from __future__ import annotations

import logging
import os
from datetime import date, datetime
from pathlib import Path

from .models import DailyBar
from .symbols import StockSymbol

logger = logging.getLogger(__name__)


class FileStorage:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def month_file_path(self, symbol: StockSymbol, month_key: str) -> Path:
        symbol_dir = self.data_dir / symbol.storage_key
        return symbol_dir / f"{symbol.storage_key}_{month_key}.txt"

    def month_exists(self, symbol: StockSymbol, month_key: str) -> bool:
        return self.month_file_path(symbol, month_key).exists()

    def read_month_file(self, symbol: StockSymbol, month_key: str) -> list[DailyBar]:
        path = self.month_file_path(symbol, month_key)
        if not path.exists():
            return []

        bars: dict[date, DailyBar] = {}
        with path.open("r", encoding="utf-8") as handle:
            for lineno, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) != 5:
                    logger.warning("skip invalid line %s:%s: %s", path, lineno, line)
                    continue
                try:
                    bar_date = datetime.strptime(parts[0], "%Y%m%d").date()
                    bar = DailyBar(
                        symbol=symbol.canonical,
                        date=bar_date,
                        open=float(parts[1]),
                        high=float(parts[2]),
                        low=float(parts[3]),
                        close=float(parts[4]),
                    )
                except ValueError:
                    logger.warning("skip invalid line %s:%s: %s", path, lineno, line)
                    continue
                if min(bar.open, bar.high, bar.low, bar.close) <= 0:
                    logger.warning("skip non-positive prices %s:%s: %s", path, lineno, line)
                    continue
                bars[bar.date] = bar

        return sorted(bars.values(), key=lambda item: item.date)

    def read_window_bars(self, symbol: StockSymbol, month_keys: list[str]) -> list[DailyBar]:
        merged: dict[date, DailyBar] = {}
        for month_key in month_keys:
            for bar in self.read_month_file(symbol, month_key):
                merged[bar.date] = bar
        return sorted(merged.values(), key=lambda item: item.date)

    def write_month_file(self, symbol: StockSymbol, month_key: str, bars: list[DailyBar]) -> None:
        path = self.month_file_path(symbol, month_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        normalized = sorted(
            {bar.date: bar for bar in bars}.values(),
            key=lambda item: item.date,
        )
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            for bar in normalized:
                handle.write(
                    f"{bar.date.strftime('%Y%m%d')} "
                    f"{_format_price(bar.open)} "
                    f"{_format_price(bar.high)} "
                    f"{_format_price(bar.low)} "
                    f"{_format_price(bar.close)}\n"
                )
        os.replace(tmp_path, path)


def merge_bars(*groups: list[DailyBar]) -> list[DailyBar]:
    merged: dict[date, DailyBar] = {}
    for bars in groups:
        for bar in bars:
            merged[bar.date] = bar
    return sorted(merged.values(), key=lambda item: item.date)


def _format_price(value: float) -> str:
    text = f"{value:.10f}".rstrip("0").rstrip(".")
    return text or "0"
