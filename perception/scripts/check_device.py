#!/usr/bin/env python3
"""Print available inference devices for local debugging."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import torch

from vipde.utils.device import describe_device, mps_is_available, resolve_device


def main() -> None:
    print(f"torch version: {torch.__version__}")
    print(f"cuda available: {torch.cuda.is_available()}")
    print(f"mps available:  {mps_is_available()}")

    for name in ("auto", "cuda", "mps", "cpu"):
        try:
            device = resolve_device(name)
            print(f"resolve_device({name!r}) -> {describe_device(device)}")
        except (RuntimeError, ValueError) as exc:
            print(f"resolve_device({name!r}) -> ERROR: {exc}")


if __name__ == "__main__":
    main()
