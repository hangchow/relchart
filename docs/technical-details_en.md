中文版本：[technical-details.md](./technical-details.md)

# Technical Details

This document collects implementation-oriented details that are intentionally kept out of the main
README.

## Runtime Behavior

- Server startup itself does not fetch any market data
- Chart page/API access only reads local month files; if a required month file is missing,
  relchart downloads it, writes it, then reads it from disk
- Fixed window only: previous 3 full natural months plus current month to the latest completed
  trading day
- Browser time-range controls are intentionally disabled
- Y-axis is percentage, not raw price
- For each symbol, cache files are written as one file per month
- Historical months are only written if the fetched month is complete
- Current month file is written once for the latest completed trading day range available at first
  fetch

## Cache Layout

Example:

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

## Cache File Format

Example:

```text
20260201 260 261 257 260.5
20260202 260.5 263 255 262
```

Columns:

- `date`
- `open`
- `high`
- `low`
- `close`

## HTTP Endpoints

- `GET /`: empty shell page with usage hint
- `GET /kline?stocks=...`: chart page for a comma-separated stock list, for example
  `/kline?stocks=US.AAPL,US.TSLA`
- `GET /api/chart-data?stocks=...`: chart snapshot used by the frontend
- `GET /healthz`: basic health status

## Notes

- Frontend uses local Plotly assets under `relchart/web/static/`
- No Node.js build step is required
- `requirements.txt` includes `scipy`, so Yahoo price repair should be enabled by default after a
  normal install
- First request for a chart page can take longer because missing monthly cache files must be fetched
- Request logs include per-file local read timing, per-remote-call timing, and per-page aggregate
  timing
