from __future__ import annotations

import colorsys
import hashlib

from .models import DailyBar

def color_for_symbol(symbol: str) -> str:
    digest = hashlib.sha256(symbol.encode("utf-8")).digest()
    hue = int.from_bytes(digest[:2], "big") % 360
    saturation = 0.62 + (digest[2] / 255.0) * 0.16
    lightness = 0.42 + (digest[3] / 255.0) * 0.10
    red, green, blue = colorsys.hls_to_rgb(hue / 360.0, lightness, saturation)
    return "#{:02X}{:02X}{:02X}".format(
        round(red * 255),
        round(green * 255),
        round(blue * 255),
    )


def to_percent_bars(bars: list[DailyBar], base_close: float) -> list[dict[str, float | str]]:
    return [
        {
            "time": bar.date.isoformat(),
            "open": _to_percent(bar.open, base_close),
            "high": _to_percent(bar.high, base_close),
            "low": _to_percent(bar.low, base_close),
            "close": _to_percent(bar.close, base_close),
        }
        for bar in bars
    ]


def _to_percent(value: float, base_close: float) -> float:
    return round((value / base_close - 1.0) * 100.0, 4)
