"""Tests for assessment index deletion."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from geoagent.tools.historical_index import (
    build_assessment_index,
    delete_assessment_aoi,
    load_assessment_index,
    write_assessment_index,
)


class DeleteAssessmentAoiTests(unittest.TestCase):
    def test_delete_removes_directory_and_refreshes_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            aligned = data_root / "aligned" / "upload_testdelete01"
            aoi_out = aligned / "aoi_out"
            aoi_out.mkdir(parents=True)
            (aoi_out / "aoi_stats.json").write_text(
                json.dumps(
                    {
                        "aoi_id": "upload_testdelete01",
                        "event": "la_wildfires_jan2025",
                        "damage_summary": {"damaged_count": 1},
                        "buildings": {"total": 1},
                    }
                )
            )
            index_path = data_root / "assessment_index.json"
            write_assessment_index(index_path, build_assessment_index(data_root=data_root))
            self.assertTrue(aligned.is_dir())

            result = delete_assessment_aoi(
                "upload_testdelete01",
                data_root=data_root,
                index_path=index_path,
            )
            self.assertEqual(result["aoi_id"], "upload_testdelete01")
            self.assertFalse(aligned.exists())
            index = load_assessment_index(index_path)
            self.assertEqual(index["aoi_count"], 0)

    def test_delete_missing_on_disk_still_drops_stale_index_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            data_root.mkdir()
            index_path = data_root / "assessment_index.json"
            write_assessment_index(
                index_path,
                {
                    "schema_version": "1.0",
                    "aoi_count": 1,
                    "events": ["la_wildfires_jan2025"],
                    "records": [
                        {
                            "aoi_id": "maxar_stale_only",
                            "event": "la_wildfires_jan2025",
                            "aligned_dir": "aligned/maxar_stale_only",
                            "summary": {"damaged_count": 1},
                        }
                    ],
                },
            )
            delete_assessment_aoi(
                "maxar_stale_only",
                data_root=data_root,
                index_path=index_path,
            )
            index = load_assessment_index(index_path)
            self.assertEqual(index["aoi_count"], 0)


if __name__ == "__main__":
    unittest.main()
