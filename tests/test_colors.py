import unittest
from itertools import permutations
from unittest.mock import patch

from relchart.transform import assign_distinct_colors, _circular_distance, _preferred_hue


class ColorAssignmentTests(unittest.TestCase):
    def test_assignment_matches_exhaustive_optimum(self):
        symbols = ["US.AAPL", "HK.00700", "US.SLV", "US.TMF"]
        preferred = [_preferred_hue(symbol) for symbol in symbols]
        expected_cost = min(
            sum(_circular_distance(hue, slot) ** 2 for hue, slot in zip(preferred, slots))
            for offset in range(360)
            for slots in permutations([(index * 90 + offset) % 360 for index in range(4)])
        )
        with patch("relchart.transform._color_from_hue", side_effect=lambda hue: hue):
            assigned = assign_distinct_colors(symbols)
        actual_cost = sum(
            _circular_distance(hue, assigned[symbol]) ** 2
            for symbol, hue in zip(symbols, preferred)
        )
        self.assertEqual(actual_cost, expected_cost)

    def test_colors_are_deterministic_and_ignore_duplicate_symbols(self):
        symbols = [f"US.TEST{index}" for index in range(20)]
        colors = assign_distinct_colors(symbols)
        self.assertEqual(len(set(colors.values())), 20)
        self.assertEqual(colors, assign_distinct_colors(symbols + symbols))
