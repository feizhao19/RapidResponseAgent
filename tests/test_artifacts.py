"""Artifact validation for pipeline steps."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from geoagent.graph.artifacts import validate_buildings_geojson
from geoagent.tools.aoi_stats import _building_scope_stats

import geopandas as gpd


class ValidateBuildingsGeojsonTests(unittest.TestCase):
    def test_accepts_empty_feature_collection(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            geojson = Path(tmp) / "buildings_with_damage.geojson"
            geojson.write_text(
                json.dumps({"type": "FeatureCollection", "features": []}) + "\n"
            )
            self.assertEqual(validate_buildings_geojson(geojson), [])

    def test_rejects_missing_features_key(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            geojson = Path(tmp) / "buildings_with_damage.geojson"
            geojson.write_text(json.dumps({"type": "FeatureCollection"}) + "\n")
            errors = validate_buildings_geojson(geojson)
            self.assertTrue(any("missing 'features'" in err for err in errors))


class EmptyBuildingScopeStatsTests(unittest.TestCase):
    def test_empty_geojson_returns_zero_stats(self) -> None:
        empty = gpd.GeoDataFrame(geometry=[], crs="EPSG:32611")
        stats = _building_scope_stats(empty)
        self.assertEqual(stats["buildings"]["total"], 0)
        self.assertEqual(stats["damage_summary"]["damaged_count"], 0)
        self.assertTrue(stats["limitations"])


if __name__ == "__main__":
    unittest.main()
