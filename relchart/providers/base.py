from __future__ import annotations

from datetime import date
from typing import Protocol

from relchart.models import DailyBar
from relchart.symbols import StockSymbol


class DailyBarProvider(Protocol):
    def fetch_daily_bars(
        self,
        symbol: StockSymbol,
        start_date: date,
        end_date: date,
    ) -> list[DailyBar]: ...

    def fetch_previous_close(
        self,
        symbol: StockSymbol,
        before_date: date,
    ) -> float | None: ...

    def fetch_display_name(self, symbol: StockSymbol) -> tuple[str | None, bool]: ...

    def fetch_trading_days(
        self,
        symbol: StockSymbol,
        start_date: date,
        end_date: date,
    ) -> list[date]: ...

    def last_completed_trading_day(self, symbol: StockSymbol) -> date | None: ...
