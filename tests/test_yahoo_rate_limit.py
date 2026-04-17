from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock

from yfinance.exceptions import YFRateLimitError

from relchart.app import RelChartService, RequestContext
from relchart.config import AppConfig
from relchart.models import MonthSlice, WindowSpec
from relchart.providers.base import ProviderRateLimitError
from relchart.providers.yahoo import YahooProvider
from relchart.symbols import parse_symbol


class HistoricalRateLimitedProvider:
    def __init__(self) -> None:
        self.fetch_calls: list[tuple[str, date, date]] = []

    def last_completed_trading_day(self, symbol) -> date | None:
        return None

    def fetch_daily_bars(
        self,
        symbol,
        start_date: date,
        end_date: date,
    ):
        self.fetch_calls.append((symbol.canonical, start_date, end_date))
        raise ProviderRateLimitError("Yahoo Finance")


class ServiceRateLimitTests(unittest.TestCase):
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

    def test_skips_historical_incomplete_warning_when_yahoo_is_rate_limited(self) -> None:
        symbol = parse_symbol("YF.SI=F")
        window = WindowSpec(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 2, 28),
            months=[
                MonthSlice(
                    key="202601",
                    start_date=date(2026, 1, 1),
                    end_date=date(2026, 1, 31),
                    is_current=False,
                )
            ],
        )
        self.service.provider = HistoricalRateLimitedProvider()
        warnings: list[str] = []

        self.service._sync_symbol(symbol, window, warnings, RequestContext())

        self.assertEqual(
            warnings,
            ["YF.SI=F: skipped historical backfill 202601 because Yahoo Finance rate limited"],
        )
        self.assertEqual(
            self.service.provider.fetch_calls,
            [("YF.SI=F", date(2026, 1, 1), date(2026, 1, 31))],
        )
        self.assertFalse(self.service.storage.month_exists(symbol, "202601"))


class YahooProviderRateLimitTests(unittest.TestCase):
    def test_short_circuits_follow_up_history_calls_during_cooldown(self) -> None:
        provider = YahooProvider()
        symbol = parse_symbol("YF.SI=F")
        ticker = Mock()
        ticker.history.side_effect = YFRateLimitError()
        provider._tickers[symbol.yahoo_symbol] = ticker

        with self.assertRaises(ProviderRateLimitError) as first_error:
            provider.fetch_daily_bars(symbol, date(2026, 1, 1), date(2026, 1, 31))

        with self.assertRaises(ProviderRateLimitError):
            provider.fetch_daily_bars(symbol, date(2026, 2, 1), date(2026, 2, 28))

        self.assertIsNotNone(first_error.exception.retry_at)
        self.assertEqual(ticker.history.call_count, 1)


if __name__ == "__main__":
    unittest.main()
