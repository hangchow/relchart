from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from relchart.app import RelChartService, RequestContext
from relchart.config import AppConfig
from relchart.models import DailyBar, MonthSlice, WindowSpec
from relchart.providers.yahoo import _latest_chart_daily_bar_from_payload
from relchart.symbols import RatioSymbol, parse_request_item, parse_symbol


def _bar(symbol: str, year: int, month: int, day: int, close: float) -> DailyBar:
    return DailyBar(
        symbol=symbol,
        date=date(year, month, day),
        open=close - 1.0,
        high=close + 2.0,
        low=close - 2.0,
        close=close,
    )


class FakeSnapshotProvider:
    def __init__(
        self,
        *,
        previous_close_by_symbol: dict[str, float],
        provisional_by_symbol: dict[str, DailyBar | None],
    ) -> None:
        self.previous_close_by_symbol = previous_close_by_symbol
        self.provisional_by_symbol = provisional_by_symbol
        self.provisional_calls: list[str] = []

    def fetch_daily_bars(self, symbol, start_date: date, end_date: date) -> list[DailyBar]:
        return []

    def fetch_previous_close(self, symbol, before_date: date) -> float | None:
        return self.previous_close_by_symbol.get(symbol.canonical)

    def fetch_provisional_daily_bar(self, symbol) -> DailyBar | None:
        self.provisional_calls.append(symbol.canonical)
        return self.provisional_by_symbol.get(symbol.canonical)

    def fetch_display_name(self, symbol) -> tuple[str | None, bool]:
        return None, False

    def fetch_trading_days(self, symbol, start_date: date, end_date: date) -> list[date]:
        return []

    def last_completed_trading_day(self, symbol) -> date | None:
        return None


class ProvisionalSnapshotTests(unittest.TestCase):
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
        self.window = WindowSpec(
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 18),
            months=[
                MonthSlice(
                    key="202603",
                    start_date=date(2026, 3, 1),
                    end_date=date(2026, 3, 31),
                    is_current=True,
                )
            ],
        )

    def test_snapshot_includes_provisional_bar_without_writing_it(self) -> None:
        symbol = parse_symbol("YF.GC=F")
        self.service.storage.write_month_file(
            symbol,
            "202603",
            [
                _bar(symbol.canonical, 2026, 3, 2, 102.0),
                _bar(symbol.canonical, 2026, 3, 3, 103.0),
            ],
        )
        self.service.provider = FakeSnapshotProvider(
            previous_close_by_symbol={symbol.canonical: 100.0},
            provisional_by_symbol={
                symbol.canonical: _bar(symbol.canonical, 2026, 3, 4, 112.0),
            },
        )

        snapshot = self.service._build_snapshot(self.window, [symbol], [], RequestContext())

        series = snapshot["series"][0]
        self.assertEqual(series["provisional_bar"]["time"], "2026-03-04")
        self.assertEqual(series["provisional_bar"]["close"], 12.0)

        cached_bars = self.service.storage.read_month_file(symbol, "202603")
        self.assertEqual([bar.date for bar in cached_bars], [date(2026, 3, 2), date(2026, 3, 3)])
        self.assertEqual(self.service.provider.provisional_calls, [symbol.canonical])

    def test_ratio_snapshot_includes_matching_provisional_point(self) -> None:
        item = parse_request_item("YF.GC=F/YF.SI=F")
        self.assertIsInstance(item, RatioSymbol)
        ratio = item

        self.service.storage.write_month_file(
            ratio.numerator,
            "202603",
            [
                _bar(ratio.numerator.canonical, 2026, 3, 2, 102.0),
                _bar(ratio.numerator.canonical, 2026, 3, 3, 104.0),
            ],
        )
        self.service.storage.write_month_file(
            ratio.denominator,
            "202603",
            [
                _bar(ratio.denominator.canonical, 2026, 3, 2, 51.0),
                _bar(ratio.denominator.canonical, 2026, 3, 3, 52.0),
            ],
        )
        self.service.provider = FakeSnapshotProvider(
            previous_close_by_symbol={
                ratio.numerator.canonical: 100.0,
                ratio.denominator.canonical: 50.0,
            },
            provisional_by_symbol={
                ratio.numerator.canonical: _bar(ratio.numerator.canonical, 2026, 3, 4, 110.0),
                ratio.denominator.canonical: _bar(ratio.denominator.canonical, 2026, 3, 4, 50.0),
            },
        )

        snapshot = self.service._build_snapshot(self.window, [ratio], [], RequestContext())

        series = snapshot["series"][0]
        self.assertEqual(series["provisional_point"]["time"], "2026-03-04")
        self.assertEqual(series["provisional_point"]["raw_value"], 2.2)
        self.assertEqual(series["provisional_point"]["value"], 10.0)

    def test_ratio_snapshot_skips_mismatched_provisional_dates(self) -> None:
        item = parse_request_item("YF.GC=F/YF.SI=F")
        self.assertIsInstance(item, RatioSymbol)
        ratio = item

        self.service.storage.write_month_file(
            ratio.numerator,
            "202603",
            [_bar(ratio.numerator.canonical, 2026, 3, 3, 104.0)],
        )
        self.service.storage.write_month_file(
            ratio.denominator,
            "202603",
            [_bar(ratio.denominator.canonical, 2026, 3, 3, 52.0)],
        )
        self.service.provider = FakeSnapshotProvider(
            previous_close_by_symbol={
                ratio.numerator.canonical: 100.0,
                ratio.denominator.canonical: 50.0,
            },
            provisional_by_symbol={
                ratio.numerator.canonical: _bar(ratio.numerator.canonical, 2026, 3, 4, 110.0),
                ratio.denominator.canonical: _bar(ratio.denominator.canonical, 2026, 3, 5, 50.0),
            },
        )

        snapshot = self.service._build_snapshot(self.window, [ratio], [], RequestContext())

        series = snapshot["series"][0]
        self.assertIsNone(series["provisional_point"])


class YahooPayloadParsingTests(unittest.TestCase):
    def test_prefers_latest_non_empty_row_for_same_trade_date(self) -> None:
        symbol = parse_symbol("YF.GC=F")
        payload = {
            "chart": {
                "result": [
                    {
                        "meta": {
                            "exchangeTimezoneName": "America/New_York",
                        },
                        "timestamp": [
                            1773720000,
                            1773806400,
                            1773850923,
                        ],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [5017.6, 5010.6, 5010.6],
                                    "high": [5017.6, 5022.0, 5022.0],
                                    "low": [4994.2, 4837.1, 4837.1],
                                    "close": [5001.0, None, 4879.9],
                                }
                            ]
                        },
                    }
                ]
            }
        }

        bar = _latest_chart_daily_bar_from_payload(symbol, payload, "America/New_York")

        self.assertIsNotNone(bar)
        assert bar is not None
        self.assertEqual(bar.date, date(2026, 3, 18))
        self.assertEqual(bar.close, 4879.9)


if __name__ == "__main__":
    unittest.main()
