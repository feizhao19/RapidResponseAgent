"""Tests for Environmental Situation Layer weather grid."""

from __future__ import annotations

import unittest

from geoagent.tools.situation_weather import (
    build_situation_outlook,
    build_situation_weather,
    format_situation_outlook_markdown,
    humidity_fill_color,
    humidity_risk_band,
    sample_grid_points,
    temperature_band,
    temperature_fill_color,
    wants_situation_outlook,
)


def _mock_hourly(*, hours: int = 25, base_rh: float = 12.0, base_temp: float = 30.0) -> dict:
    times = [f"2026-07-25T{h:02d}:00" for h in range(hours)]
    return {
        "hourly": {
            "time": times,
            "temperature_2m": [base_temp + (i % 5) for i in range(hours)],
            "relative_humidity_2m": [base_rh + (i % 3) for i in range(hours)],
            "wind_speed_10m": [20.0 + i * 0.1 for i in range(hours)],
            "wind_direction_10m": [270.0 + i for i in range(hours)],
            "wind_gusts_10m": [35.0 + i * 0.1 for i in range(hours)],
        }
    }


class HumidityBandTests(unittest.TestCase):
    def test_bands(self) -> None:
        self.assertEqual(humidity_risk_band(10), "danger")
        self.assertEqual(humidity_risk_band(20), "elevated")
        self.assertEqual(humidity_risk_band(30), "moderate")
        self.assertEqual(humidity_risk_band(55), "moist")
        self.assertIn("rgba", humidity_fill_color(10))


class TemperatureBandTests(unittest.TestCase):
    def test_bands(self) -> None:
        self.assertEqual(temperature_band(10), "cool")
        self.assertEqual(temperature_band(20), "mild")
        self.assertEqual(temperature_band(28), "warm")
        self.assertEqual(temperature_band(35), "hot")
        self.assertEqual(temperature_band(40), "extreme")
        self.assertIn("rgba", temperature_fill_color(40))


class GridSampleTests(unittest.TestCase):
    def test_4x4_cells(self) -> None:
        cells = sample_grid_points([-118.6, 34.0, -118.5, 34.1], rows=4, cols=4)
        self.assertEqual(len(cells), 16)
        self.assertEqual(cells[0]["id"], "r0c0")
        self.assertEqual(len(cells[0]["polygon"]), 5)


class SituationWeatherBuildTests(unittest.TestCase):
    def test_build_grid_with_mocked_fetch(self) -> None:
        def fake_fetch(points):
            out = []
            for idx, _ in enumerate(points):
                rh = 11.0 if idx < 16 else 18.0
                temp = 39.0 if idx < 16 else 22.0
                out.append(_mock_hourly(base_rh=rh, base_temp=temp))
            return out

        payload = build_situation_weather(
            "demo_aoi",
            bounds_wgs84=[-118.6, 34.0, -118.5, 34.1],
            centroid_wgs84=[-118.55, 34.05],
            fetch_fn=fake_fetch,
            hours=25,
        )
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(len(payload["cells"]), 16)
        self.assertGreaterEqual(len(payload["hours"]), 24)
        self.assertEqual(len(payload["centroid_series"]), len(payload["hours"]))
        sample = payload["cells"][0]["series"][0]
        self.assertIn("wind_direction_deg", sample)
        self.assertIn("humidity_band", sample)
        self.assertIn("temperature_band", sample)
        self.assertEqual(sample["humidity_band"], "danger")
        self.assertEqual(sample["temperature_band"], "extreme")
        self.assertEqual(payload["centroid_series"][0]["humidity_band"], "elevated")
        self.assertEqual(payload["centroid_series"][0]["temperature_band"], "mild")


class SituationOutlookTests(unittest.TestCase):
    def test_wants_outlook(self) -> None:
        self.assertTrue(wants_situation_outlook("How will conditions change over the next 6 hours?"))
        self.assertTrue(wants_situation_outlook("situation outlook for this AOI"))
        self.assertFalse(wants_situation_outlook("nearest hospital"))

    def test_outlook_deltas(self) -> None:
        def fake_fetch(points):
            hours = 25
            times = [f"2026-07-25T{h:02d}:00" for h in range(hours)]
            return [
                {
                    "hourly": {
                        "time": times,
                        "temperature_2m": [30.0 + i for i in range(hours)],
                        "relative_humidity_2m": [25.0 - i for i in range(hours)],
                        "wind_speed_10m": [18.0 + i for i in range(hours)],
                        "wind_direction_10m": [270.0] * hours,
                        "wind_gusts_10m": [30.0 + i for i in range(hours)],
                    }
                }
                for _ in points
            ]

        payload = build_situation_weather(
            "demo_aoi",
            bounds_wgs84=[-118.6, 34.0, -118.5, 34.1],
            centroid_wgs84=[-118.55, 34.05],
            fetch_fn=fake_fetch,
            hours=25,
        )
        outlook = build_situation_outlook(payload, question="next 6 hours")
        self.assertTrue(outlook["available"])
        self.assertEqual(outlook["horizon_hours"], 6)
        self.assertEqual(outlook["wind_speed_kmh"]["delta"], 6.0)
        self.assertEqual(outlook["temperature_c"]["delta"], 6.0)
        self.assertEqual(outlook["relative_humidity_pct"]["delta"], -6.0)
        md = format_situation_outlook_markdown(outlook)
        self.assertIn("Situation outlook", md)
        self.assertIn("Wind:", md)
        self.assertIn("Humidity:", md)


if __name__ == "__main__":
    unittest.main()
