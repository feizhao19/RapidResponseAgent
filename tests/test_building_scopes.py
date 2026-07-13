"""Tests for official vs fused building scope stats."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import geopandas as gpd

from geoagent.tools.aoi_stats import enrich_stats_with_building_scopes

ROOT = Path(__file__).resolve().parents[1]
PILOT_GEOJSON = ROOT / "data/aligned/maxar_031311102212/buildings_out/buildings_with_damage.geojson"
PILOT_STATS = ROOT / "data/aligned/maxar_031311102212/aoi_out/aoi_stats.json"


@unittest.skipUnless(PILOT_GEOJSON.is_file(), "pilot buildings geojson not present")
class BuildingScopeStatsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.buildings = gpd.read_file(PILOT_GEOJSON)
        cls.stats = enrich_stats_with_building_scopes(
            json.loads(PILOT_STATS.read_text()),
            cls.buildings,
        )

    def test_default_scope_is_official(self) -> None:
        self.assertEqual(self.stats["building_scope_default"], "official")

    def test_official_excludes_detected_structures(self) -> None:
        official = self.stats["scopes"]["official"]
        self.assertEqual(official["buildings"]["total"], 593)
        self.assertEqual(official["buildings"]["detected_orphan_damage"], 0)

    def test_fused_includes_detected_structures(self) -> None:
        fused = self.stats["scopes"]["fused"]
        self.assertEqual(fused["buildings"]["total"], 691)
        self.assertEqual(fused["buildings"]["detected_orphan_damage"], 98)

    def test_top_level_mirrors_official(self) -> None:
        self.assertEqual(
            self.stats["damage_summary"]["damaged_count"],
            self.stats["scopes"]["official"]["damage_summary"]["damaged_count"],
        )
        self.assertEqual(self.stats["buildings"]["total"], 593)


if __name__ == "__main__":
    unittest.main()
