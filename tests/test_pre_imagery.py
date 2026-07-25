"""Tests for pre-disaster imagery resolution priority."""

from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from geoagent.tools.pre_imagery import (
    PreImageryCandidate,
    detect_maxar_open_event,
    extract_date_from_text,
    resolve_disaster_date,
    resolve_pre_imagery,
    try_local_maxar,
)
from geoagent.tools.preprocess import find_overlapping_pre, wgs84_bounds

ROOT = Path(__file__).resolve().parents[1]
PILOT_POST = ROOT / "data" / "aligned" / "maxar_031311102212" / "post.tif"
LOCAL_MAXAR_ROOT = ROOT / "data" / "pre_disaster" / "maxar" / "11"


class DisasterDateInferenceTests(unittest.TestCase):
    def test_parse_iso_and_compact_dates(self) -> None:
        self.assertEqual(extract_date_from_text("2025-01-07"), date(2025, 1, 7))
        self.assertEqual(extract_date_from_text("post_20250128a.tif"), date(2025, 1, 28))
        self.assertEqual(extract_date_from_text("WildFires-LosAngeles-Jan-2025"), date(2025, 1, 1))
        self.assertEqual(extract_date_from_text("2025:01:28 10:11:12"), date(2025, 1, 28))

    def test_explicit_disaster_date_wins(self) -> None:
        resolved = resolve_disaster_date(
            disaster_date="2025-01-07",
            post_filename="post_20250128a.tif",
        )
        self.assertEqual(resolved, date(2025, 1, 7))

    def test_filename_when_no_explicit(self) -> None:
        resolved = resolve_disaster_date(post_filename="noaa_20250128a_chip.tif")
        self.assertEqual(resolved, date(2025, 1, 28))

    def test_known_la_event_from_bbox(self) -> None:
        bbox = (-118.60, 34.08, -118.59, 34.09)
        resolved = resolve_disaster_date(post_bbox=bbox)
        self.assertEqual(resolved, date(2025, 1, 7))

    def test_require_disaster_date_raises_when_unknown(self) -> None:
        bbox = (10.0, 10.0, 10.1, 10.1)
        with self.assertRaises(ValueError):
            resolve_pre_imagery(
                bbox,
                providers=["local_maxar"],
                download=False,
                require_disaster_date=True,
            )


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
            result = resolve_pre_imagery(bbox, download=False, disaster_date="2025-01-07")
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
            result = resolve_pre_imagery(bbox, download=False, disaster_date="2025-01-07")
            self.assertEqual(result.provider, "naip")
            self.assertEqual(result.gsd_m, 0.6)
            usgs.assert_not_called()
            ee.assert_not_called()
            noaa.assert_not_called()

    def test_falls_back_through_usgs_then_noaa(self) -> None:
        # Non-LA bbox so no known-event disaster cutoff is inferred.
        bbox = (10.0, 10.0, 10.1, 10.1)
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
            # Without a disaster cutoff, undated USGS mosaics remain eligible.
            result = resolve_pre_imagery(bbox, download=False)
            self.assertEqual(result.provider, "usgs_naip_imageserver")
            ee.assert_not_called()
            noaa.assert_not_called()

    def test_rejects_post_dated_candidate(self) -> None:
        bbox = (-118.60, 34.08, -118.59, 34.09)
        late = PreImageryCandidate(
            provider="maxar_open",
            path=Path("/tmp/late.tif"),
            date="2025-01-20",
            overlap_ratio=0.99,
        )
        early = PreImageryCandidate(
            provider="local_maxar",
            path=Path("/tmp/early.tif"),
            date="2024-12-14",
            overlap_ratio=0.8,
        )
        with (
            patch("geoagent.tools.pre_imagery.try_maxar_open", return_value=late),
            patch("geoagent.tools.pre_imagery.try_local_maxar", return_value=early),
            patch("geoagent.tools.pre_imagery.try_naip_planetary_computer", return_value=None),
            patch("geoagent.tools.pre_imagery.try_usgs_naip_imageserver", return_value=None),
            patch("geoagent.tools.pre_imagery.try_usgs_earthexplorer", return_value=None),
            patch("geoagent.tools.pre_imagery.try_noaa_digital_coast", return_value=None),
        ):
            result = resolve_pre_imagery(bbox, disaster_date="2025-01-07", download=False)
        self.assertEqual(result.provider, "local_maxar")
        self.assertEqual(result.extras.get("disaster_date"), "2025-01-07")
        # 2024-12-14 is in the previous calendar month → allowed under 1-month gap.
        self.assertEqual(result.date, "2024-12-14")

    def test_rejects_same_month_as_disaster(self) -> None:
        bbox = (-118.60, 34.08, -118.59, 34.09)
        same_month = PreImageryCandidate(
            provider="maxar_open",
            path=Path("/tmp/same_month.tif"),
            date="2024-12-20",
            overlap_ratio=0.99,
        )
        earlier = PreImageryCandidate(
            provider="local_maxar",
            path=Path("/tmp/earlier.tif"),
            date="2024-11-15",
            overlap_ratio=0.8,
        )
        with (
            patch("geoagent.tools.pre_imagery.try_maxar_open", return_value=same_month),
            patch("geoagent.tools.pre_imagery.try_local_maxar", return_value=earlier),
            patch("geoagent.tools.pre_imagery.try_naip_planetary_computer", return_value=None),
            patch("geoagent.tools.pre_imagery.try_usgs_naip_imageserver", return_value=None),
            patch("geoagent.tools.pre_imagery.try_usgs_earthexplorer", return_value=None),
            patch("geoagent.tools.pre_imagery.try_noaa_digital_coast", return_value=None),
        ):
            result = resolve_pre_imagery(bbox, disaster_date="2024-12-25", download=False)
        self.assertEqual(result.provider, "local_maxar")
        self.assertEqual(result.date, "2024-11-15")

    def test_skips_undated_usgs_when_cutoff_set(self) -> None:
        bbox = (-118.60, 34.08, -118.59, 34.09)
        with (
            patch("geoagent.tools.pre_imagery.try_maxar_open", return_value=None),
            patch("geoagent.tools.pre_imagery.try_local_maxar", return_value=None),
            patch("geoagent.tools.pre_imagery.try_naip_planetary_computer", return_value=None),
            patch(
                "geoagent.tools.pre_imagery.try_usgs_naip_imageserver",
                return_value=PreImageryCandidate(
                    provider="usgs_naip_imageserver",
                    path=Path("/tmp/usgs.tif"),
                    overlap_ratio=1.0,
                ),
            ) as usgs,
            patch("geoagent.tools.pre_imagery.try_usgs_earthexplorer", return_value=None),
            patch("geoagent.tools.pre_imagery.try_noaa_digital_coast", return_value=None),
        ):
            with self.assertRaises(FileNotFoundError):
                resolve_pre_imagery(bbox, disaster_date="2025-01-07", download=False)
            usgs.assert_called()

    def test_to_meta_includes_provider_fields(self) -> None:
        candidate = PreImageryCandidate(
            provider="local_maxar",
            path=Path("/tmp/a.tif"),
            date="2024-12-21",
            overlap_ratio=0.7,
            extras={"quad": "031311102212", "disaster_date": "2025-01-07"},
        )
        meta = candidate.to_meta()
        self.assertEqual(meta["provider"], "local_maxar")
        self.assertEqual(meta["extras"]["quad"], "031311102212")
        self.assertEqual(meta["disaster_date"], "2025-01-07")


@unittest.skipUnless(LOCAL_MAXAR_ROOT.is_dir(), "local Maxar catalog not present")
class LocalMaxarDateConstraintTests(unittest.TestCase):
    def test_find_overlapping_pre_rejects_on_or_after_cutoff(self) -> None:
        visual = next(LOCAL_MAXAR_ROOT.rglob("*-visual.tif"), None)
        if visual is None:
            self.skipTest("no local Maxar visual tiles")
        bbox = wgs84_bounds(visual)
        with self.assertRaises(FileNotFoundError):
            find_overlapping_pre(bbox, before=date(2020, 1, 1))

    def test_try_local_maxar_keeps_only_pre_event_dates(self) -> None:
        visual = next(LOCAL_MAXAR_ROOT.rglob("*-visual.tif"), None)
        if visual is None:
            self.skipTest("no local Maxar visual tiles")
        bbox = wgs84_bounds(visual)
        hit = try_local_maxar(bbox, before=date(2025, 1, 7))
        if hit is None:
            self.skipTest("no overlapping local Maxar scene before 2025-01-07")
        self.assertIsNotNone(hit.date)
        self.assertLess(date.fromisoformat(str(hit.date)[:10]), date(2025, 1, 7))


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
        self.assertLess(date.fromisoformat(str(result.date)[:10]), date(2025, 1, 7))

    def test_detect_la_event_for_pilot_bbox(self) -> None:
        bbox = wgs84_bounds(PILOT_POST)
        event = detect_maxar_open_event(bbox)
        self.assertEqual(event, "WildFires-LosAngeles-Jan-2025")


if __name__ == "__main__":
    unittest.main()
