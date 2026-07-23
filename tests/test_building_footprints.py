"""Unit tests for footprint source helpers."""

from __future__ import annotations

import unittest

from geoagent.tools.building_footprints import (
    DEFAULT_FOOTPRINT_SOURCE,
    footprint_source_label,
    is_official_origin,
    normalize_footprint_source,
)


class BuildingFootprintSourceTests(unittest.TestCase):
    def test_default_footprint_source_is_overture(self) -> None:
        self.assertEqual(DEFAULT_FOOTPRINT_SOURCE, "overture")
        self.assertEqual(normalize_footprint_source(None), "overture")
        self.assertEqual(normalize_footprint_source("overtrue"), "overture")

    def test_official_origin_includes_overture_and_lariac(self) -> None:
        self.assertTrue(is_official_origin("overture"))
        self.assertTrue(is_official_origin("lariac"))
        self.assertFalse(is_official_origin("detected"))

    def test_footprint_source_label(self) -> None:
        self.assertIn("Overture", footprint_source_label("overture"))
        self.assertIn("LARIAC6", footprint_source_label("lariac"))

    def test_prefetch_uses_meta_bounds_cache_hit(self) -> None:
        import json
        import tempfile
        from pathlib import Path

        from geoagent.tools.building_footprints import prefetch_official_footprints

        with tempfile.TemporaryDirectory() as tmp:
            aligned = Path(tmp)
            bounds = [-118.7, 34.02, -118.68, 34.03]
            (aligned / "meta.json").write_text(
                json.dumps(
                    {
                        "grid": {
                            "bounds_wgs84": bounds,
                            "crs": "EPSG:3857",
                            "width": 10,
                            "height": 10,
                            "transform": [1, 0, 0, 0, -1, 10],
                        }
                    }
                )
            )
            cache_dir = aligned / "buildings_out"
            cache_dir.mkdir()
            from geoagent.tools.building_footprints import overture_cache_path

            cache_path = overture_cache_path(cache_dir, bounds)
            cache_path.write_text(
                '{"type":"FeatureCollection","features":[]}\n'
            )
            result = prefetch_official_footprints(aligned, source="overture")
            self.assertTrue(result["cache_hit"])
            self.assertEqual(Path(result["footprints_cache"]), cache_path)


if __name__ == "__main__":
    unittest.main()
