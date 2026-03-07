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
from .storage import FileStorage
from .symbols import RatioSymbol, StockSymbol, parse_request_items
from .transform import assign_distinct_colors, to_percent_bars, to_percent_line_points
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
        items = parse_request_items(stocks_arg)
        symbols = self._collect_symbols(items)
        today = self.config.today or date.today()
        window = build_window(today)
        warnings: list[str] = []
        context = RequestContext()
        started = perf_counter()

        logger.info(
            "chart request started stocks=%s window=%s..%s",
            ",".join(item.canonical for item in items),
            window.start_date,
            window.end_date,
        )

        for symbol in symbols:
            self._sync_symbol(symbol, window, warnings, context)

        snapshot = self._build_snapshot(window, items, warnings, context)
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
            ",".join(item.canonical for item in items),
            elapsed * 1000.0,
            context.metrics.local_read_seconds * 1000.0,
            context.metrics.local_reads,
            context.metrics.remote_seconds * 1000.0,
            context.metrics.remote_requests,
        )
        return snapshot

    def _collect_symbols(
        self,
        items: list[StockSymbol | RatioSymbol],
    ) -> list[StockSymbol]:
        symbols_by_canonical: dict[str, StockSymbol] = {}
        for item in items:
            if isinstance(item, RatioSymbol):
                symbols_by_canonical.setdefault(item.numerator.canonical, item.numerator)
                symbols_by_canonical.setdefault(item.denominator.canonical, item.denominator)
                continue
            symbols_by_canonical.setdefault(item.canonical, item)
        return list(symbols_by_canonical.values())

    def _sync_symbol(
        self,
        symbol: StockSymbol,
        window,
        warnings: list[str],
        context: RequestContext,
    ) -> None:
        for month in window.months:
            if self.storage.month_exists(symbol, month.key):
                continue

            fetch_end = month.end_date
            if month.is_current:
                cutoff = self.provider.last_completed_trading_day(symbol)
                if cutoff is None or cutoff < month.start_date:
                    logger.info("%s: no completed trading day in current month yet", symbol.canonical)
                    continue
                fetch_end = min(cutoff, window.end_date)

            bars = self._fetch_daily_bars(
                symbol,
                month.start_date,
                fetch_end,
                context,
                reason=f"missing month file {month.key}",
            )
            if month.is_current:
                if bars:
                    self.storage.write_month_file(symbol, month.key, bars)
                    context.month_cache[(symbol.canonical, month.key)] = bars
                continue

            if self._is_complete_historical_month(symbol, month.start_date, fetch_end, bars):
                self.storage.write_month_file(symbol, month.key, bars)
                context.month_cache[(symbol.canonical, month.key)] = bars
                continue

            warnings.append(
                f"{symbol.canonical}: skipped writing incomplete historical month {month.key}"
            )

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
        items: list[StockSymbol | RatioSymbol],
        warnings: list[str],
        context: RequestContext,
    ) -> dict:
        series = []
        month_keys = [month.key for month in window.months]
        snapshot_warnings = list(warnings)

        for item in items:
            if isinstance(item, RatioSymbol):
                ratio_series = self._build_ratio_series(
                    item,
                    window.start_date,
                    month_keys,
                    snapshot_warnings,
                    context,
                )
                if ratio_series is not None:
                    series.append(ratio_series)
                continue

            symbol_series = self._build_symbol_series(
                item,
                window.start_date,
                month_keys,
                snapshot_warnings,
                context,
            )
            if symbol_series is not None:
                series.append(symbol_series)

        colors = assign_distinct_colors([item["symbol"] for item in series])
        for item in series:
            item["color"] = colors[item["symbol"]]

        return {
            "title": "Relative Daily K Overlay",
            "generated_at": datetime.now(UTC).isoformat(),
            "window": {
                "start": window.start_date.isoformat(),
                "end": window.end_date.isoformat(),
            },
            "requested_symbols": [item.canonical for item in items],
            "series": series,
            "warnings": snapshot_warnings,
        }

    def _build_symbol_series(
        self,
        symbol: StockSymbol,
        window_start: date,
        month_keys: list[str],
        warnings: list[str],
        context: RequestContext,
    ) -> dict | None:
        bars = self._read_window_bars(symbol, month_keys, context)
        if not bars:
            warnings.append(
                f"{symbol.canonical}: no cached data in requested window"
            )
            return None

        display_name = self._display_name_for_symbol(
            symbol,
            context,
            reason=f"display name for {symbol.canonical}",
        )

        base_close = self._find_previous_close_in_cache(symbol, window_start, context)
        if base_close is None:
            base_close = self._fetch_previous_close(
                symbol,
                window_start,
                context,
                reason=f"base close before {window_start}",
            )
        if base_close is None:
            base_close = bars[0].open
            warnings.append(
                f"{symbol.canonical}: previous close unavailable, fell back to first visible open"
            )

        return {
            "symbol": symbol.canonical,
            "display_name": display_name,
            "market": symbol.market,
            "series_type": "candlestick",
            "base_close": round(base_close, 4),
            "bars": to_percent_bars(bars, base_close),
        }

    def _build_ratio_series(
        self,
        ratio: RatioSymbol,
        window_start: date,
        month_keys: list[str],
        warnings: list[str],
        context: RequestContext,
    ) -> dict | None:
        numerator_bars = self._read_window_bars(ratio.numerator, month_keys, context)
        denominator_bars = self._read_window_bars(ratio.denominator, month_keys, context)
        if not numerator_bars:
            warnings.append(
                f"{ratio.numerator.canonical}: no cached data in requested window for ratio {ratio.canonical}"
            )
            return None
        if not denominator_bars:
            warnings.append(
                f"{ratio.denominator.canonical}: no cached data in requested window for ratio {ratio.canonical}"
            )
            return None

        numerator_by_date = {bar.date: bar for bar in numerator_bars}
        denominator_by_date = {bar.date: bar for bar in denominator_bars}
        shared_dates = sorted(set(numerator_by_date) & set(denominator_by_date))
        if not shared_dates:
            warnings.append(f"{ratio.canonical}: no overlapping trading dates in requested window")
            return None

        ratio_values = [
            (
                trading_date.isoformat(),
                numerator_by_date[trading_date].close / denominator_by_date[trading_date].close,
            )
            for trading_date in shared_dates
        ]

        base_value = self._find_ratio_base_value(ratio, window_start, context)
        if base_value is None:
            base_value = ratio_values[0][1]
            warnings.append(
                f"{ratio.canonical}: previous ratio close unavailable, fell back to first visible close"
            )

        numerator_name = self._display_name_for_symbol(
            ratio.numerator,
            context,
            reason=f"display name for {ratio.numerator.canonical}",
        )
        denominator_name = self._display_name_for_symbol(
            ratio.denominator,
            context,
            reason=f"display name for {ratio.denominator.canonical}",
        )
        display_name = f"{numerator_name} / {denominator_name}"

        return {
            "symbol": ratio.canonical,
            "display_name": display_name,
            "market": "RATIO",
            "series_type": "line",
            "points": to_percent_line_points(ratio_values, base_value),
        }

    def _display_name_for_symbol(
        self,
        symbol: StockSymbol,
        context: RequestContext,
        reason: str,
    ) -> str:
        display_name = symbol.canonical
        if symbol.market != "YF":
            return display_name

        fetched_name = self._fetch_display_name(symbol, context, reason=reason)
        if fetched_name:
            return fetched_name
        return display_name

    def _find_ratio_base_value(
        self,
        ratio: RatioSymbol,
        before_date: date,
        context: RequestContext,
    ) -> float | None:
        numerator_close = self._find_previous_close_in_cache(ratio.numerator, before_date, context)
        if numerator_close is None:
            numerator_close = self._fetch_previous_close(
                ratio.numerator,
                before_date,
                context,
                reason=f"ratio base close before {before_date}",
            )

        denominator_close = self._find_previous_close_in_cache(ratio.denominator, before_date, context)
        if denominator_close is None:
            denominator_close = self._fetch_previous_close(
                ratio.denominator,
                before_date,
                context,
                reason=f"ratio base close before {before_date}",
            )

        if numerator_close is None or denominator_close is None:
            return None
        return numerator_close / denominator_close

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
