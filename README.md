英文原文：[README_en.md](./README_en.md)

# relchart

相对涨跌幅日 K 线叠加 Web 工具。

`relchart` 会启动一个本地 Web 服务器，在浏览器中渲染固定窗口的多标的百分比 K 线图。访问图表 URL 时才按需读取月度文件；若本地缺失对应文件，程序会先下载、写入磁盘缓存，再从本地缓存读取。

## 数据源支持

- 当前通过 `yfinance` 使用 Yahoo Finance 公开的日线数据
- 支持 `US.*`、`HK.*` 和 `YF.*` 三种 symbol 输入
- 支持 `<symbol>/<symbol>` 形式的比值项，例如 `YF.GC=F/YF.SI=F`
- 不依赖 Futu OpenD
- 缺失月文件时需要能够访问外网
- 数据拉取由页面/API 访问触发，不会在服务启动时主动执行

Yahoo symbol 映射示例：

- `US.AAPL -> AAPL`
- `US.BRK.B -> BRK-B`
- `HK.00700 -> 0700.HK`
- `HK.700 -> 0700.HK`（会规范化为标准形式 `HK.00700`）
- `YF.GC=F -> GC=F`
- `YF.SI=F -> SI=F`

`HK.*` 使用港交所数字代码，而不是名称别名。请在 `HK.` 前缀后填写交易所代码，并优先使用 5 位标准形式：

- 腾讯：`HK.00700`，不要写 `HK.TCH`
- 阿里巴巴-W：`HK.09988`

在 Yahoo Finance 侧，relchart 会把 5 位标准 HK 代码转换为 4 位 `.HK` symbol，即去掉一个前导零。例如：`HK.00700 -> 0700.HK`。

`YF.*` 是原样透传给 Yahoo Finance 的前缀，适合 Yahoo 原生支持、但不是普通股票代码的 symbol，例如：

- 期货，如 `GC=F` 和 `SI=F`
- 外汇对，如 `EURUSD=X`
- 指数，如 `^GSPC`
- 加密货币对，如 `BTC-USD`

对于 `YF.*`，relchart 会尽力推断交易日历。`GC=F` 和 `SI=F` 已按 Yahoo 当前日线行为做了显式对齐，采用类似 `XNYS` 的“已完成交易日”日程；常见的 `=X`、`-USD`、`=F` 和 `^...` 形式也内置了启发式规则。当 Yahoo 返回 `shortName` 时，relchart 会在页面标题、图例和悬浮标签中使用该英文显示名，同时把原始 symbol 作为辅助文本保留。

比值项使用 `<symbol>/<symbol>` 语法。它们会基于日收盘价比值渲染为折线，并且可以和普通 K 线 symbol 混合出现在同一个 `stocks` 查询里。

## 快速开始

创建并激活虚拟环境：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

启动 Web 应用：

```bash
python relchart.py
```

可选参数：

- `--data_dir DIR`
- `--web_host HOST`
- `--web_port PORT`

然后打开：

```text
http://127.0.0.1:19090/kline?stocks=US.AAPL,US.TSLA
```

你也可以只传一个股票代码，查看单标的日 K 图。

## 示例

打开单个股票：

[`http://127.0.0.1:19090/kline?stocks=HK.700`](http://127.0.0.1:19090/kline?stocks=HK.700)

`HK.700` 会被规范化为标准形式 `HK.00700`，并渲染为单标的日 K 图。

![单个港股示例](docs/images/hk-700-single.png)

对比多个股票：

[`http://127.0.0.1:19090/kline?stocks=HK.00700,US.MSFT`](http://127.0.0.1:19090/kline?stocks=HK.00700,US.MSFT)

![港股和美股对比示例](docs/images/hk-700-msft.png)

打开 Yahoo 原生 symbol：

[`http://127.0.0.1:19090/kline?stocks=YF.GC=F,YF.SI=F`](http://127.0.0.1:19090/kline?stocks=YF.GC%3DF,YF.SI%3DF)

![黄金和白银示例](docs/images/yf-gc-si.png)

打开单条比值线：

[`http://127.0.0.1:19090/kline?stocks=YF.GC=F/YF.SI=F`](http://127.0.0.1:19090/kline?stocks=YF.GC%3DF%2FYF.SI%3DF)

![黄金和白银比值线示例](docs/images/ratio-gc-si-only.png)

对比多条比值线：

[`http://127.0.0.1:19090/kline?stocks=YF.GC=F/YF.SI=F,YF.GC=F/YF.HG=F,YF.GC=F/YF.ALI=F`](http://127.0.0.1:19090/kline?stocks=YF.GC%3DF%2FYF.SI%3DF,YF.GC%3DF%2FYF.HG%3DF,YF.GC%3DF%2FYF.ALI%3DF)

![比值线对比示例](docs/images/ratio-gc-si-hg-ali.png)

打开同时包含 K 线和比值线的混合图表：

[`http://127.0.0.1:19090/kline?stocks=US.MSFT,YF.GC=F/YF.SI=F`](http://127.0.0.1:19090/kline?stocks=US.MSFT,YF.GC%3DF%2FYF.SI%3DF)

![混合 K 线和比值线示例](docs/images/ratio-gc-si-msft.png)

当 Yahoo 原生 symbol 含有 `=` 这类 URL 保留字符时，手动书写 URL 需要先对查询值进行编码。前端在发起 API 请求时已经自动处理了这一步。

## 进一步说明

- 月文件会在访问时按需从 `data_dir` 读取；如果缺失，relchart 会先下载并存到本地
- 如果你想刷新某个 symbol 的数据，删除 `data_dir` 下对应的月文件后重新访问页面即可
- 缓存目录结构、文件格式、HTTP 接口及其他实现细节见 [`docs/technical-details.md`](docs/technical-details.md)

## 故障排查

- 出现 `ModuleNotFoundError: fastapi`、`uvicorn` 或 `yfinance`：运行 `pip install -r requirements.txt`
- 图表为空或请求失败：检查网络连接、股票代码格式，以及 URL 中的 `stocks` 查询参数
- `YF.*` symbol 会原样传给 Yahoo；如果 Yahoo 本身不识别该 symbol，relchart 无法在本地修复
- 端口已被占用：修改 `--web_port`
