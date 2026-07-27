"""Perception agent: ViPDE pixel-level damage inference."""

from __future__ import annotations

import sys
from pathlib import Path

from geoagent.graph.progress import emit_tile_progress
from geoagent.graph.runner import ROOT, run_command
from geoagent.graph.state import PipelineState
from geoagent.graph.step_runner import execute_step

WEIGHTS = ROOT / "perception" / "checkpoints" / "vipde_vitb_damage_v1.pth"
PREDICT_SCRIPT = ROOT / "perception" / "scripts" / "predict.py"


def _run_impl(state: PipelineState) -> dict:
    aligned_dir = Path(state["aligned_dir"])
    damage_mask = aligned_dir / "vipde_out" / "damage_mask.png"

    if state.get("skip_vipde"):
        if not damage_mask.is_file():
            raise RuntimeError(
                f"Cannot use --skip-vipde: damage mask not found at {damage_mask}. "
                "Run perception without --skip-vipde first."
            )
        print(f"Using existing {damage_mask}")
        return {
            "damage_mask": str(damage_mask),
            "completed_steps": ["perception"],
        }

    if damage_mask.is_file():
        print(f"Using existing {damage_mask}")
        return {
            "damage_mask": str(damage_mask),
            "completed_steps": ["perception"],
        }

    vipde_python = state.get("vipde_python")
    py = Path(vipde_python) if vipde_python else Path(sys.executable)

    def on_output_line(line: str) -> None:
        emit_tile_progress(state, "perception", line)

    run_command(
        [
            str(py),
            str(PREDICT_SCRIPT),
            "--pre-image",
            str(aligned_dir / "pre.tif"),
            "--post-image",
            str(aligned_dir / "post.tif"),
            "--weights",
            str(WEIGHTS),
            "--output-dir",
            str(aligned_dir / "vipde_out"),
            "--sliding-window",
            "--tile-size",
            "1024",
            "--stride",
            "512",
            "--img-size",
            "1024",
            "--batch-size",
            "4",
        ],
        "Perception (ViPDE)",
        on_output_line=on_output_line,
    )
    return {
        "damage_mask": str(damage_mask),
        "completed_steps": ["perception"],
    }


def run_perception(state: PipelineState) -> dict:
    return execute_step(state, "perception", "Perception", lambda: _run_impl(state))
