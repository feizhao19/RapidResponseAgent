from __future__ import annotations

import unittest

import numpy as np

from geoagent.tools.registration import apply_pixel_shift, estimate_phase_shift


class RegistrationTests(unittest.TestCase):
    def test_detects_known_shift(self) -> None:
        rng = np.random.default_rng(0)
        ref = rng.integers(30, 220, size=(256, 256), dtype=np.uint8)
        valid = np.ones((256, 256), dtype=bool)
        moved = np.zeros_like(ref)
        moved[3:, 5:] = ref[:-3, :-5]

        row_shift, col_shift, peak = estimate_phase_shift(ref, moved, valid, max_dim=256)
        self.assertGreater(peak, 0.2)
        self.assertAlmostEqual(abs(row_shift), 3.0, delta=1.5)
        self.assertAlmostEqual(abs(col_shift), 5.0, delta=1.5)

    def test_apply_shift_roundtrip(self) -> None:
        arr = np.arange(100, dtype=np.float32).reshape(10, 10)
        shifted = apply_pixel_shift(arr, 2.0, -1.0)
        self.assertEqual(shifted.shape, arr.shape)


if __name__ == "__main__":
    unittest.main()
