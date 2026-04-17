from __future__ import annotations

from datetime import date, datetime, timedelta
import importlib
import math
import exchange_calendars as xcals
import pandas as pd

from relchart.models import DailyBar
from relchart.symbols import StockSymbol

from .yahoo import YahooProvider

MARKET_FETCHERS = {
    "HK": "stock_hk_daily",
    "US": "stock_us_daily",
}

CALENDAR_BY_MARKET = {
    "US": "XNYS",
    "HK": "XHKG",
}


class SinaProvider:
    def __init__(self) -> None:
        self._fallback_provider = YahooProvider()
        self._calendars = {
            calendar_name: xcals.get_calendar(calendar_name)
            for calendar_name in sorted(set(CALENDAR_BY_MARKET.values()) | {"24/5", "24/7"})
        }

    def fetch_daily_bars(
        self,
        symbol: StockSymbol,
        start_date: date,
        end_date: date,
    ) -> list[DailyBar]:
        if symbol.market == "YF":
            return self._fallback_provider.fetch_daily_bars(symbol, start_date, end_date)
        if end_date < start_date:
            return []

        history = self._fetch_sina_history(
            symbol,
            start_date=start_date,
            end_date_exclusive=end_date + timedelta(days=1),
        )
        if history.empty:
            return []

        bars: list[DailyBar] = []
        for row in history.itertuples(index=False):
            try:
                bar_date = _to_date(row.date)
                open_price = float(row.open)
                high_price = float(row.high)
                low_price = float(row.low)
                close_price = float(row.close)
            except (TypeError, ValueError):
                continue
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
        if symbol.market == "YF":
            return self._fallback_provider.fetch_previous_close(symbol, before_date)
        start_date = before_date - timedelta(days=15)
        bars = self.fetch_daily_bars(symbol, start_date, before_date - timedelta(days=1))
        if not bars:
            return None
        return bars[-1].close

    def fetch_provisional_daily_bar(self, symbol: StockSymbol) -> DailyBar | None:
        if symbol.market == "YF":
            return self._fallback_provider.fetch_provisional_daily_bar(symbol)
        return None

    def fetch_display_name(self, symbol: StockSymbol) -> tuple[str | None, bool]:
        if symbol.market == "YF":
            return self._fallback_provider.fetch_display_name(symbol)
        return None, False

    def fetch_trading_days(
        self,
        symbol: StockSymbol,
        start_date: date,
        end_date: date,
    ) -> list[date]:
        if symbol.market == "YF":
            return self._fallback_provider.fetch_trading_days(symbol, start_date, end_date)
        if end_date < start_date:
            return []
        calendar = self._calendar(symbol)
        sessions = calendar.sessions_in_range(pd.Timestamp(start_date), pd.Timestamp(end_date))
        return [session.date() for session in sessions]

    def last_completed_trading_day(self, symbol: StockSymbol) -> date | None:
        if symbol.market == "YF":
            return self._fallback_provider.last_completed_trading_day(symbol)
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

    def _fetch_sina_history(
        self,
        symbol: StockSymbol,
        *,
        start_date: date,
        end_date_exclusive: date,
    ) -> pd.DataFrame:
        akshare = importlib.import_module("akshare")
        fetcher_name = MARKET_FETCHERS.get(symbol.market)
        if fetcher_name is None:
            raise ValueError(f"unsupported market for Sina provider: {symbol.canonical}")
        fetcher = getattr(akshare, fetcher_name, None)
        if fetcher is None or not callable(fetcher):
            raise RuntimeError(f"akshare missing expected api={fetcher_name}")

        history = fetcher(symbol=_sina_symbol(symbol), adjust="")
        if history.empty:
            return history

        dates = pd.to_datetime(history["date"]).dt.date
        return history.loc[
            (dates >= start_date) & (dates < end_date_exclusive),
            ["date", "open", "high", "low", "close"],
        ].copy()


def _sina_symbol(symbol: StockSymbol) -> str:
    if symbol.market == "HK":
        return symbol.code
    if symbol.market == "US":
        return symbol.code.replace(".", "-")
    raise ValueError(f"unsupported market for Sina provider: {symbol.canonical}")


def _to_date(value) -> date:
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        value = value.date()
    return value
