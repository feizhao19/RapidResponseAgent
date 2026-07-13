"""Tests for official vs fused assessment report generation."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from geoagent.agents.report_agent import generate_assessment_reports, load_stats_with_scopes

ROOT = Path(__file__).resolve().parents[1]
PILOT_ALIGNED = ROOT / "data/aligned/maxar_031311102212"
PILOT_STATS = PILOT_ALIGNED / "aoi_out/aoi_stats.json"


@unittest.skipUnless(PILOT_STATS.is_file(), "pilot aoi stats not present")
class ReportScopeTests(unittest.TestCase):
    def test_load_stats_with_scopes_enriches_from_geojson(self) -> None:
        stats = load_stats_with_scopes(PILOT_STATS, PILOT_ALIGNED)
        self.assertIn("scopes", stats)
        self.assertEqual(stats["scopes"]["official"]["buildings"]["total"], 593)
        self.assertEqual(stats["scopes"]["fused"]["buildings"]["total"], 691)

    def test_generate_dual_reports(self) -> None:
        stats = load_stats_with_scopes(PILOT_STATS, PILOT_ALIGNED)
        out_dir = self._tmp_out_dir()
        paths = generate_assessment_reports(
            PILOT_STATS,
            out_dir,
            aligned_dir=PILOT_ALIGNED,
            hospitals_path=PILOT_ALIGNED / "aoi_out/nearest_hospitals.json",
        )

        self.assertTrue(paths["official"].is_file())
        self.assertTrue(paths["fused"].is_file())

        official_md = paths["official"].read_text()
        fused_md = paths["fused"].read_text()

        self.assertIn("Official footprints (LARIAC6 only)", official_md)
        self.assertIn("Official footprints + ViPDE-detected extra structures", fused_md)
        self.assertIn("Total buildings in assessment: **593**", official_md)
        self.assertIn("Total buildings in assessment: **691**", fused_md)
        self.assertIn("Detected orphan-damage structures", fused_md)
        self.assertNotIn("Detected orphan-damage structures", official_md)

        official_damaged = stats["scopes"]["official"]["damage_summary"]["damaged_count"]
        fused_damaged = stats["scopes"]["fused"]["damage_summary"]["damaged_count"]
        self.assertIn(f"Damaged (minor + major + destroyed): **{official_damaged}**", official_md)
        self.assertIn(f"Damaged (minor + major + destroyed): **{fused_damaged}**", fused_md)

        self.assertIn("## Damage Summary", official_md)
        self.assertIn("| Damage | Buildings | % |", official_md)
        self.assertNotIn("Assignment coverage", official_md)
        self.assertNotIn("effective damage level", official_md.lower())
        self.assertNotIn("observed vs inferred", official_md.lower())

    def _tmp_out_dir(self) -> Path:
        out_dir = PILOT_ALIGNED / "aoi_out" / "_report_scope_test"
        out_dir.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: _cleanup_dir(out_dir))
        return out_dir


def _cleanup_dir(path: Path) -> None:
    for child in path.iterdir():
        child.unlink()
    path.rmdir()


if __name__ == "__main__":
    unittest.main()
