"""Tests for assessed case label formatting."""

from __future__ import annotations

import unittest

from geoagent.tools.case_label import format_assessed_case_label


class CaseLabelTests(unittest.TestCase):
    def test_wildwood_topanga_with_post_image_date(self) -> None:
        record = {
            "aoi_id": "maxar_031311102212",
            "event": "la_wildfires_jan2025",
            "post_image": "NOAA ERI 20250128a",
            "location": {
                "display_name": "Wildwood, Topanga, Los Angeles County, California, 90290, United States",
                "city": "Topanga",
                "county": "Los Angeles County",
                "state": "California",
            },
        }
        self.assertEqual(
            format_assessed_case_label(record),
            "Wildwood · Topanga · California · 2025-01-07",
        )

    def test_pacific_palisades_uses_neighbourhood(self) -> None:
        record = {
            "aoi_id": "upload_4178b5b46024",
            "event": "la_wildfires_jan2025",
            "post_image": "NOAA ERI 20250128a",
            "location": {
                "display_name": "Pacific Palisades, Los Angeles, Los Angeles County, California, 90272, United States",
                "city": "Los Angeles",
                "state": "California",
                "neighbourhood": "Pacific Palisades",
            },
        }
        self.assertEqual(
            format_assessed_case_label(record),
            "Pacific Palisades · Los Angeles · California · 2025-01-07",
        )

    def test_altadena_collapses_duplicate_community(self) -> None:
        record = {
            "aoi_id": "upload_34fd88225242",
            "event": "la_wildfires_jan2025",
            "post_image": "NOAA ERI 20250128a",
            "location": {
                "display_name": "Altadena, Los Angeles County, California, 91001, United States",
                "city": "Altadena",
                "state": "California",
            },
        }
        self.assertEqual(
            format_assessed_case_label(record),
            "Altadena · California · 2025-01-07",
        )

    def test_event_date_beats_post_image_and_generated_at(self) -> None:
        record = {
            "aoi_id": "upload_130ea1ac498a",
            "event": "la_wildfires_jan2025",
            "post_image": "NOAA ERI 20250128a",
            "generated_at": "2026-07-05T21:26:14.709751+00:00",
            "location": {"city": "Topanga", "state": "California"},
        }
        self.assertEqual(
            format_assessed_case_label(record).split(" · ")[-1],
            "2025-01-07",
        )

    def test_upload_without_event_uses_post_image_date(self) -> None:
        record = {
            "aoi_id": "upload_custom",
            "post_image": "NOAA ERI 20250128a",
            "generated_at": "2026-07-05T21:26:14.709751+00:00",
            "location": {"city": "Topanga", "state": "California"},
        }
        self.assertEqual(
            format_assessed_case_label(record).split(" · ")[-1],
            "2025-01-28",
        )


if __name__ == "__main__":
    unittest.main()
