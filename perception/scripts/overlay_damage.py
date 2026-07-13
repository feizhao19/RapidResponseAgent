#!/usr/bin/env python3
"""Overlay an existing damage mask on pre/post images with a class legend."""

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vipde.utils import save_damage_overlays


def parse_args():
    parser = argparse.ArgumentParser(description="Create damage overlay images with legend")
    parser.add_argument("--pre-image", required=True, help="Pre-disaster RGB image")
    parser.add_argument("--post-image", required=True, help="Post-disaster RGB image")
    parser.add_argument("--damage-mask", required=True, help="Single-channel damage mask PNG")
    parser.add_argument("--output-dir", required=True, help="Directory for overlay outputs")
    parser.add_argument("--alpha", type=float, default=0.5, help="Overlay opacity for damage classes")
    return parser.parse_args()


def main():
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    pre_rgb = np.array(Image.open(args.pre_image).convert("RGB"))
    post_rgb = np.array(Image.open(args.post_image).convert("RGB"))
    mask_np = np.array(Image.open(args.damage_mask))

    if pre_rgb.shape[:2] != mask_np.shape[:2]:
        raise ValueError("Pre image and damage mask must have the same height and width.")
    if post_rgb.shape[:2] != mask_np.shape[:2]:
        raise ValueError("Post image and damage mask must have the same height and width.")

    paths = save_damage_overlays(
        pre_rgb,
        post_rgb,
        mask_np,
        str(output_dir),
        alpha=args.alpha,
    )
    for path in paths.values():
        print(f"Saved: {path}")


if __name__ == "__main__":
    main()
