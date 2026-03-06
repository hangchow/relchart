from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from time import perf_counter

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import AppConfig
from .models import DailyBar
from .providers import YahooProvider
from .storage import FileStorage, merge_bars
from .symbols import StockSymbol, parse_symbols
from .transform import color_for_symbol, to_percent_bars
from .web.routes import register_routes
from .window import build_window

logger = logging.getLogger(__name__)


@dataclass
class RequestMetrics:
    local_read_seconds: float = 0.0
    remote_seconds: float = 0.0
    local_reads: int = 0
    remote_requests: int = 0
    remote_events: list["RemoteEvent"] = field(default_factory=list)


@dataclass
class RemoteEvent:
    symbol: str
    kind: str
    reason: str
    elapsed_seconds: float


@dataclass
class RequestContext:
    metrics: RequestMetrics = field(default_factory=RequestMetrics)
    month_cache: dict[tuple[str, str], list[DailyBar]] = field(default_factory=dict)


class RelChartService:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.provider = YahooProvider()
        self.storage = FileStorage(config.data_dir)

    def get_snapshot(self, stocks_arg: str) -> dict:
        symbols = parse_symbols(stocks_arg)
        today = self.config.today or date.today()
        window = build_window(today)
        warnings: list[str] = []
        context = RequestContext()
        started = perf_counter()

        logger.info(
            "chart request started stocks=%s window=%s..%s",
            ",".join(symbol.canonical for symbol in symbols),
            window.start_date,
            window.end_date,
        )

        for symbol in symbols:
            self._sync_symbol(symbol, window, warnings, context)

        snapshot = self._build_snapshot(window, symbols, warnings, context)
        elapsed = perf_counter() - started
        for index, event in enumerate(context.metrics.remote_events, start=1):
            logger.info(
                "chart request remote timing index=%d/%d symbol=%s kind=%s "
                "elapsed_ms=%.2f reason=%s",
                index,
                len(context.metrics.remote_events),
                event.symbol,
                event.kind,
                event.elapsed_seconds * 1000.0,
                event.reason,
            )
        logger.info(
            "chart request finished stocks=%s total_ms=%.2f local_read_ms=%.2f "
            "local_reads=%d remote_ms=%.2f remote_requests=%d",
            ",".join(symbol.canonical for symbol in symbols),
            elapsed * 1000.0,
            context.metrics.local_read_seconds * 1000.0,
            context.metrics.local_reads,
            context.metrics.remote_seconds * 1000.0,
            context.metrics.remote_requests,
        )
        return snapshot

    def _sync_symbol(
        self,
        symbol: StockSymbol,
        window,
        warnings: list[str],
        context: RequestContext,
    ) -> None:
        historical_months = [month for month in window.months if not month.is_current]
        for month in historical_months:
            file_exists = self.storage.month_exists(symbol, month.key)
            if file_exists and not self.config.repair_history:
                continue

            bars = self._fetch_daily_bars(
                symbol,
                month.start_date,
                month.end_date,
                context,
                reason=f"historical month {month.key}",
            )
            if self._is_complete_historical_month(symbol, month.start_date, month.end_date, bars):
                self.storage.write_month_file(symbol, month.key, bars)
                context.month_cache[(symbol.canonical, month.key)] = bars
                continue

            warnings.append(
                f"{symbol.canonical}: skipped writing incomplete historical month {month.key}"
            )

        current_month = next(month for month in window.months if month.is_current)
        cutoff = self.provider.last_completed_trading_day(symbol)
        if cutoff is None or cutoff < current_month.start_date:
            logger.info("%s: no completed trading day in current month yet", symbol.canonical)
            return

        fetch_end = min(cutoff, window.end_date)
        existing = self._read_month_file(
            symbol,
            current_month.key,
            context,
            reason="current-month cache check",
        )
        expected_days = self.provider.fetch_trading_days(
            symbol,
            current_month.start_date,
            fetch_end,
        )
        local_days = {bar.date for bar in existing if current_month.start_date <= bar.date <= fetch_end}
        missing_days = [trading_day for trading_day in expected_days if trading_day not in local_days]

        if not missing_days:
            logger.info(
                "%s: current-month cache already complete through %s, skip remote fetch",
                symbol.canonical,
                fetch_end,
            )
            return

        fetch_start = missing_days[0]
        fetched = self._fetch_daily_bars(
            symbol,
            fetch_start,
            fetch_end,
            context,
            reason=(
                f"current month refresh missing_days={len(missing_days)} "
                f"from={fetch_start} to={fetch_end}"
            ),
        )
        merged = [bar for bar in merge_bars(existing, fetched) if bar.date <= fetch_end]
        if fetched and merged:
            self.storage.write_month_file(symbol, current_month.key, merged)
            context.month_cache[(symbol.canonical, current_month.key)] = merged
            return

        if existing:
            warnings.append(
                f"{symbol.canonical}: kept existing current-month cache because remote returned no bars"
            )
            return

        warnings.append(f"{symbol.canonical}: no current-month data returned from Yahoo")

    def _is_complete_historical_month(
        self,
        symbol: StockSymbol,
        start_date: date,
        end_date: date,
        bars,
    ) -> bool:
        if not bars:
            return False
        expected_days = self.provider.fetch_trading_days(symbol, start_date, end_date)
        actual_days = {bar.date for bar in bars}
        return actual_days == set(expected_days)

    def _build_snapshot(
        self,
        window,
        symbols: list[StockSymbol],
        warnings: list[str],
        context: RequestContext,
    ) -> dict:
        series = []
        month_keys = [month.key for month in window.months]
        snapshot_warnings = list(warnings)

        for symbol in symbols:
            bars = self._read_window_bars(symbol, month_keys, context)
            if not bars:
                snapshot_warnings.append(
                    f"{symbol.canonical}: no cached data in requested window"
                )
                continue

            display_name = symbol.canonical
            if symbol.market == "YF":
                fetched_name = self._fetch_display_name(
                    symbol,
                    context,
                    reason=f"display name for {symbol.canonical}",
                )
                if fetched_name:
                    display_name = fetched_name

            base_close = self._find_previous_close_in_cache(symbol, window.start_date, context)
            if base_close is None:
                base_close = self._fetch_previous_close(
                    symbol,
                    window.start_date,
                    context,
                    reason=f"base close before {window.start_date}",
                )
            if base_close is None:
                base_close = bars[0].open
                snapshot_warnings.append(
                    f"{symbol.canonical}: previous close unavailable, fell back to first visible open"
                )

            series.append(
                {
                    "symbol": symbol.canonical,
                    "display_name": display_name,
                    "market": symbol.market,
                    "color": color_for_symbol(symbol.canonical),
                    "base_close": round(base_close, 4),
                    "bars": to_percent_bars(bars, base_close),
                }
            )

        return {
            "title": "Relative Daily K Overlay",
            "generated_at": datetime.now(UTC).isoformat(),
            "window": {
                "start": window.start_date.isoformat(),
                "end": window.end_date.isoformat(),
            },
            "requested_symbols": [symbol.canonical for symbol in symbols],
            "series": series,
            "warnings": snapshot_warnings,
        }

    def _read_window_bars(
        self,
        symbol: StockSymbol,
        month_keys: list[str],
        context: RequestContext,
    ) -> list[DailyBar]:
        merged: dict[date, DailyBar] = {}
        for month_key in month_keys:
            for bar in self._read_month_file(
                symbol,
                month_key,
                context,
                reason="window snapshot build",
            ):
                merged[bar.date] = bar
        return sorted(merged.values(), key=lambda item: item.date)

    def _read_month_file(
        self,
        symbol: StockSymbol,
        month_key: str,
        context: RequestContext,
        reason: str,
    ) -> list[DailyBar]:
        cache_key = (symbol.canonical, month_key)
        if cache_key in context.month_cache:
            bars = context.month_cache[cache_key]
            logger.info(
                "local cache hit symbol=%s month=%s reason=%s bars=%d",
                symbol.canonical,
                month_key,
                reason,
                len(bars),
            )
            return bars

        path = self.storage.month_file_path(symbol, month_key)
        exists = path.exists()
        started = perf_counter()
        bars = self.storage.read_month_file(symbol, month_key)
        elapsed = perf_counter() - started
        context.metrics.local_read_seconds += elapsed
        context.metrics.local_reads += 1
        context.month_cache[cache_key] = bars
        logger.info(
            "local read symbol=%s month=%s reason=%s path=%s exists=%s bars=%d elapsed_ms=%.2f",
            symbol.canonical,
            month_key,
            reason,
            path,
            exists,
            len(bars),
            elapsed * 1000.0,
        )
        return bars

    def _fetch_daily_bars(
        self,
        symbol: StockSymbol,
        start_date: date,
        end_date: date,
        context: RequestContext,
        reason: str,
    ) -> list[DailyBar]:
        started = perf_counter()
        bars = self.provider.fetch_daily_bars(symbol, start_date, end_date)
        elapsed = perf_counter() - started
        context.metrics.remote_seconds += elapsed
        context.metrics.remote_requests += 1
        context.metrics.remote_events.append(
            RemoteEvent(
                symbol=symbol.canonical,
                kind="daily-bars",
                reason=reason,
                elapsed_seconds=elapsed,
            )
        )
        logger.info(
            "remote fetch kind=daily-bars symbol=%s yahoo_symbol=%s reason=%s "
            "start=%s end=%s bars=%d elapsed_ms=%.2f",
            symbol.canonical,
            symbol.yahoo_symbol,
            reason,
            start_date,
            end_date,
            len(bars),
            elapsed * 1000.0,
        )
        return bars

    def _fetch_previous_close(
        self,
        symbol: StockSymbol,
        before_date: date,
        context: RequestContext,
        reason: str,
    ) -> float | None:
        started = perf_counter()
        previous_close = self.provider.fetch_previous_close(symbol, before_date)
        elapsed = perf_counter() - started
        context.metrics.remote_seconds += elapsed
        context.metrics.remote_requests += 1
        context.metrics.remote_events.append(
            RemoteEvent(
                symbol=symbol.canonical,
                kind="previous-close",
                reason=reason,
                elapsed_seconds=elapsed,
            )
        )
        logger.info(
            "remote fetch kind=previous-close symbol=%s yahoo_symbol=%s reason=%s "
            "before=%s close=%s elapsed_ms=%.2f",
            symbol.canonical,
            symbol.yahoo_symbol,
            reason,
            before_date,
            "none" if previous_close is None else f"{previous_close:.4f}",
            elapsed * 1000.0,
        )
        return previous_close

    def _fetch_display_name(
        self,
        symbol: StockSymbol,
        context: RequestContext,
        reason: str,
    ) -> str | None:
        started = perf_counter()
        display_name, from_remote = self.provider.fetch_display_name(symbol)
        elapsed = perf_counter() - started
        if from_remote:
            context.metrics.remote_seconds += elapsed
            context.metrics.remote_requests += 1
            context.metrics.remote_events.append(
                RemoteEvent(
                    symbol=symbol.canonical,
                    kind="display-name",
                    reason=reason,
                    elapsed_seconds=elapsed,
                )
            )
        logger.info(
            "%s kind=display-name symbol=%s yahoo_symbol=%s reason=%s "
            "display_name=%s elapsed_ms=%.2f",
            "remote fetch" if from_remote else "metadata cache hit",
            symbol.canonical,
            symbol.yahoo_symbol,
            reason,
            "none" if display_name is None else display_name,
            elapsed * 1000.0,
        )
        return display_name

    def _find_previous_close_in_cache(
        self,
        symbol: StockSymbol,
        before_date: date,
        context: RequestContext,
    ) -> float | None:
        trading_days = self.provider.fetch_trading_days(
            symbol,
            before_date - timedelta(days=15),
            before_date - timedelta(days=1),
        )
        if not trading_days:
            return None

        previous_trading_day = trading_days[-1]
        month_key = previous_trading_day.strftime("%Y%m")
        for bar in self._read_month_file(
            symbol,
            month_key,
            context,
            reason=f"previous-close cache lookup for {previous_trading_day}",
        ):
            if bar.date == previous_trading_day:
                logger.info(
                    "previous close cache hit symbol=%s trade_date=%s close=%.4f",
                    symbol.canonical,
                    previous_trading_day,
                    bar.close,
                )
                return bar.close
        return None


def create_app(config: AppConfig) -> FastAPI:
    service = RelChartService(config)

    static_dir = Path(__file__).resolve().parent / "web" / "static"
    app = FastAPI(title="relchart")
    app.state.relchart_service = service
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    register_routes(app, static_dir)
    return app
