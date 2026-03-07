from __future__ import annotations

import colorsys
import hashlib
from itertools import permutations

from .models import DailyBar

def color_for_symbol(symbol: str) -> str:
    return _color_from_hue(_preferred_hue(symbol))


def assign_distinct_colors(symbols: list[str]) -> dict[str, str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for symbol in symbols:
        if symbol in seen:
            continue
        seen.add(symbol)
        ordered.append(symbol)

    if not ordered:
        return {}
    if len(ordered) == 1:
        symbol = ordered[0]
        return {symbol: color_for_symbol(symbol)}

    preferred_hues = [_preferred_hue(symbol) for symbol in ordered]
    slot_step = 360.0 / len(ordered)
    base_slots = [index * slot_step for index in range(len(ordered))]
    best_assignment: tuple[float, ...] | None = None
    best_cost: float | None = None

    for offset in range(360):
        rotated_slots = tuple((slot + offset) % 360.0 for slot in base_slots)
        for assignment in permutations(rotated_slots):
            cost = sum(
                _circular_distance(preferred_hues[index], assigned_hue) ** 2
                for index, assigned_hue in enumerate(assignment)
            )
            if best_cost is None or cost < best_cost:
                best_cost = cost
                best_assignment = assignment

    assert best_assignment is not None
    return {
        symbol: _color_from_hue(hue)
        for symbol, hue in zip(ordered, best_assignment)
    }


def _preferred_hue(symbol: str) -> float:
    digest = hashlib.sha256(symbol.encode("utf-8")).digest()
    return float(int.from_bytes(digest[:2], "big") % 360)


def _color_from_hue(hue: float) -> str:
    saturation = 0.72
    lightness = 0.46
    red, green, blue = colorsys.hls_to_rgb(hue / 360.0, lightness, saturation)
    return "#{:02X}{:02X}{:02X}".format(
        round(red * 255),
        round(green * 255),
        round(blue * 255),
    )


def _circular_distance(left: float, right: float) -> float:
    distance = abs(left - right) % 360.0
    return min(distance, 360.0 - distance)


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


def to_percent_line_points(
    points: list[tuple[str, float]],
    base_value: float,
) -> list[dict[str, float | str]]:
    return [
        {
            "time": time,
            "value": _to_percent(value, base_value),
            "raw_value": round(value, 6),
        }
        for time, value in points
    ]


def _to_percent(value: float, base_close: float) -> float:
    return round((value / base_close - 1.0) * 100.0, 4)
