英文原文：[technical-details_en.md](./technical-details_en.md)

# 技术细节

本文收集了一些偏实现层面的细节，这些内容刻意没有放进主 README。

## 运行时行为

- 服务启动本身不会抓取任何市场数据
- 图表页面/API 访问只会读取本地月文件；如果缺少所需月份，relchart 会先下载、写入，再从磁盘读回
- 仅支持固定窗口：前 3 个完整自然月 + 当前月到最近一个已完成交易日
- 浏览器中的时间范围控制被有意关闭
- Y 轴展示百分比，而不是原始价格
- 每个 symbol 的缓存文件按“每月一个文件”写入
- 历史月份只有在该月数据完整时才会写入
- 当前月文件会在首次抓取时，按当时可获得的“最近一个已完成交易日”范围写入一次

## 缓存目录结构

示例：

```text
.stocks/
  us.aapl/
    us.aapl_202512.txt
    us.aapl_202601.txt
    us.aapl_202602.txt
    us.aapl_202603.txt
  us.tsla/
    us.tsla_202512.txt
```

## 缓存文件格式

示例：

```text
20260201 260 261 257 260.5
20260202 260.5 263 255 262
```

字段：

- `date`
- `open`
- `high`
- `low`
- `close`

## HTTP 接口

- `GET /`：空白壳页面，带用法提示
- `GET /kline?stocks=...`：用于展示逗号分隔股票列表的图表页面，例如 `/kline?stocks=US.AAPL,US.TSLA`
- `GET /api/chart-data?stocks=...`：前端使用的图表快照接口
- `GET /healthz`：基础健康检查

## 说明

- 前端使用 `relchart/web/static/` 下的本地 Plotly 静态资源
- 不需要 Node.js 构建步骤
- `requirements.txt` 包含 `scipy`，因此正常安装后应默认启用 Yahoo 价格修复能力
- 图表页面的第一次请求可能更慢，因为需要抓取缺失的月度缓存文件
- 请求日志会记录单文件本地读取耗时、单次远程调用耗时，以及整页总耗时
