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
        self.assertIn("Only 1 fire stations found", md)
        self.assertNotIn("[No other", md)


if __name__ == "__main__":
    unittest.main()
