from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class DailyBar:
    symbol: str
    date: date
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class MonthSlice:
    key: str
    start_date: date
    end_date: date
    is_current: bool


@dataclass(frozen=True)
class WindowSpec:
    start_date: date
    end_date: date
    months: list[MonthSlice]

