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

    def test_incomplete_markdown_link_detection(self) -> None:
        from geoagent.runtime.tools import _has_incomplete_markdown_link

        self.assertTrue(
            _has_incomplete_markdown_link(
                "Other nearby hospitals\n"
                "[West Los Angeles Veterans Affairs Medical Center](#"
            )
        )
        self.assertTrue(
            _has_incomplete_markdown_link(
                "[UCLA](#map-hospital?lon=-118.48&lat=34.02&name=UCLA"
            )
        )
        self.assertFalse(
            _has_incomplete_markdown_link(
                "- [UCLA](#map-facility?lon=-118.48&lat=34.02&name=UCLA&kind=hospital) — 4.85 mi"
            )
        )

    def test_other_than_hospitals_resolves_non_hospital_kinds(self) -> None:
        from geoagent.tools.nearest_facilities import (
            resolve_facility_kinds,
            wants_facilities_excluding_hospitals,
        )

        q = "Can we find any nearby facilities other than hospitals?"
        self.assertTrue(wants_facilities_excluding_hospitals(q))
        self.assertIsNone(detect_facility_kind(q))
        kinds = resolve_facility_kinds(q, slots={"facility_kind": "all"})
        self.assertEqual(kinds, ["fire_station", "police", "shelter"])
        self.assertNotIn("hospital", kinds)

        route = route_message(q)
        self.assertEqual(route.l2, "facilities")
        self.assertEqual(route.tools(), ["find_nearest_facilities"])

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
        self.assertIn("- [H1]", md)
        self.assertIn("- [H2]", md)
        self.assertIn("- [H3]", md)
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

        def fake_multi(kinds, lat, lon, **kwargs):
            self.assertEqual(list(kinds), ["shelter"])
            return {
                "shelter": [
                    {
                        "kind": "shelter",
                        "name": "S1",
                        "distance_km": 0.5,
                        "distance_mi": 0.3,
                        "coordinates_wgs84": [-118.55, 34.06],
                    }
                ]
            }

        with patch(
            "geoagent.tools.nearest_facilities.fetch_facilities_overpass_multi",
            side_effect=fake_multi,
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

    def test_overpass_query_uses_nwr_and_combined(self) -> None:
        from geoagent.tools.nearest_facilities import (
            build_combined_overpass_query,
            build_overpass_query,
        )

        q = build_overpass_query("hospital", 34.08, -118.60, radius_m=5000)
        self.assertIn('nwr["amenity"="hospital"](around:5000,', q)
        self.assertNotIn("node[", q)
        self.assertIn("out center tags;", q)

        combined = build_combined_overpass_query(
            ["hospital", "fire_station"],
            34.08,
            -118.60,
            radius_m=8000,
        )
        self.assertIn('nwr["amenity"="hospital"]', combined)
        self.assertIn('nwr["amenity"="fire_station"]', combined)
        self.assertIn("[timeout:30]", combined)

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

    def test_ensure_facility_answer_rebuilds_run_on_paragraph_as_bullets(self) -> None:
        from geoagent.runtime.tools import ensure_facility_answer

        payload = {
            "aoi_id": "demo",
            "facility_kind": "all",
            "by_kind": {
                "hospital": {
                    "status": "ok",
                    "hospitals": [
                        {
                            "name": "UCLA Medical Center - Santa Monica",
                            "distance_mi": 4.85,
                            "coordinates_wgs84": [-118.48, 34.02],
                            "phone": "+1 424 259 6000",
                        },
                        {
                            "name": "Providence Saint John's Health Center",
                            "distance_mi": 5.19,
                            "coordinates_wgs84": [-118.48, 34.03],
                        },
                    ],
                },
                "fire_station": {
                    "status": "ok",
                    "facilities": [
                        {
                            "name": "Los Angeles Fire Department Fire Station 23",
                            "distance_mi": 0.83,
                            "coordinates_wgs84": [-118.55, 34.05],
                        }
                    ],
                },
                "police": {"status": "ok", "facilities": []},
                "shelter": {
                    "status": "ok",
                    "facilities": [
                        {
                            "name": "Sunset & Castellammare",
                            "distance_mi": 0.88,
                            "coordinates_wgs84": [-118.55, 34.04],
                        }
                    ],
                },
            },
        }
        # Mimic the collapsed LLM output the user reported.
        draft = (
            "Nearby Facilities\n\n"
            "Hospitals\n"
            "UCLA Medical Center - Santa Monica — 4.85 mi +1 424 259 6000 "
            "Providence Saint John's Health Center — 5.19 mi\n\n"
            "Fire Stations\n"
            "Los Angeles Fire Department Fire Station 23 — 0.83 mi\n\n"
            "Shelters\n"
            "Sunset & Castellammare — 0.88 mi\n"
        )
        polished = ensure_facility_answer(draft, payload, limit=3)
        self.assertIn("- [UCLA Medical Center - Santa Monica](#map-", polished)
        self.assertIn("- [Providence Saint John's Health Center](#map-", polished)
        self.assertIn("- [Los Angeles Fire Department Fire Station 23](#map-", polished)
        self.assertIn("- [Sunset & Castellammare](#map-", polished)
        # Facilities must not remain jammed onto one non-bullet line.
        self.assertNotRegex(
            polished,
            r"UCLA Medical Center - Santa Monica.*Providence Saint John's Health Center",
        )

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
