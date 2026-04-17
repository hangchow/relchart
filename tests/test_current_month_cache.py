from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from relchart.app import RelChartService, RequestContext
from relchart.config import AppConfig
from relchart.models import DailyBar, MonthSlice, WindowSpec
from relchart.providers.base import ProviderRateLimitError
from relchart.symbols import parse_symbol


def _bar(symbol: str, year: int, month: int, day: int, close: float) -> DailyBar:
    return DailyBar(
        symbol=symbol,
        date=date(year, month, day),
        open=close - 1.0,
        high=close + 1.0,
        low=close - 2.0,
        close=close,
    )


class FakeProvider:
    def __init__(self, cutoff: date, bars: list[DailyBar]) -> None:
        self.cutoff = cutoff
        self.bars = bars
        self.fetch_calls: list[tuple[str, date, date]] = []

    def last_completed_trading_day(self, symbol) -> date:
        return self.cutoff

    def fetch_daily_bars(
        self,
        symbol,
        start_date: date,
        end_date: date,
    ) -> list[DailyBar]:
        self.fetch_calls.append((symbol.canonical, start_date, end_date))
        return [bar for bar in self.bars if start_date <= bar.date <= end_date]


class RateLimitedProvider:
    def __init__(self, cutoff: date) -> None:
        self.cutoff = cutoff
        self.fetch_calls: list[tuple[str, date, date]] = []

    def last_completed_trading_day(self, symbol) -> date:
        return self.cutoff

    def fetch_daily_bars(
        self,
        symbol,
        start_date: date,
        end_date: date,
    ) -> list[DailyBar]:
        self.fetch_calls.append((symbol.canonical, start_date, end_date))
        raise ProviderRateLimitError("Yahoo Finance")


class CurrentMonthCacheRefreshTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.service = RelChartService(
            AppConfig(
                data_dir=Path(self.temp_dir.name),
                web_host="127.0.0.1",
                web_port=19090,
            )
        )
        self.symbol = parse_symbol("YF.GC=F")
        self.window = WindowSpec(
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 16),
            months=[
                MonthSlice(
                    key="202603",
                    start_date=date(2026, 3, 1),
                    end_date=date(2026, 3, 31),
                    is_current=True,
                )
            ],
        )
        self.all_march_bars = [
            _bar(self.symbol.canonical, 2026, 3, 2, 102.0),
            _bar(self.symbol.canonical, 2026, 3, 3, 103.0),
            _bar(self.symbol.canonical, 2026, 3, 4, 104.0),
            _bar(self.symbol.canonical, 2026, 3, 5, 105.0),
            _bar(self.symbol.canonical, 2026, 3, 6, 106.0),
            _bar(self.symbol.canonical, 2026, 3, 9, 109.0),
            _bar(self.symbol.canonical, 2026, 3, 10, 110.0),
            _bar(self.symbol.canonical, 2026, 3, 11, 111.0),
            _bar(self.symbol.canonical, 2026, 3, 12, 112.0),
            _bar(self.symbol.canonical, 2026, 3, 13, 113.0),
        ]

    def test_refreshes_stale_current_month_cache(self) -> None:
        self.service.storage.write_month_file(
            self.symbol,
            "202603",
            self.all_march_bars[:5],
        )
        self.service.provider = FakeProvider(date(2026, 3, 13), self.all_march_bars)

        self.service._sync_symbol(self.symbol, self.window, [], RequestContext())

        cached_bars = self.service.storage.read_month_file(self.symbol, "202603")
        self.assertEqual(cached_bars[-1].date, date(2026, 3, 13))
        self.assertEqual(
            self.service.provider.fetch_calls,
            [("YF.GC=F", date(2026, 3, 1), date(2026, 3, 13))],
        )

    def test_skips_remote_refresh_when_current_month_cache_is_current(self) -> None:
        self.service.storage.write_month_file(
            self.symbol,
            "202603",
            self.all_march_bars,
        )
        self.service.provider = FakeProvider(date(2026, 3, 13), self.all_march_bars)

        self.service._sync_symbol(self.symbol, self.window, [], RequestContext())

        cached_bars = self.service.storage.read_month_file(self.symbol, "202603")
        self.assertEqual(cached_bars[-1].date, date(2026, 3, 13))
        self.assertEqual(self.service.provider.fetch_calls, [])

    def test_keeps_stale_cache_and_adds_warning_when_refresh_is_rate_limited(self) -> None:
        self.service.storage.write_month_file(
            self.symbol,
            "202603",
            self.all_march_bars[:5],
        )
        self.service.provider = RateLimitedProvider(date(2026, 3, 13))
        warnings: list[str] = []

        self.service._sync_symbol(self.symbol, self.window, warnings, RequestContext())

        cached_bars = self.service.storage.read_month_file(self.symbol, "202603")
        self.assertEqual(cached_bars[-1].date, date(2026, 3, 6))
        self.assertEqual(
            warnings,
            [
                "YF.GC=F: current month refresh paused because Yahoo Finance rate limited "
                "(last cached day 2026-03-06)"
            ],
        )
        self.assertEqual(
            self.service.provider.fetch_calls,
            [("YF.GC=F", date(2026, 3, 1), date(2026, 3, 13))],
        )


if __name__ == "__main__":
    unittest.main()
