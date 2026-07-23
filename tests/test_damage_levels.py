"""Tests for 4-class damage level helpers."""

from __future__ import annotations

import unittest

from geoagent.tools.damage_levels import format_levels_markdown, levels_from_stats
from geoagent.tools.historical_query import parse_natural_language


class DamageLevelsTests(unittest.TestCase):
    def test_folds_inferred_into_no_damage(self) -> None:
        stats = {
            "by_damage_label": {
                "no_damage": {"count": 80, "pct": 80.0},
                "no_damage_inferred": {"count": 10, "pct": 10.0},
                "minor": {"count": 5, "pct": 5.0},
                "major": {"count": 3, "pct": 3.0},
                "destroyed": {"count": 2, "pct": 2.0},
            }
        }
        levels = levels_from_stats(stats)
        self.assertEqual(levels["no_damage"]["count"], 90)
        self.assertEqual(levels["minor"]["count"], 5)
        self.assertEqual(levels["destroyed"]["count"], 2)

    def test_prefers_by_effective_level(self) -> None:
        stats = {
            "by_effective_level": {
                "no_damage": {"count": 100, "pct": 80.0},
                "minor": {"count": 10, "pct": 8.0},
                "major": {"count": 10, "pct": 8.0},
                "destroyed": {"count": 5, "pct": 4.0},
            },
            "by_damage_label": {"minor": {"count": 999, "pct": 99.0}},
        }
        levels = levels_from_stats(stats)
        self.assertEqual(levels["minor"]["count"], 10)

    def test_markdown_has_four_classes_only(self) -> None:
        stats = {
            "buildings": {"total": 125},
            "by_effective_level": {
                "no_damage": {"count": 100, "pct": 80.0},
                "minor": {"count": 10, "pct": 8.0},
                "major": {"count": 10, "pct": 8.0},
                "destroyed": {"count": 5, "pct": 4.0},
            },
        }
        md = format_levels_markdown("upload_test", stats)
        self.assertIn("No damage", md)
        self.assertIn("Minor damage", md)
        self.assertIn("Major damage", md)
        self.assertIn("Destroyed", md)
        self.assertNotIn("**Damaged:**", md)
        self.assertNotIn("**Severe:**", md)


class HistoricalMetricRoutingTests(unittest.TestCase):
    def test_damaged_maps_to_breakdown(self) -> None:
        query = parse_natural_language("how many damaged buildings in Topanga")
        self.assertEqual(query.metric, "damage_breakdown")

    def test_destroyed_stays_specific(self) -> None:
        query = parse_natural_language("how many destroyed buildings in Topanga")
        self.assertEqual(query.metric, "destroyed_count")


if __name__ == "__main__":
    unittest.main()
