from __future__ import annotations

import importlib.util
import json
import logging
import math
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import exchange_calendars as xcals
import pandas as pd
import yfinance as yf

from relchart.models import DailyBar
from relchart.symbols import StockSymbol

logger = logging.getLogger(__name__)

CALENDAR_BY_MARKET = {
    "US": "XNYS",
    "HK": "XHKG",
    "YF": "24/5",
}


class YahooProvider:
    def __init__(self) -> None:
        self._calendars = {}
        for calendar_name in sorted(set(CALENDAR_BY_MARKET.values()) | {"24/7"}):
            self._calendars[calendar_name] = xcals.get_calendar(calendar_name)
        self._tickers: dict[str, yf.Ticker] = {}
        self._display_names: dict[str, str | None] = {}
        self._repair_enabled = importlib.util.find_spec("scipy") is not None
        if not self._repair_enabled:
            logger.info("scipy not installed, Yahoo price repair is disabled")

    def fetch_daily_bars(
        self,
        symbol: StockSymbol,
        start_date: date,
        end_date: date,
    ) -> list[DailyBar]:
        if end_date < start_date:
            return []

        try:
            history = self._ticker(symbol.yahoo_symbol).history(
                start=start_date.isoformat(),
                end=(end_date + timedelta(days=1)).isoformat(),
                interval="1d",
                auto_adjust=True,
                repair=self._repair_enabled,
                actions=False,
            )
        except Exception:
            logger.exception(
                "yahoo history request failed symbol=%s start=%s end=%s",
                symbol.yahoo_symbol,
                start_date,
                end_date,
            )
            return []
        if history is None or history.empty:
            return []

        bars: list[DailyBar] = []
        for timestamp, row in history.iterrows():
            bar_date = _to_date(timestamp)
            if bar_date < start_date or bar_date > end_date:
                continue
            open_price = _safe_float(row.get("Open"))
            high_price = _safe_float(row.get("High"))
            low_price = _safe_float(row.get("Low"))
            close_price = _safe_float(row.get("Close"))
            if (
                not math.isfinite(open_price)
                or not math.isfinite(high_price)
                or not math.isfinite(low_price)
                or not math.isfinite(close_price)
                or min(open_price, high_price, low_price, close_price) <= 0
            ):
                continue
            bars.append(
                DailyBar(
                    symbol=symbol.canonical,
                    date=bar_date,
                    open=open_price,
                    high=high_price,
                    low=low_price,
                    close=close_price,
                )
            )
        return bars

    def fetch_previous_close(
        self,
        symbol: StockSymbol,
        before_date: date,
    ) -> float | None:
        start_date = before_date - timedelta(days=15)
        bars = self.fetch_daily_bars(symbol, start_date, before_date - timedelta(days=1))
        if not bars:
            return None
        return bars[-1].close

    def fetch_provisional_daily_bar(self, symbol: StockSymbol) -> DailyBar | None:
        cutoff = self.last_completed_trading_day(symbol)
        if cutoff is None:
            return None

        try:
            latest_bar = self._fetch_latest_chart_daily_bar(symbol)
        except Exception:
            logger.exception("yahoo provisional daily bar request failed symbol=%s", symbol.yahoo_symbol)
            return None

        if latest_bar is None or latest_bar.date <= cutoff:
            return None
        return latest_bar

    def fetch_display_name(self, symbol: StockSymbol) -> tuple[str | None, bool]:
        if symbol.yahoo_symbol in self._display_names:
            return self._display_names[symbol.yahoo_symbol], False

        ticker = self._ticker(symbol.yahoo_symbol)
        display_name = None
        try:
            metadata = ticker.history_metadata or {}
            display_name = _normalize_display_name(metadata.get("shortName"))
            if not display_name:
                display_name = _normalize_display_name(metadata.get("longName"))
        except Exception:
            logger.exception("yahoo history metadata request failed symbol=%s", symbol.yahoo_symbol)

        if not display_name:
            try:
                info = ticker.get_info() or {}
                display_name = _normalize_display_name(info.get("shortName"))
                if not display_name:
                    display_name = _normalize_display_name(info.get("longName"))
            except Exception:
                logger.exception("yahoo info request failed symbol=%s", symbol.yahoo_symbol)

        self._display_names[symbol.yahoo_symbol] = display_name
        return display_name, True

    def fetch_trading_days(
        self,
        symbol: StockSymbol,
        start_date: date,
        end_date: date,
    ) -> list[date]:
        if end_date < start_date:
            return []
        calendar = self._calendar(symbol)
        sessions = calendar.sessions_in_range(
            pd.Timestamp(start_date),
            pd.Timestamp(end_date),
        )
        return [session.date() for session in sessions]

    def last_completed_trading_day(self, symbol: StockSymbol) -> date | None:
        calendar = self._calendar(symbol)
        now_market = datetime.now(calendar.tz)
        today = now_market.date()
        sessions = list(
            calendar.sessions_in_range(
                pd.Timestamp(today - timedelta(days=10)),
                pd.Timestamp(today),
            )
        )
        if not sessions:
            return None

        last_session = sessions[-1]
        if last_session.date() != today:
            return last_session.date()

        session_close = calendar.session_close(last_session).tz_convert(calendar.tz)
        if now_market >= session_close.to_pydatetime():
            return today
        if len(sessions) >= 2:
            return sessions[-2].date()
        return None

    def _calendar(self, symbol: StockSymbol):
        calendar_name = symbol.calendar_name or CALENDAR_BY_MARKET.get(symbol.market)
        if calendar_name is None:
            raise ValueError(f"unsupported market for calendar lookup: {symbol.market}")
        try:
            return self._calendars[calendar_name]
        except KeyError as exc:
            raise ValueError(
                f"unsupported calendar lookup for symbol {symbol.canonical}: {calendar_name}"
            ) from exc

    def _ticker(self, yahoo_symbol: str) -> yf.Ticker:
        ticker = self._tickers.get(yahoo_symbol)
        if ticker is None:
            ticker = yf.Ticker(yahoo_symbol)
            self._tickers[yahoo_symbol] = ticker
        return ticker

    def _fetch_latest_chart_daily_bar(self, symbol: StockSymbol) -> DailyBar | None:
        now_utc = datetime.now(timezone.utc)
        params = urlencode(
            {
                "period1": int((now_utc - timedelta(days=10)).timestamp()),
                "period2": int((now_utc + timedelta(days=1)).timestamp()),
                "interval": "1d",
                "includePrePost": "false",
                "events": "div,splits",
            }
        )
        url = (
            "https://query2.finance.yahoo.com/v8/finance/chart/"
            f"{quote(symbol.yahoo_symbol, safe='')}?{params}"
        )
        request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=20) as response:
            payload = json.load(response)

        calendar = self._calendar(symbol)
        fallback_timezone = getattr(calendar.tz, "key", str(calendar.tz))
        return _latest_chart_daily_bar_from_payload(symbol, payload, fallback_timezone)


def _to_date(value) -> date:
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        value = value.date()
    return value


def _safe_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid float value from yahoo response: {value!r}") from exc


def _normalize_display_name(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _latest_chart_daily_bar_from_payload(
    symbol: StockSymbol,
    payload: dict,
    fallback_timezone: str,
) -> DailyBar | None:
    chart = payload.get("chart") or {}
    results = chart.get("result") or []
    if not results:
        return None

    result = results[0]
    meta = result.get("meta") or {}
    timezone_name = meta.get("exchangeTimezoneName") or fallback_timezone or "UTC"
    try:
        market_tz = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        market_tz = ZoneInfo("UTC")

    timestamps = result.get("timestamp") or []
    indicators = result.get("indicators") or {}
    quote_values = (indicators.get("quote") or [{}])[0]

    latest_by_date: dict[date, tuple[int, DailyBar]] = {}
    for index, raw_timestamp in enumerate(timestamps):
        timestamp = int(raw_timestamp)
        open_price = _safe_float_or_none(_value_at(quote_values.get("open"), index))
        high_price = _safe_float_or_none(_value_at(quote_values.get("high"), index))
        low_price = _safe_float_or_none(_value_at(quote_values.get("low"), index))
        close_price = _safe_float_or_none(_value_at(quote_values.get("close"), index))
        if None in {open_price, high_price, low_price, close_price}:
            continue
        assert open_price is not None
        assert high_price is not None
        assert low_price is not None
        assert close_price is not None
        if min(open_price, high_price, low_price, close_price) <= 0:
            continue

        bar_date = datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone(market_tz).date()
        bar = DailyBar(
            symbol=symbol.canonical,
            date=bar_date,
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
        )
        previous = latest_by_date.get(bar_date)
        if previous is None or timestamp > previous[0]:
            latest_by_date[bar_date] = (timestamp, bar)

    if not latest_by_date:
        return None

    _, latest_bar = max(
        latest_by_date.values(),
        key=lambda item: (item[1].date, item[0]),
    )
    return latest_bar


def _safe_float_or_none(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _value_at(values, index: int):
    if values is None or index >= len(values):
        return None
    return values[index]
