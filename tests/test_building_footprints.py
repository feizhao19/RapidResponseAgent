"""Unit tests for footprint source helpers and Overture release dating."""

from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import patch

from geoagent.tools.building_footprints import (
    DEFAULT_FOOTPRINT_SOURCE,
    DEFAULT_OVERTURE_RELEASE,
    disaster_date_from_meta,
    footprint_source_label,
    is_official_origin,
    latest_overture_release_on_or_before,
    normalize_footprint_source,
    parse_overture_release_date,
    resolve_overture_release,
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
        self.assertIn(DEFAULT_OVERTURE_RELEASE, footprint_source_label("overture"))
        self.assertIn("LARIAC6", footprint_source_label("lariac"))

    def test_parse_overture_release_date(self) -> None:
        self.assertEqual(parse_overture_release_date("2024-12-18.0"), date(2024, 12, 18))
        self.assertEqual(parse_overture_release_date("2025-03-19.1"), date(2025, 3, 19))
        self.assertIsNone(parse_overture_release_date("not-a-release"))

    def test_latest_release_on_or_before_disaster(self) -> None:
        # LA wildfires onset ~2025-01-07 → prefer Dec 2024 release.
        self.assertEqual(
            latest_overture_release_on_or_before(date(2025, 1, 7)),
            "2024-12-18.0",
        )
        self.assertEqual(
            latest_overture_release_on_or_before(date(2025, 1, 22)),
            "2025-01-22.0",
        )

    def test_resolve_prefers_disaster_date_then_explicit(self) -> None:
        auto = resolve_overture_release(disaster_date="2025-01-07")
        self.assertEqual(auto.reason, "disaster_date")
        self.assertEqual(auto.requested, "2024-12-18.0")
        self.assertEqual(auto.used, "2024-12-18.0")
        self.assertEqual(auto.disaster_date, "2025-01-07")

        forced = resolve_overture_release(
            disaster_date="2025-01-07",
            explicit_release="2026-07-22.0",
        )
        self.assertEqual(forced.reason, "explicit")
        self.assertEqual(forced.used, "2026-07-22.0")

        default = resolve_overture_release()
        self.assertEqual(default.reason, "default")
        self.assertEqual(default.used, DEFAULT_OVERTURE_RELEASE)

    def test_disaster_date_from_meta(self) -> None:
        meta = {
            "pre_match": {
                "disaster_date": "2025-01-28",
                "extras": {"disaster_date": "2025-01-07"},
            }
        }
        self.assertEqual(disaster_date_from_meta(meta), date(2025, 1, 28))
        self.assertEqual(
            disaster_date_from_meta({"pre_match": {"extras": {"disaster_date": "2025-01-07"}}}),
            date(2025, 1, 7),
        )
        self.assertIsNone(disaster_date_from_meta({}))

    def test_prefetch_uses_meta_bounds_cache_hit(self) -> None:
        import json
        import os
        import tempfile
        from pathlib import Path

        from geoagent.tools.building_footprints import (
            overture_cache_path,
            prefetch_official_footprints,
            resolve_overture_release,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shared = root / "shared_overture"
            aligned = root / "aoi"
            aligned.mkdir()
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
                        },
                        "pre_match": {"disaster_date": "2025-01-07"},
                    }
                )
            )
            planned = resolve_overture_release(disaster_date="2025-01-07")
            shared.mkdir()
            cache_path = overture_cache_path(shared, bounds, planned.used)
            cache_path.write_text('{"type":"FeatureCollection","features":[]}\n')
            with patch.dict(os.environ, {"GEOAGENT_OVERTURE_CACHE": str(shared)}):
                result = prefetch_official_footprints(aligned, source="overture")
            self.assertTrue(result["cache_hit"])
            self.assertEqual(Path(result["footprints_cache"]), cache_path)
            self.assertEqual(result["overture_release"]["requested"], "2024-12-18.0")

    def test_prefetch_survives_aoi_delete_via_shared_cache(self) -> None:
        """AOI-local cache is promoted; deleting the AOI still hits shared cache."""
        import json
        import os
        import shutil
        import tempfile
        from pathlib import Path

        from geoagent.tools.building_footprints import (
            overture_cache_path,
            prefetch_official_footprints,
            resolve_overture_release,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shared = root / "shared_overture"
            aligned = root / "aoi"
            aligned.mkdir()
            bounds = [-118.7, 34.02, -118.68, 34.03]
            meta = {
                "grid": {
                    "bounds_wgs84": bounds,
                    "crs": "EPSG:3857",
                    "width": 10,
                    "height": 10,
                    "transform": [1, 0, 0, 0, -1, 10],
                },
                "pre_match": {"disaster_date": "2025-01-07"},
            }
            (aligned / "meta.json").write_text(json.dumps(meta))
            local = aligned / "buildings_out"
            local.mkdir()
            planned = resolve_overture_release(disaster_date="2025-01-07")
            local_cache = overture_cache_path(local, bounds, planned.used)
            local_cache.write_text('{"type":"FeatureCollection","features":[]}\n')

            with patch.dict(os.environ, {"GEOAGENT_OVERTURE_CACHE": str(shared)}):
                first = prefetch_official_footprints(aligned, source="overture")
                self.assertTrue(first["cache_hit"])
                promoted = Path(first["footprints_cache"])
                self.assertTrue(promoted.is_file())
                self.assertEqual(promoted.parent.resolve(), shared.resolve())

                # Simulate deleting the AOI and recreating a fresh aligned dir.
                shutil.rmtree(aligned)
                aligned.mkdir()
                (aligned / "meta.json").write_text(json.dumps(meta))
                second = prefetch_official_footprints(aligned, source="overture")
                self.assertTrue(second["cache_hit"])
                self.assertEqual(Path(second["footprints_cache"]), promoted)

    def test_fetch_fallback_records_unavailable_reason(self) -> None:
        import geopandas as gpd

        from geoagent.tools.building_footprints import fetch_overture_buildings_with_fallback

        planned = resolve_overture_release(disaster_date="2025-01-07")
        empty = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

        def fake_fetch(bounds, *, release=None, cache_path=None):
            if release == "2024-12-18.0":
                raise RuntimeError("HTTP 404")
            return empty

        with patch(
            "geoagent.tools.building_footprints.fetch_overture_buildings_wgs84",
            side_effect=fake_fetch,
        ):
            _gdf, used = fetch_overture_buildings_with_fallback(
                [-118.55, 34.05, -118.53, 34.07],
                resolution=planned,
            )
        self.assertEqual(used.requested, "2024-12-18.0")
        self.assertNotEqual(used.used, "2024-12-18.0")
        self.assertEqual(used.reason, "fallback_unavailable")
        self.assertIn("2024-12-18.0", used.tried)


if __name__ == "__main__":
    unittest.main()
