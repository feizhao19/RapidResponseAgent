"""Unit tests for ViPDE sliding-window batching helpers."""

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path

import numpy as np
import torch

VIPDE_ROOT = Path(__file__).resolve().parents[1] / "perception" / "vipde"


def _load_sliding_window():
    """Load sliding_window without importing vipde/__init__ (avoids SAM dependency)."""
    for name in ("vipde", "vipde.utils"):
        sys.modules.setdefault(name, types.ModuleType(name))

    def _load(mod_name: str, path: Path):
        spec = importlib.util.spec_from_file_location(mod_name, path)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
        return mod

    _load("vipde.utils.preprocess", VIPDE_ROOT / "utils" / "preprocess.py")
    return _load("vipde.utils.sliding_window", VIPDE_ROOT / "utils" / "sliding_window.py")


sw = _load_sliding_window()


class SlidingWindowBatchTests(unittest.TestCase):
    def test_window_starts_covers_edge(self) -> None:
        starts = sw.window_starts(100, 64, 32)
        self.assertEqual(starts[0], 0)
        self.assertEqual(starts[-1], 100 - 64)

    def test_pad_tile_black_edge(self) -> None:
        arr = np.ones((40, 50, 3), dtype=np.uint8) * 7
        padded, vh, vw = sw.pad_tile_black(arr, 64)
        self.assertEqual(padded.shape, (64, 64, 3))
        self.assertEqual((vh, vw), (40, 50))
        self.assertEqual(int(padded[0, 0, 0]), 7)
        self.assertEqual(int(padded[63, 63, 0]), 0)

    def test_sliding_window_batch_matches_batch_one(self) -> None:
        rng = np.random.default_rng(0)
        h, w = 96, 80
        pre = rng.integers(0, 255, size=(h, w, 3), dtype=np.uint8)
        post = rng.integers(0, 255, size=(h, w, 3), dtype=np.uint8)
        tile = 64
        device = torch.device("cpu")

        def forward_fn(model, pre_t, post_t, *, use_fp16, device):  # noqa: ARG001
            mean = 0.5 * (pre_t.mean(dim=1, keepdim=True) + post_t.mean(dim=1, keepdim=True))
            zeros = torch.zeros_like(mean)
            return torch.cat([mean, -mean, zeros.expand(-1, 1, -1, -1)], dim=1)

        common = dict(
            model=None,
            pre_orig=pre,
            post_orig=post,
            device=device,
            img_size=tile,
            tile_size=tile,
            stride=32,
            num_classes=3,
            pixel_mean=[0.5, 0.5, 0.5],
            pixel_std=[0.5, 0.5, 0.5],
            use_fp16=False,
            forward_fn=forward_fn,
        )
        pred1, logits1 = sw.sliding_window_predict(**common, batch_size=1)
        pred4, logits4 = sw.sliding_window_predict(**common, batch_size=4)

        self.assertEqual(pred1.shape, (h, w))
        self.assertEqual(logits1.shape, (3, h, w))
        np.testing.assert_allclose(logits1, logits4, rtol=1e-5, atol=1e-5)
        np.testing.assert_array_equal(pred1, pred4)


if __name__ == "__main__":
    unittest.main()
