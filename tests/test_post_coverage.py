"""Tests for post-disaster / pre catalog coverage classification."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import TestCase

from geoagent.tools.post_coverage import (
    WITH_PRE,
    WITHOUT_PRE,
    apply_post_disaster_split,
    classify_noaa_tile,
)
from geoagent.tools.preprocess import (
    DEFAULT_NOAA_FLIGHT,
    _parse_noaa_name,
    iter_noaa_tiles,
    noaa_flight_dirs,
)


class PostCoverageTest(TestCase):
    def test_parse_noaa_bbox(self) -> None:
        bbox = _parse_noaa_name("20250128aC1183945w340300n.tif", DEFAULT_NOAA_FLIGHT)
        self.assertIsNotNone(bbox)
        west, south, east, north = bbox  # type: ignore[misc]
        self.assertLess(west, east)
        self.assertLess(south, north)

    def test_classify_known_tile_against_local_catalog(self) -> None:
        root = Path(__file__).resolve().parents[1] / "data"
        tiles = iter_noaa_tiles(data_root=root)
        if not tiles:
            self.skipTest("no local NOAA tiles")
        item = classify_noaa_tile(tiles[0], data_root=root)
        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item.provider, "noaa")
        self.assertIn(item.bucket(), (WITH_PRE, WITHOUT_PRE))

    def test_split_dry_run(self) -> None:
        root = Path(__file__).resolve().parents[1] / "data"
        report = apply_post_disaster_split(data_root=root, dry_run=True)
        self.assertIn("summary", report)
        self.assertEqual(
            report["summary"]["total"],
            report["summary"]["with_pre"] + report["summary"]["without_pre"],
        )

    def test_noaa_dirs_include_split_layout(self) -> None:
        root = Path(__file__).resolve().parents[1] / "data"
        dirs = noaa_flight_dirs(data_root=root)
        if not dirs:
            self.skipTest("no NOAA directories")
        coverage = root / "post_disaster" / "coverage_split.json"
        if coverage.is_file():
            payload = json.loads(coverage.read_text())
            self.assertIn("summary", payload)
