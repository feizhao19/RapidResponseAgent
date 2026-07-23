"""Tests for pre-disaster imagery resolution priority."""

from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from geoagent.tools.pre_imagery import (
    PreImageryCandidate,
    detect_maxar_open_event,
    resolve_pre_imagery,
)
from geoagent.tools.preprocess import wgs84_bounds

ROOT = Path(__file__).resolve().parents[1]
PILOT_POST = ROOT / "data" / "aligned" / "maxar_031311102212" / "post.tif"


class PreImageryResolveTests(unittest.TestCase):
    def test_priority_prefers_maxar_open_when_available(self) -> None:
        bbox = (-118.60, 34.08, -118.59, 34.09)
        open_hit = PreImageryCandidate(
            provider="maxar_open",
            path=Path("/tmp/maxar_open.tif"),
            date="2024-12-14",
            overlap_ratio=0.9,
            event_id="WildFires-LosAngeles-Jan-2025",
        )
        local_hit = PreImageryCandidate(
            provider="local_maxar",
            path=Path("/tmp/local_maxar.tif"),
            date="2024-12-21",
            overlap_ratio=0.95,
        )

        with (
            patch("geoagent.tools.pre_imagery.try_maxar_open", return_value=open_hit),
            patch("geoagent.tools.pre_imagery.try_local_maxar", return_value=local_hit),
            patch("geoagent.tools.pre_imagery.try_naip_planetary_computer") as naip,
        ):
            result = resolve_pre_imagery(bbox, download=False)
            self.assertEqual(result.provider, "maxar_open")
            naip.assert_not_called()

    def test_falls_back_to_local_then_naip(self) -> None:
        bbox = (-118.60, 34.08, -118.59, 34.09)
        naip_hit = PreImageryCandidate(
            provider="naip",
            path=Path("/tmp/naip.tif"),
            date="2022-05-12",
            overlap_ratio=0.8,
            gsd_m=0.6,
        )
        with (
            patch("geoagent.tools.pre_imagery.try_maxar_open", return_value=None),
            patch("geoagent.tools.pre_imagery.try_local_maxar", return_value=None),
            patch("geoagent.tools.pre_imagery.try_naip_planetary_computer", return_value=naip_hit),
            patch("geoagent.tools.pre_imagery.try_usgs_naip_imageserver") as usgs,
            patch("geoagent.tools.pre_imagery.try_usgs_earthexplorer") as ee,
            patch("geoagent.tools.pre_imagery.try_noaa_digital_coast") as noaa,
        ):
            result = resolve_pre_imagery(bbox, download=False)
            self.assertEqual(result.provider, "naip")
            self.assertEqual(result.gsd_m, 0.6)
            usgs.assert_not_called()
            ee.assert_not_called()
            noaa.assert_not_called()

    def test_falls_back_through_usgs_then_noaa(self) -> None:
        bbox = (-118.60, 34.08, -118.59, 34.09)
        usgs_hit = PreImageryCandidate(
            provider="usgs_naip_imageserver",
            path=Path("/tmp/usgs.tif"),
            overlap_ratio=1.0,
            gsd_m=1.0,
        )
        with (
            patch("geoagent.tools.pre_imagery.try_maxar_open", return_value=None),
            patch("geoagent.tools.pre_imagery.try_local_maxar", return_value=None),
            patch("geoagent.tools.pre_imagery.try_naip_planetary_computer", return_value=None),
            patch("geoagent.tools.pre_imagery.try_usgs_naip_imageserver", return_value=usgs_hit),
            patch("geoagent.tools.pre_imagery.try_usgs_earthexplorer") as ee,
            patch("geoagent.tools.pre_imagery.try_noaa_digital_coast") as noaa,
        ):
            result = resolve_pre_imagery(bbox, download=False)
            self.assertEqual(result.provider, "usgs_naip_imageserver")
            ee.assert_not_called()
            noaa.assert_not_called()

    def test_to_meta_includes_provider_fields(self) -> None:
        candidate = PreImageryCandidate(
            provider="local_maxar",
            path=Path("/tmp/a.tif"),
            date="2024-12-21",
            overlap_ratio=0.7,
            extras={"quad": "031311102212"},
        )
        meta = candidate.to_meta()
        self.assertEqual(meta["provider"], "local_maxar")
        self.assertEqual(meta["extras"]["quad"], "031311102212")


@unittest.skipUnless(PILOT_POST.is_file(), "pilot aligned post.tif not present")
class PreImageryIntegrationTests(unittest.TestCase):
    def test_local_maxar_resolves_for_pilot_when_open_skipped(self) -> None:
        bbox = wgs84_bounds(PILOT_POST)
        with patch("geoagent.tools.pre_imagery.try_maxar_open", return_value=None):
            result = resolve_pre_imagery(
                bbox,
                providers=["maxar_open", "local_maxar"],
                download=False,
                disaster_date=date(2025, 1, 7),
            )
        self.assertEqual(result.provider, "local_maxar")
        self.assertTrue(result.path.is_file())
        self.assertGreater(result.overlap_ratio, 0.5)

    def test_detect_la_event_for_pilot_bbox(self) -> None:
        bbox = wgs84_bounds(PILOT_POST)
        try:
            event = detect_maxar_open_event(bbox)
        except Exception as exc:  # noqa: BLE001
            self.skipTest(f"Maxar Open catalog unavailable: {exc}")
        self.assertEqual(event, "WildFires-LosAngeles-Jan-2025")


if __name__ == "__main__":
    unittest.main()
