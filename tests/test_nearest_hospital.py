"""Tests for nearest hospital lookup."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from geoagent.agents.facilities_agent import _run_impl
from geoagent.agents.report_agent import render_hospitals_section
from geoagent.tools.nearest_hospital import find_nearest_hospitals, haversine_km, unavailable_hospitals_payload

MOCK_OVERPASS_ELEMENTS = [
    {
        "type": "node",
        "id": 1,
        "lat": 34.05,
        "lon": -118.25,
        "tags": {
            "amenity": "hospital",
            "name": "Saint John's Hospital",
            "phone": "+1-310-555-0100",
            "website": "https://example.org/saint-johns",
            "operator": "Providence Health",
        },
    },
    {
        "type": "node",
        "id": 2,
        "lat": 34.15,
        "lon": -118.80,
        "tags": {
            "amenity": "hospital",
            "name": "Distant Medical Center",
        },
    },
]


class NearestHospitalTests(unittest.TestCase):
    def test_haversine(self) -> None:
        distance = haversine_km(34.08, -118.59, 34.05, -118.25)
        self.assertGreater(distance, 20)
        self.assertLess(distance, 40)

    @patch(
        "geoagent.tools.nearest_hospital.fetch_hospitals_overpass",
        return_value=[
            {
                "name": "Saint John's Hospital",
                "distance_km": 12.3,
                "distance_mi": 7.6,
                "coordinates_wgs84": [-118.25, 34.05],
                "latitude": 34.05,
                "longitude": -118.25,
                "phone": "+1-310-555-0100",
                "website": "https://example.org/saint-johns",
                "operator": "Providence Health",
                "osm_type": "node",
                "osm_id": 1,
            }
        ],
    )
    def test_find_nearest_hospitals(self, _mock_fetch) -> None:
        payload = find_nearest_hospitals(
            centroid_wgs84=[-118.598699, 34.082889],
            aoi_id="maxar_031311102212",
            display_name="Topanga",
            limit=3,
        )
        self.assertEqual(payload["hospital_count"], 1)
        self.assertEqual(payload["nearest"]["name"], "Saint John's Hospital")

    def test_report_section_renders_contacts(self) -> None:
        section = render_hospitals_section(
            {
                "aoi_centroid_wgs84": [-118.598699, 34.082889],
                "search_radius_km": 40,
                "nearest": {
                    "name": "Saint John's Hospital",
                    "distance_km": 12.3,
                    "distance_mi": 7.6,
                    "phone": "+1-310-555-0100",
                    "website": "https://example.org/saint-johns",
                    "operator": "Providence Health",
                },
                "hospitals": [
                    {
                        "name": "Saint John's Hospital",
                        "distance_km": 12.3,
                        "distance_mi": 7.6,
                        "coordinates_wgs84": [-118.25, 34.05],
                        "phone": "+1-310-555-0100",
                        "website": "https://example.org/saint-johns",
                        "operator": "Providence Health",
                    }
                ],
            }
        )
        markdown = "\n".join(section)
        self.assertIn("Nearest Hospitals", markdown)
        self.assertIn("Saint John's Hospital", markdown)
        self.assertIn("+1-310-555-0100", markdown)
        self.assertIn("Providence Health", markdown)

    def test_report_section_renders_unavailable(self) -> None:
        section = render_hospitals_section(
            unavailable_hospitals_payload(
                centroid_wgs84=[-118.598699, 34.082889],
                aoi_id="test_aoi",
                lookup_error="Overpass hospital lookup failed: timed out",
            )
        )
        markdown = "\n".join(section)
        self.assertIn("Hospital lookup unavailable", markdown)
        self.assertIn("| N/A | N/A | N/A | N/A | N/A | N/A | N/A |", markdown)

    @patch(
        "geoagent.agents.facilities_agent.find_nearest_hospitals",
        side_effect=RuntimeError("Overpass hospital lookup failed: timed out"),
    )
    def test_facilities_agent_continues_on_lookup_failure(self, _mock_find) -> None:
        import json
        import shutil
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            aligned_dir = Path(tmp) / "upload_test"
            aoi_out = aligned_dir / "aoi_out"
            aoi_out.mkdir(parents=True)
            location = {
                "aoi_id": "upload_test",
                "display_name": "Test AOI",
                "centroid_wgs84": [-118.598699, 34.082889],
            }
            (aoi_out / "location.json").write_text(json.dumps(location))
            result = _run_impl({"aligned_dir": str(aligned_dir)})
            output_path = Path(result["nearest_hospitals_json"])
            self.assertTrue(output_path.is_file())
            payload = json.loads(output_path.read_text())
            self.assertEqual(payload["status"], "unavailable")
            self.assertIn("facilities", result["completed_steps"])
            shutil.rmtree(aligned_dir)


if __name__ == "__main__":
    unittest.main()
