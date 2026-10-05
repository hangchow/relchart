# osaka 部署与自动更新方案

状态：部署设计，尚未安装到 osaka。核查日期：2026-10-06。

采用与 `~/workspace/opdash` 相同的 **独立版本目录 + Python venv + systemd 服务 + timer 拉取发布**，增加 Nginx 提供 `http://192.168.10.1/` 的 80 端口入口。

## 已核实的现状

| 项目 | 结果 |
| --- | --- |
| 目标主机 | `ssh osaka`，Ubuntu 26.04 LTS、x86_64、Python 3.14.4 |
| LAN | `enp9s0f0np0`，`192.168.10.1/24` |
| 资源 | 约 15 GiB 内存，磁盘可用约 711 GiB |
| 现有服务 | `opdash-web.service` 和 `opdash-deploy.timer` 均 active，HTTP 使用 18080 |
| 新服务端口 | 核查时 80、19090 均无监听；Nginx/Caddy/Apache 服务均非 active |
| 代码来源 | `https://github.com/hangchow/relchart.git`，匿名读取成功 |
| 发布分支 | 远端默认分支为 `main`，不是 opdash 的 `master` |
| 当前远端提交 | `214fe2c72e7b05c8d7bbacfa76c3a6855df63275` |
| 本地改动 | 折线图、取消数量限制及相关测试尚未提交；首次发布前需要提交并 push |
| 当前权限 | SSH 只读检查成功；`sudo -n ufw status` 要求交互认证，现行防火墙规则未在此次实机核验 |

参考实现：`../opdash/docs/deployment.md`、`../opdash/deploy/deploy.py` 以及其 systemd units。可以复用事务、锁、失败回滚和版本清理设计，不能直接原样复制发布器：仓库分支、入口、静态资源路径、检查接口及 OpenD 依赖均不同。

## 访问和运行结构

```mermaid
flowchart LR
    Browser[局域网浏览器] -->|192.168.10.1:80| Nginx[Nginx]
    Nginx -->|127.0.0.1:19090| App[relchart-web.service]
    App --> Cache[/var/lib/relchart/stocks/]
    App --> Market[新浪 / Yahoo]
    Push[开发机 push main] --> Git[GitHub relchart]
    Timer[relchart-deploy.timer] --> Deploy[独立构建 / 检查 / 切换 / 回滚]
    Deploy -->|fetch main| Git
    Deploy --> App
```

首页保留当前使用提示，图表 URL 为 `http://192.168.10.1/kline?stocks=US.AAPL,HK.00700`。全部标的使用同一个 `stocks` 参数，无固定数量上限。

应用只监听 `127.0.0.1:19090`，Nginx 只监听 LAN 地址的 80 端口，opdash 继续使用原有 18080。前端使用 `/static/...` 和 `/api/...` 的绝对路径，因此将 relchart 放在站点根路径；若将来改挂 `/relchart/`，必须同时适配前端 URL 和 ASGI root path。

部署中的日线数据仍由 Sina/Yahoo 获取。先前 OpenD 持仓读取是临时查询工具，不是 relchart 的常驻功能；本方案无需部署 Futu SDK、RSA 私钥或等待 OpenD 登录。若以后需要持仓变动自动更新标的，应另行将只读持仓同步实现为正式功能，标的清单和私钥保持在主机配置中。

## 目录与配置

```text
/opt/relchart/
  releases/<完整 commit SHA>/    # 代码、静态资源、该版本独立 .venv
  current -> releases/<sha>
  previous -> releases/<sha>
/var/lib/relchart/
  stocks/sina/<symbol>/          # 当前数据源的月度日线缓存
  stocks/yahoo/<symbol>/         # 切换 provider 后使用的独立缓存
/var/cache/relchart/             # 第三方库的可写缓存
/var/lib/relchart-deploy/
  repo.git/
  state.json
  deploy.lock
/etc/relchart/relchart.env
/usr/local/libexec/relchart/     # 管理员安装的固定启动、发布程序
/etc/systemd/system/            # web.service、deploy.service、deploy.timer
/etc/nginx/sites-available/relchart
```

拟用配置：

```ini
WEB_HOST=127.0.0.1
WEB_PORT=19090
DATA_DIR=/var/lib/relchart/stocks
PROVIDER=sina
TZ=Asia/Shanghai
XDG_CACHE_HOME=/var/cache/relchart
```

这些环境变量由待实现的固定 `start.py` 转为 CLI 参数；当前 CLI 不会自动读取它们。等价启动命令：

```bash
/opt/relchart/current/.venv/bin/python -u /opt/relchart/current/relchart.py \
  --web_host 127.0.0.1 --web_port 19090 \
  --data_dir /var/lib/relchart/stocks --provider sina
```

缓存路径由代码按 `data_dir / provider` 拼接，所以当前缓存实际位于 `/var/lib/relchart/stocks/sina/`。不能将 `DATA_DIR` 设置成已含 `sina` 的路径，否则会形成 `sina/sina/`。

首次部署可以将本机 `.stocks/sina/` 复制到服务器的 `stocks/sina/`，在首次启动前完成所有权校正。缓存不进入 Git、不放入 release，不随发布或回滚删除。开发机的 macOS `.venv` 不复制，服务器使用 Linux Python 重建。

## 运行和入口服务

创建独立系统用户 `relchart` 和 `relchart-deploy`。前者可读取代码，只能写入运行状态与缓存目录；后者可写 release 和发布状态，以非 root 身份安装依赖。发布用户仅获得固定的 `systemctl start/stop/restart relchart-web.service` 权限。

应用使用单进程，不启用 reload 或多个 worker。拟配置 `Restart=on-failure`、`RestartSec=10s`、停止超时 30 秒，初始资源预算为单核 CPU、1 GiB 内存。部署任务预算为单核 CPU、2 GiB 内存，并降低调度优先级。设置 `ProtectSystem=strict`、`ProtectHome=yes` 和显式可写状态/缓存目录；运行进程禁用额外提权。按实际行情加载峰值调整预算。

Nginx 配置草案：

```nginx
server {
    listen 192.168.10.1:80;
    server_name 192.168.10.1;

    allow 192.168.10.0/24;
    deny all;

    location / {
        proxy_pass http://127.0.0.1:19090;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 5s;
        proxy_read_timeout 120s;
    }
}
```

该配置透传原有路径及查询参数；120 秒用于容纳首次缺失缓存下载，并不是行情任务的总执行时限。使用 Nginx 前先检查既有站点配置，避免发行版默认站点额外监听所有地址的 80 端口。通过 `nginx -t` 后启用。[Nginx 官方代理文档](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_pass)

实施时核验现行 UFW/nft 规则，只新增 LAN 接口、来源 `192.168.10.0/24`、目标 `192.168.10.1` 的 TCP 80 放行规则。该设计保持 opdash、OpenD、网关 NAT/转发规则不变；当前方案入口为 LAN，Tailscale 访问需要另配明确的入口和访问规则。

## 自动发布流程

发布器每轮结束后等待约 60 秒，再检查远端 `main`。本地修改文件或只 commit 不会触发；push 后的发布延迟包含轮询、依赖安装、测试及服务检查时间。

1. 获取部署锁，检查暂停标志，优先恢复上次未完成的事务。手工操作与 timer 共用同一把锁。
2. 有超时地 fetch `refs/heads/main`，解析完整 SHA。目标 SHA 与当前一致则退出，不重启服务；拉取失败保留现有版本。
3. 将目标 SHA 导出到最终 release 路径，在该路径创建独立 venv，以目标平台验证的 `requirements.lock` 安装全部锁定依赖。准备失败不影响运行版本，不移动已经建立的 venv。
4. 运行 `pip check`、编译/导入检查、`unittest discover -s tests -v`、静态资源检查及离线 HTTP 绘图冒烟测试。测试使用固定日期、测试 provider 和独立临时数据目录，不写生产缓存。
5. 记录旧 SHA、目标 SHA 和发布阶段；停止旧进程，原子替换 `current` 软链，然后启动新进程。保留数秒切换中断，不承诺零停机。
6. 期限内连续三次检查回环接口：`/healthz` 的目标发布 SHA、`/readyz`、首页及 JS/CSS/Plotly。检查实际进程就绪，不能仅凭软链指向或 HTTP 200 判断。
7. 成功后更新 `previous`、成功 SHA 和完成时间；通过 LAN 的 Nginx 入口检查主页与图表 API。首次上线还验证真实 Sina 数据，并按需验证 Yahoo。外部行情超时或限流单独记为数据源问题，不能自动判定为新代码故障。
8. 新版本启动或本地就绪检查失败，恢复旧软链、重启并检查旧版本；首次没有可回滚版本时记录失败。回滚也失败则暂停自动发布并保留诊断状态。
9. 失败 SHA 冷却 30 分钟，支持手工重试；新 SHA 可立即处理。保留最近 3 个成功 release，清理始终保护 current、previous 和事务涉及的目录，不涉及缓存。

定时器草案：

```ini
[Unit]
Description=Check relchart main updates

[Timer]
OnBootSec=2min
OnUnitInactiveSec=60s
AccuracySec=5s
Unit=relchart-deploy.service

[Install]
WantedBy=timers.target
```

对应 service 使用 `Type=oneshot`，不设置 `RemainAfterExit=yes`；总发布超时建议 20 分钟。运行中的同名 service 不会因 timer 再次触发而启动第二个实例；文件锁也覆盖手动发布。[systemd timer 官方文档](https://github.com/systemd/systemd/blob/main/man/systemd.timer.xml)

该流程以服务器上的候选测试作为发布门禁，不默认等待 GitHub Actions。若以后要求远端 CI 必须成功，应对准确目标 SHA 额外核验 CI 状态。

## 本项目上线前需要补齐的内容

| 待实现项 | 具体要求 |
| --- | --- |
| `requirements.lock` | 在 Ubuntu x86_64 / Python 3.14 环境锁定并验证全部传递依赖；不直接复制 macOS 的 freeze |
| `/healthz` 版本信息 | 启动时固定读取 `RELCHART_RELEASE`，返回进程实际 SHA；开发环境标记为 dev |
| `/readyz` | 只检查本地服务初始化、数据目录可写及必要静态资源；不得为了就绪检查联网下载行情 |
| HTTP 非阻塞 | 当前 async 路由直接运行同步 `get_snapshot()`，行情下载会阻塞健康请求；需放入工作线程，并以单实例锁串行访问共享 provider 与缓存 |
| 有界行情操作 | 核实底层接口超时；不支持超时的调用应采用可终止的独立任务。线程超时不能冒充实际取消下载 |
| 发布版本的前端资源 | HTML 返回前插入发布 SHA，JS/CSS URL 携带该版本；HTML 强制重新验证，避免浏览器沿用旧 API 格式 |
| 离线 HTTP 测试 | 覆盖普通折线、比值线、盘中点、超过 5 个标的，以及行情处理期间健康接口可响应 |
| `deploy/start.py` | 从受控环境构造 CLI 参数、固定进程发布 SHA，以 exec 启动；不读取 OpenD 配置 |
| `deploy/deploy.py` | 从 opdash 流程适配 main 分支、本项目目录、静态文件与健康接口；去掉 OpenD 就绪门禁 |
| 配套安装文件 | web/deploy/timer units、环境示例、Nginx 站点、安装器及发布流程测试 |

上述内容均为本次方案中的后续实施项，当前仓库尚无这些部署程序。管理员安装的 `/usr/local/libexec/relchart/` 程序、systemd unit、Nginx 和防火墙配置不随 Git push 以 root 自动覆盖；基础设施文件变更单独安装，业务代码、资源和依赖锁随 main 自动发布。

当前普通标的的 API 已由 `bars` 改为 `points`，因此首次发布应将后端和前端作为同一 release 切换，并验证浏览器刷新获取新版本。

## 首次实施与验收

实施顺序：补齐上表内容并在本地测试 → 在目标平台验证锁定依赖 → 将当前业务修改与部署文件提交到 main 并 push → 管理员安装服务和 Nginx → 准备持久缓存 → 首次手动发布 → 验证真实图表与失败回滚 → 启用 timer → 用一次 main 更新验证自动发布。

此前检查发现非交互 sudo 不可用，正式安装需要 osaka 上可执行管理员操作的会话；这不影响当前方案和只读环境核查。

验收至少覆盖：

- `http://192.168.10.1/` 和带 `stocks` 的图表地址能从 LAN 打开，10 个标的绘制在同一张折线图。
- main 新提交自动上线，HTTP 中的 release SHA 与目标一致；无新提交不重启。
- 构建失败保持旧服务；候选启动失败能恢复 previous；手动回滚同时暂停自动升级。
- 缓存路径始终为 `/var/lib/relchart/stocks/<provider>/`，升级、回滚后缓存仍在。
- 健康检查不因慢行情请求被阻塞；Sina/Yahoo 暂时不可用时不会发生反复版本回滚。
- 重启应用后服务恢复，开机启动配置正确；保留现有 opdash 18080、OpenD 11111 和网关功能。

部署落地后日常检查使用：

```bash
systemctl status relchart-web.service
systemctl list-timers relchart-deploy.timer
journalctl -u relchart-web.service -n 100 --no-pager
journalctl -u relchart-deploy.service -n 100 --no-pager
```

发布器拟提供 `status`、`update`、`update --retry`、`pause`、`resume`、`rollback [sha]`；rollback 在同一锁内设置暂停，防止下一轮立即重新部署被回滚的版本。停用 timer 本身不会取消已经开始的任务。
