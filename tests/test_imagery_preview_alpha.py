"""Map preview alpha: punch align black borders, keep interior dark pixels."""

from __future__ import annotations

import unittest

import numpy as np

from web.api.services import _border_connected_empty_mask, _preview_alpha_from_rgb


class ImageryPreviewAlphaTests(unittest.TestCase):
    def test_border_empty_mask_keeps_interior_zero(self) -> None:
        intensity = np.full((20, 20), 120, dtype=np.uint8)
        intensity[:3, :] = 0  # top pad
        intensity[8:12, 8:12] = 0  # interior dark “roof”
        mask = _border_connected_empty_mask(intensity, empty_max=0)
        self.assertTrue(mask[0, 10])
        self.assertTrue(mask[2, 5])
        self.assertFalse(mask[10, 10])
        self.assertFalse(mask[15, 15])

    def test_preview_alpha_punches_border_keeps_interior(self) -> None:
        rgb = np.full((3, 30, 30), 100, dtype=np.uint8)
        rgb[:, :4, :] = 0
        rgb[:, 12:16, 12:16] = 0
        alpha = _preview_alpha_from_rgb(rgb, fringe_dilate=2, feather_px=0)
        self.assertEqual(int(alpha[0, 15]), 0)
        self.assertEqual(int(alpha[14, 14]), 255)
        self.assertEqual(int(alpha[20, 20]), 255)


if __name__ == "__main__":
    unittest.main()
