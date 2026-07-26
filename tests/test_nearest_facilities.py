"""Tests for multi-kind nearest facilities (fire / police / shelter / hospital)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from geoagent.tools.hierarchical_router import route_message
from geoagent.tools.nearest_facilities import (
    detect_facility_kind,
    find_nearest_facilities,
)
from geoagent.tools.nearest_hospital import find_nearest_hospitals


class NearestFacilitiesTests(unittest.TestCase):
    def test_detect_kinds(self) -> None:
        self.assertEqual(detect_facility_kind("nearest fire station?"), "fire_station")
        self.assertEqual(detect_facility_kind("any police nearby"), "police")
        self.assertEqual(detect_facility_kind("where is the evacuation shelter"), "shelter")
        self.assertEqual(detect_facility_kind("nearest hospital"), "hospital")
        self.assertEqual(detect_facility_kind("附近有没有消防站"), "fire_station")
        self.assertEqual(detect_facility_kind("避难所在哪里"), "shelter")

    def test_routes_fire_to_facilities_tool(self) -> None:
        route = route_message("where is the nearest fire station?")
        self.assertEqual(route.l2, "facilities")
        self.assertEqual(route.tools(), ["find_nearest_facilities"])
        self.assertEqual(route.slots.get("facility_kind"), "fire_station")

    def test_routes_police_and_shelter(self) -> None:
        for q, kind in (
            ("nearest police station", "police"),
            ("nearest emergency shelter", "shelter"),
        ):
            with self.subTest(q=q):
                route = route_message(q)
                self.assertEqual(route.l2, "facilities")
                self.assertIn("find_nearest_facilities", route.tools())
                self.assertEqual(route.slots.get("facility_kind"), kind)

    def test_hospital_still_uses_hospital_tool(self) -> None:
        route = route_message("any hospital nearby?")
        self.assertEqual(route.l2, "hospitals")
        self.assertEqual(route.tools(), ["find_nearest_hospitals"])

    def test_generic_facilities_not_hospitals(self) -> None:
        for q in (
            "any available facilities do we have?",
            "Yes, nearby facilities",
            "nearby facilities",
        ):
            with self.subTest(q=q):
                route = route_message(q)
                self.assertEqual(route.l2, "facilities", q)
                self.assertEqual(route.tools(), ["find_nearest_facilities"])
                self.assertEqual(route.slots.get("facility_kind"), "all")

    def test_nearby_alone_does_not_force_hospitals(self) -> None:
        route = route_message("anything nearby?")
        self.assertNotEqual(route.l2, "hospitals")

    @patch(
        "geoagent.tools.nearest_facilities.fetch_facilities_overpass",
        return_value=[
            {
                "kind": "fire_station",
                "name": "Station 69",
                "distance_km": 3.1,
                "distance_mi": 1.9,
                "coordinates_wgs84": [-118.25, 34.05],
                "latitude": 34.05,
                "longitude": -118.25,
                "phone": None,
                "website": None,
                "operator": None,
                "emergency": None,
                "beds": None,
                "address": None,
                "osm_type": "node",
                "osm_id": 9,
                "osm_tags": {"amenity": "fire_station"},
            }
        ],
    )
    def test_find_nearest_fire_station(self, _mock_fetch) -> None:
        payload = find_nearest_facilities(
            "fire_station",
            centroid_wgs84=[-118.598699, 34.082889],
            aoi_id="upload_demo",
            limit=3,
        )
        self.assertEqual(payload["facility_kind"], "fire_station")
        self.assertEqual(payload["facility_count"], 1)
        self.assertEqual(payload["nearest"]["name"], "Station 69")

    @patch(
        "geoagent.tools.nearest_facilities.fetch_facilities_overpass",
        return_value=[
            {
                "kind": "hospital",
                "name": "Saint John's Hospital",
                "distance_km": 12.3,
                "distance_mi": 7.6,
                "coordinates_wgs84": [-118.25, 34.05],
                "latitude": 34.05,
                "longitude": -118.25,
                "osm_type": "node",
                "osm_id": 1,
            }
        ],
    )
    def test_hospital_wrapper_still_works(self, _mock_fetch) -> None:
        payload = find_nearest_hospitals(
            centroid_wgs84=[-118.598699, 34.082889],
            aoi_id="maxar_031311102212",
            limit=3,
        )
        self.assertEqual(payload["hospital_count"], 1)
        self.assertEqual(payload["nearest"]["name"], "Saint John's Hospital")

    def test_format_all_kinds_lists_multiple(self) -> None:
        from geoagent.runtime.tools import _format_facilities_markdown, _requested_facility_count

        self.assertEqual(_requested_facility_count("give me three options for each"), 3)
        payload = {
            "facility_kind": "all",
            "by_kind": {
                "hospital": {
                    "status": "ok",
                    "hospitals": [
                        {"name": "H1", "distance_mi": 1.0, "coordinates_wgs84": [-118.2, 34.0]},
                        {"name": "H2", "distance_mi": 2.0, "coordinates_wgs84": [-118.3, 34.1]},
                        {"name": "H3", "distance_mi": 3.0, "coordinates_wgs84": [-118.4, 34.2]},
                    ],
                },
                "fire_station": {
                    "status": "ok",
                    "facilities": [
                        {"name": "F1", "distance_mi": 0.2, "coordinates_wgs84": [-118.2, 34.0]},
                    ],
                },
                "police": {"status": "ok", "facilities": []},
                "shelter": {"status": "ok", "facilities": []},
            },
            "disclaimer": "OSM disclaimer",
        }
        md = _format_facilities_markdown("demo", payload, limit=3)
        self.assertIn("1. [H1]", md)
        self.assertIn("2. [H2]", md)
        self.assertIn("3. [H3]", md)
        self.assertIn("1.0 mi", md)
        self.assertIn("0.2 mi", md)
        self.assertIn("Only 1 fire stations found", md)
        self.assertNotIn("[No other", md)

    def test_refresh_unavailable_kinds_only_retries_failures(self) -> None:
        from geoagent.tools.nearest_facilities import refresh_unavailable_facility_kinds

        payload = {
            "facility_kind": "all",
            "status": "ok",
            "by_kind": {
                "hospital": {"status": "ok", "hospitals": [{"name": "H1", "distance_mi": 1.0}]},
                "fire_station": {"status": "ok", "facilities": [{"name": "F1", "distance_mi": 0.2}]},
                "police": {"status": "ok", "facilities": [{"name": "P1", "distance_mi": 1.5}]},
                "shelter": {
                    "status": "unavailable",
                    "lookup_error": "The read operation timed out",
                    "facilities": [],
                },
            },
        }
        shelter_ok = {
            "status": "ok",
            "facility_kind": "shelter",
            "facilities": [{"name": "S1", "distance_mi": 0.3}],
            "nearest": {"name": "S1", "distance_mi": 0.3},
        }

        def fake_find(kind, **kwargs):
            self.assertEqual(kind, "shelter")
            return shelter_ok

        with patch(
            "geoagent.tools.nearest_facilities.find_nearest_facilities",
            side_effect=fake_find,
        ):
            updated = refresh_unavailable_facility_kinds(
                payload,
                centroid_wgs84=[-118.55, 34.06],
                aoi_id="demo",
                limit_per_kind=3,
            )
        self.assertEqual(updated["by_kind"]["shelter"]["status"], "ok")
        self.assertEqual(updated["by_kind"]["hospital"]["status"], "ok")
        self.assertEqual(updated["by_kind"]["shelter"]["nearest"]["name"], "S1")

    def test_combined_payload_detects_unavailable_kind(self) -> None:
        from geoagent.tools.nearest_facilities import combined_payload_has_unavailable_kind

        self.assertTrue(
            combined_payload_has_unavailable_kind(
                {
                    "by_kind": {
                        "hospital": {"status": "ok"},
                        "fire_station": {"status": "ok"},
                        "police": {"status": "ok"},
                        "shelter": {"status": "unavailable"},
                    }
                }
            )
        )
        self.assertFalse(
            combined_payload_has_unavailable_kind(
                {
                    "by_kind": {
                        "hospital": {"status": "ok"},
                        "fire_station": {"status": "ok"},
                        "police": {"status": "ok"},
                        "shelter": {"status": "ok"},
                    }
                }
            )
        )

    def test_merge_per_kind_cache_avoids_network(self) -> None:
        import json
        import tempfile
        from pathlib import Path

        from geoagent.tools.nearest_facilities import merge_per_kind_caches_into_combined

        payload = {
            "facility_kind": "all",
            "status": "ok",
            "by_kind": {
                "hospital": {"status": "ok", "hospitals": [{"name": "H1"}]},
                "fire_station": {"status": "ok", "facilities": [{"name": "F1"}]},
                "police": {"status": "ok", "facilities": [{"name": "P1"}]},
                "shelter": {
                    "status": "unavailable",
                    "lookup_error": "timed out",
                    "facilities": [],
                },
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            aligned = Path(tmp)
            aoi_out = aligned / "aoi_out"
            aoi_out.mkdir()
            (aoi_out / "nearest_shelters.json").write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "facility_kind": "shelter",
                        "facilities": [{"name": "S1", "distance_mi": 0.3}],
                        "nearest": {"name": "S1", "distance_mi": 0.3},
                    }
                )
                + "\n"
            )
            merged, missing = merge_per_kind_caches_into_combined(payload, aligned)
        self.assertEqual(missing, [])
        self.assertEqual(merged["by_kind"]["shelter"]["status"], "ok")
        self.assertEqual(merged["by_kind"]["shelter"]["nearest"]["name"], "S1")


    def test_ensure_facility_answer_adds_links_and_distances(self) -> None:
        from geoagent.runtime.tools import ensure_facility_answer

        payload = {
            "facility_kind": "all",
            "by_kind": {
                "hospital": {
                    "status": "ok",
                    "hospitals": [
                        {
                            "name": "UCLA Medical Center - Santa Monica",
                            "distance_mi": 2.18,
                            "coordinates_wgs84": [-118.48, 34.02],
                        }
                    ],
                },
                "fire_station": {"status": "ok", "facilities": []},
                "police": {"status": "ok", "facilities": []},
                "shelter": {
                    "status": "ok",
                    "facilities": [
                        {
                            "name": "Sunset & Carey",
                            "distance_mi": 0.27,
                            "coordinates_wgs84": [-118.55, 34.05],
                        }
                    ],
                },
            },
        }
        draft = (
            "Here are the nearest facilities for this AOI.\n\n"
            "### Hospitals\n"
            "- UCLA Medical Center - Santa Monica\n\n"
            "### Shelters\n"
            "- Sunset & Carey\n"
        )
        polished = ensure_facility_answer(draft, payload, limit=3)
        self.assertIn("[UCLA Medical Center - Santa Monica](#map-", polished)
        self.assertIn("2.18 mi", polished)
        self.assertIn("[Sunset & Carey](#map-", polished)
        self.assertIn("0.27 mi", polished)
        self.assertIn("Here are the nearest facilities", polished)

    def test_unnamed_facilities_ranked_after_named(self) -> None:
        from geoagent.runtime.tools import _facility_list_items, _format_facilities_markdown
        from geoagent.tools.nearest_facilities import (
            facilities_payload_for_display,
            find_nearest_facilities,
            is_unnamed_facility_name,
            rank_facilities_for_display,
        )

        self.assertTrue(is_unnamed_facility_name("Unnamed hospital"))
        self.assertTrue(is_unnamed_facility_name("Unnamed fire station"))
        self.assertFalse(is_unnamed_facility_name("UCLA Medical Center"))

        with patch(
            "geoagent.tools.nearest_facilities.fetch_facilities_overpass",
            return_value=[
                {
                    "kind": "hospital",
                    "name": "Unnamed hospital",
                    "distance_km": 1.0,
                    "distance_mi": 0.6,
                    "coordinates_wgs84": [-118.2, 34.0],
                },
                {
                    "kind": "hospital",
                    "name": "UCLA Medical Center",
                    "distance_km": 2.0,
                    "distance_mi": 1.2,
                    "coordinates_wgs84": [-118.3, 34.1],
                    "phone": "+1 424",
                },
            ],
        ):
            payload = find_nearest_facilities(
                "hospital",
                centroid_wgs84=[-118.5, 34.0],
                aoi_id="demo",
                limit=3,
            )
        # Cache keeps geographic inventory; nearest prefers the named row.
        self.assertEqual(payload["facility_count"], 2)
        self.assertEqual(payload["hospitals"][0]["name"], "Unnamed hospital")
        self.assertEqual(payload["nearest"]["name"], "UCLA Medical Center")

        ranked = rank_facilities_for_display(payload["hospitals"])
        self.assertEqual(
            [row["name"] for row in ranked],
            ["UCLA Medical Center", "Unnamed hospital"],
        )
        self.assertEqual(
            [row["name"] for row in _facility_list_items(payload, "hospital")],
            ["UCLA Medical Center", "Unnamed hospital"],
        )

        display = facilities_payload_for_display(payload)
        assert display is not None
        self.assertEqual(display["facility_count"], 2)
        self.assertEqual(display["nearest"]["name"], "UCLA Medical Center")
        self.assertEqual(display["hospitals"][0]["name"], "UCLA Medical Center")
        md = _format_facilities_markdown(
            "demo",
            {
                "facility_kind": "all",
                "by_kind": {
                    "hospital": payload,
                    "fire_station": {"status": "ok", "facilities": []},
                    "police": {"status": "ok", "facilities": []},
                    "shelter": {"status": "ok", "facilities": []},
                },
            },
            limit=3,
        )
        # Named first in the answer; Unnamed can still appear later in the list.
        self.assertLess(md.index("UCLA Medical Center"), md.index("Unnamed hospital"))

    def test_map_facilities_exclude_unnamed(self) -> None:
        import json
        import tempfile
        from pathlib import Path

        from geoagent.tools.nearest_facilities import load_facilities_for_map

        with tempfile.TemporaryDirectory() as tmp:
            aoi = Path(tmp)
            out = aoi / "aoi_out"
            out.mkdir()
            (out / "nearest_facilities_all.json").write_text(
                json.dumps(
                    {
                        "facility_kind": "all",
                        "by_kind": {
                            "hospital": {
                                "status": "ok",
                                "hospitals": [
                                    {
                                        "name": "Unnamed hospital",
                                        "distance_mi": 0.5,
                                        "coordinates_wgs84": [-118.2, 34.0],
                                    },
                                    {
                                        "name": "UCLA Medical Center",
                                        "distance_mi": 1.2,
                                        "coordinates_wgs84": [-118.3, 34.1],
                                    },
                                ],
                            },
                            "fire_station": {
                                "status": "ok",
                                "facilities": [
                                    {
                                        "name": "Unnamed fire station",
                                        "distance_mi": 0.2,
                                        "coordinates_wgs84": [-118.25, 34.05],
                                    }
                                ],
                            },
                            "police": {"status": "ok", "facilities": []},
                            "shelter": {"status": "ok", "facilities": []},
                        },
                    }
                )
            )
            markers = load_facilities_for_map(aoi)
            names = [row["name"] for row in markers]
            self.assertEqual(names, ["UCLA Medical Center"])
            self.assertTrue(all(not str(n).lower().startswith("unnamed") for n in names))


if __name__ == "__main__":
    unittest.main()
