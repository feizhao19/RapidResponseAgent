from __future__ import annotations

import unittest
from pathlib import Path

from geoagent.tools.preprocess import (
    _intersection_area_ratio,
    find_overlapping_pre,
    run_upload_align,
    wgs84_bounds,
)

ROOT = Path(__file__).resolve().parents[1]
PILOT_POST = ROOT / "data" / "aligned" / "maxar_031311102212" / "post.tif"


@unittest.skipUnless(PILOT_POST.is_file(), "pilot aligned post.tif not present")
class PreprocessUploadTests(unittest.TestCase):
    def test_find_overlapping_pre_for_pilot_post(self) -> None:
        bbox = wgs84_bounds(PILOT_POST)
        match = find_overlapping_pre(bbox)
        self.assertEqual(match["quad"], "031311102212")
        self.assertGreater(float(match["overlap_ratio"]), 0.5)

    def test_intersection_area_ratio_full_overlap(self) -> None:
        bbox = (-118.6, 34.0, -118.5, 34.1)
        self.assertAlmostEqual(_intersection_area_ratio(bbox, bbox), 1.0)

    def test_upload_align_crops_to_post_extent(self) -> None:
        post_candidates = list((ROOT / "data" / "uploads").rglob("post.tif"))
        if not post_candidates:
            self.skipTest("no uploaded post.tif available for crop test")
        post_path = post_candidates[0]
        out_dir = ROOT / "data" / "aligned" / "_test_crop_upload_py"
        if out_dir.exists():
            import shutil

            shutil.rmtree(out_dir)
        aligned_dir, meta = run_upload_align(
            post_path=post_path,
            auto_match_pre=True,
            aoi_id="_test_crop_upload_py",
        )
        try:
            import rasterio

            with rasterio.open(aligned_dir / "pre.tif") as ds:
                pixels = ds.width * ds.height
            self.assertLess(pixels, 50_000_000)
            self.assertGreater(meta.get("valid_pair_coverage", 0), 0.5)
            self.assertTrue(meta.get("crop_to_post"))
        finally:
            import shutil

            shutil.rmtree(out_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
