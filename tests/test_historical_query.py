"""Faithfulness tests: historical QA numbers must match aoi_stats.json."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import geopandas as gpd

from geoagent.tools.aoi_stats import enrich_stats_with_building_scopes
from geoagent.tools.historical_index import build_assessment_index
from geoagent.tools.historical_query import (
    StructuredQuery,
    execute_query,
    parse_natural_language,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PILOT_STATS = DATA / "aligned/maxar_031311102212/aoi_out/aoi_stats.json"


@unittest.skipUnless(PILOT_STATS.is_file(), "pilot aoi_stats.json not present")
class HistoricalQueryFaithfulnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        raw_stats = json.loads(PILOT_STATS.read_text())
        geojson = DATA / "aligned/maxar_031311102212/buildings_out/buildings_with_damage.geojson"
        if geojson.is_file():
            cls.stats = enrich_stats_with_building_scopes(raw_stats, gpd.read_file(geojson))
        else:
            cls.stats = raw_stats
        cls.index = build_assessment_index(data_root=DATA)

    def test_parse_topanga_damaged_count(self) -> None:
        query = parse_natural_language("Topanga 2025 wildfire damaged count")
        self.assertEqual(query.city, "Topanga")
        self.assertEqual(query.metric, "damage_breakdown")
        self.assertIsNone(query.rank_by)

    def test_parse_topanga_buildings_total(self) -> None:
        query = parse_natural_language("I mean how many buildings it has in Topanga")
        self.assertEqual(query.city, "Topanga")
        self.assertEqual(query.metric, "buildings_total")

    def test_parse_statistics_request(self) -> None:
        query = parse_natural_language("what is the statistic information of this")
        self.assertEqual(query.metric, "damage_breakdown")

    def test_parse_mesa_damaged_count(self) -> None:
        query = parse_natural_language("what happened in Mesa, how many buildings are damaged")
        self.assertEqual(query.city, "Mesa")
        self.assertEqual(query.metric, "damage_breakdown")
        result = execute_query(query, index=self.index)
        self.assertEqual(result.matched_aoi_ids, ["upload_7b21cf164310"])
        destroyed = [f for f in result.facts if f.label == "destroyed"]
        self.assertGreaterEqual(len(destroyed), 1)

    def test_damage_breakdown_matches_effective_levels(self) -> None:
        query = StructuredQuery(city="Topanga", metric="damage_breakdown")
        result = execute_query(query, index=self.index)
        self.assertIn("maxar_031311102212", result.matched_aoi_ids)
        levels = self.stats.get("by_effective_level") or {}
        for level in ("no_damage", "minor", "major", "destroyed"):
            facts = [
                f
                for f in result.facts
                if f.label == level and f.aoi_id == "maxar_031311102212"
            ]
            self.assertEqual(len(facts), 1, msg=level)
            self.assertEqual(facts[0].value, levels[level]["count"], msg=level)

    def test_all_summary_numbers_match_stats(self) -> None:
        query = StructuredQuery(aoi_id="maxar_031311102212")
        result = execute_query(query, index=self.index)
        buildings = self.stats["buildings"]
        levels = self.stats.get("by_effective_level") or {}
        expected = {
            "buildings_total": buildings["total"],
            "buildings_official": buildings["official"],
            "buildings_detected": buildings["detected_orphan_damage"],
            "no_damage": levels["no_damage"]["count"],
            "minor": levels["minor"]["count"],
            "major": levels["major"]["count"],
            "destroyed": levels["destroyed"]["count"],
        }
        for label, value in expected.items():
            facts = [f for f in result.facts if f.label == label]
            self.assertEqual(len(facts), 1, msg=label)
            self.assertEqual(facts[0].value, value, msg=label)

    def test_citations_point_at_aoi_stats(self) -> None:
        query = StructuredQuery(city="Topanga", metric="damage_breakdown")
        result = execute_query(query, index=self.index)
        for fact in result.facts:
            self.assertIn("aoi_stats.json#", fact.citation)


if __name__ == "__main__":
    unittest.main()
