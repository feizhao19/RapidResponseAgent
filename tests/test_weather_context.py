"""Tests for EOC-style weather context (mocked network)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from geoagent.tools.weather_context import (
    build_weather_context,
    classify_weather_topic,
    render_weather_markdown,
)

MOCK_FORECAST = {
    "current": {
        "time": "2026-07-05T12:00",
        "temperature_2m": 24.5,
        "relative_humidity_2m": 12,
        "wind_speed_10m": 28.0,
        "wind_direction_10m": 270,
        "wind_gusts_10m": 40.0,
        "weather_code": 0,
        "precipitation": 0.0,
    },
    "hourly": {
        "time": [f"2026-07-05T{hour:02d}:00" for hour in range(13, 19)],
        "temperature_2m": [25.0, 26.0, 27.0, 28.0, 27.0, 26.0],
        "relative_humidity_2m": [15, 14, 13, 12, 12, 13],
        "wind_speed_10m": [28.0, 30.0, 32.0, 30.0, 28.0, 26.0],
        "wind_direction_10m": [265, 260, 255, 250, 245, 240],
        "wind_gusts_10m": [40.0, 42.0, 45.0, 42.0, 38.0, 35.0],
        "precipitation_probability": [5, 10, 15, 20, 25, 30],
        "precipitation": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "weather_code": [0, 0, 1, 1, 2, 2],
    },
}

MOCK_NWS = {
    "office": "LOX",
    "forecast_zone": "CAZ368",
    "fire_weather_zone": "CAZ368",
    "forecast_periods": [
        {
            "name": "This Afternoon",
            "wind_speed": "15 mph",
            "wind_direction": "W",
            "short_forecast": "Sunny",
            "detailed_forecast": "Sunny, windy.",
            "temperature_f": 75,
        }
    ],
    "alerts": [
        {
            "event": "Red Flag Warning",
            "headline": "Red Flag Warning for Los Angeles County",
            "severity": "Severe",
            "urgency": "Expected",
            "ends": "2026-07-06T00:00:00-07:00",
            "description": "Critical fire weather conditions.",
        }
    ],
    "red_flag_active": True,
}

MOCK_AQ = {
    "current": {"us_aqi": 165, "pm2_5": 55.0, "pm10": 80.0},
    "hourly": {"time": ["2026-07-05T13:00"], "us_aqi": [170], "pm2_5": [58.0]},
}


class WeatherTopicTests(unittest.TestCase):
    def test_wind_maps_to_fire_weather(self) -> None:
        self.assertEqual(classify_weather_topic("wind forecast for Topanga"), "fire_weather")

    def test_aqi_maps_to_air_quality(self) -> None:
        self.assertEqual(classify_weather_topic("smoke and air quality in Topanga"), "air_quality")


class WeatherContextTests(unittest.TestCase):
    @patch("geoagent.tools.weather_context.fetch_air_quality", return_value=MOCK_AQ)
    @patch("geoagent.tools.weather_context.fetch_nws_context", return_value=MOCK_NWS)
    @patch("geoagent.tools.weather_context.fetch_weather_forecast", return_value=MOCK_FORECAST)
    @patch(
        "geoagent.tools.weather_context.resolve_location",
        return_value={
            "display_name": "Topanga, CA",
            "city": "Topanga",
            "aoi_id": "maxar_031311102212",
            "lat": 34.08,
            "lon": -118.59,
            "source": "assessment_index",
        },
    )
    def test_eoc_payload_and_render(self, _loc, _forecast, _nws, _aq) -> None:
        payload = build_weather_context(
            question="What is the wind forecast for Topanga?",
            city="Topanga",
            topic="fire_weather",
        )
        self.assertEqual(payload["topic"], "fire_weather")
        self.assertTrue(payload["nws"]["red_flag_active"])
        self.assertEqual(payload["operational_impact"]["fire_spread_concern"], "CRITICAL")
        self.assertIn("NWS", " ".join(payload["sources"]))

        markdown = render_weather_markdown(payload)
        self.assertIn("Situational Weather Advisory", markdown)
        self.assertIn("Operational impact", markdown)
        self.assertIn("Red Flag", markdown)
        self.assertIn("Air quality", markdown)
        self.assertIn("building damage assessment", markdown.casefold())

    def test_resolve_from_index_requires_filter(self) -> None:
        from geoagent.tools.weather_context import resolve_location_from_index

        self.assertIsNone(resolve_location_from_index())
        self.assertIsNone(resolve_location_from_index(city=""))

    @patch(
        "geoagent.tools.weather_context.load_assessment_index",
        return_value={
            "records": [
                {
                    "aoi_id": "maxar_topanga",
                    "location": {
                        "display_name": "Wildwood, Topanga",
                        "city": "Topanga",
                        "centroid_wgs84": [-118.59, 34.08],
                    },
                },
                {
                    "aoi_id": "maxar_altadena",
                    "location": {
                        "display_name": "Altadena, Los Angeles County",
                        "city": "Altadena",
                        "centroid_wgs84": [-118.13, 34.19],
                    },
                },
            ]
        },
    )
    def test_resolve_from_index_by_aoi_id(self, _index) -> None:
        from geoagent.tools.weather_context import resolve_location_from_index

        loc = resolve_location_from_index(aoi_id="maxar_altadena")
        self.assertIsNotNone(loc)
        assert loc is not None
        self.assertEqual(loc["city"], "Altadena")
        self.assertEqual(loc["aoi_id"], "maxar_altadena")


if __name__ == "__main__":
    unittest.main()
