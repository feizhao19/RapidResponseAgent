"""Assessment job progress for upload UI polling."""

from __future__ import annotations

import re
from typing import Any

# update_job imported lazily to avoid circular import with web.api.jobs

# Weights sum to 100 for a single overall progress bar.
STEP_WEIGHTS: dict[str, int] = {
    "upload": 2,
    "align": 5,
    "route": 3,
    "preprocessing": 5,
    "location": 5,
    "perception": 45,
    "fusion": 7,
    "vlm_arbitrate": 8,
    "stats": 4,
    "facilities": 4,
    "report": 5,
    "visualization": 5,
    "finalize": 5,
}

PROGRESS_TOTAL = sum(STEP_WEIGHTS.values())

UPLOAD_STEP_LABELS: dict[str, str] = {
    "upload": "Upload received",
    "align": "Aligning pre/post GeoTIFF pair",
    "route": "Routing to assessment pipeline",
}

PIPELINE_STEP_LABELS: dict[str, str] = {
    "preprocessing": "Preprocessing imagery",
    "location": "Resolving location (geocoding)",
    "perception": "ViPDE damage perception",
    "fusion": "Fusing damage to building footprints",
    "vlm_arbitrate": "VLM reviewing footprints and predicted damage",
    "stats": "Computing AOI statistics",
    "facilities": "Looking up nearest hospitals",
    "report": "Generating assessment report",
    "visualization": "Rendering map overlays",
    "finalize": "Finalizing outputs",
}

STEP_LABELS = {**UPLOAD_STEP_LABELS, **PIPELINE_STEP_LABELS}

ORDERED_STEPS = list(UPLOAD_STEP_LABELS) + list(PIPELINE_STEP_LABELS)

TILE_PROGRESS_RE = re.compile(r"tiles\s+(\d+)/(\d+)", re.IGNORECASE)


def step_label(step: str) -> str:
    return STEP_LABELS.get(step, step.replace("_", " ").title())


def _empty_progress() -> dict[str, Any]:
    return {
        "overall_current": 0,
        "overall_total": PROGRESS_TOTAL,
        "current_step": None,
        "current_label": None,
        "step_status": "pending",
        "message": None,
        "unit_current": None,
        "unit_total": None,
        "unit_label": None,
        "completed_steps": [],
        "timeline": [],
    }


def _weighted_current(progress: dict[str, Any]) -> float:
    completed = progress.get("completed_steps") or []
    done = sum(STEP_WEIGHTS.get(step, 0) for step in completed)

    current = progress.get("current_step")
    if not current or current in completed:
        return float(done)

    weight = STEP_WEIGHTS.get(current, 0)
    if current == "perception":
        unit_total = progress.get("unit_total") or 0
        unit_current = progress.get("unit_current") or 0
        if unit_total > 0:
            done += weight * (unit_current / unit_total)
        return done

    # Step started but no sub-units yet — show a sliver of progress.
    return done + min(weight * 0.05, 0.5)


def _sync_overall(progress: dict[str, Any]) -> dict[str, Any]:
    weighted = _weighted_current(progress)
    progress["overall_current"] = min(PROGRESS_TOTAL, int(round(weighted)))
    progress["overall_total"] = PROGRESS_TOTAL
    return progress


def _append_timeline(progress: dict[str, Any], step: str, status: str, message: str | None) -> None:
    timeline = list(progress.get("timeline") or [])
    entry = {
        "step": step,
        "label": step_label(step),
        "status": status,
        "message": message,
    }
    for index, item in enumerate(timeline):
        if item.get("step") == step:
            timeline[index] = entry
            progress["timeline"] = timeline
            return
    timeline.append(entry)
    progress["timeline"] = timeline


def load_progress(job: dict[str, Any]) -> dict[str, Any]:
    progress = dict(job.get("progress") or _empty_progress())
    merged_completed = list(progress.get("completed_steps") or [])
    for step in job.get("completed_steps") or []:
        if step not in merged_completed:
            merged_completed.append(step)
    progress["completed_steps"] = merged_completed
    return _sync_overall(progress)


def mark_job_progress_complete(job_id: str, *, message: str | None = None) -> dict[str, Any]:
    from web.api.jobs import get_job, update_job

    job = get_job(job_id)
    progress = load_progress(job)
    progress["completed_steps"] = list(ORDERED_STEPS)
    progress["current_step"] = None
    progress["current_label"] = None
    progress["step_status"] = "done"
    progress["unit_current"] = None
    progress["unit_total"] = None
    progress["unit_label"] = None
    progress["overall_current"] = PROGRESS_TOTAL
    progress["overall_total"] = PROGRESS_TOTAL
    progress["message"] = message or "Assessment completed — results are ready."
    for step in ORDERED_STEPS:
        _append_timeline(progress, step, "done", progress["message"] if step == "finalize" else None)
    return update_job(
        job_id,
        progress=progress,
        completed_steps=list(ORDERED_STEPS),
        message=progress["message"],
    )


def apply_progress_event(job_id: str, event: dict[str, Any]) -> dict[str, Any]:
    from web.api.jobs import get_job, update_job

    job = get_job(job_id)
    progress = load_progress(job)
    event_type = event.get("type")
    step = str(event.get("step") or progress.get("current_step") or "")
    message = event.get("message")

    if event_type == "step_start":
        progress["current_step"] = step
        progress["current_label"] = step_label(step)
        progress["step_status"] = "running"
        progress["message"] = message or f"Running {step_label(step)}…"
        progress["unit_current"] = None
        progress["unit_total"] = None
        progress["unit_label"] = None
        _append_timeline(progress, step, "running", progress["message"])

    elif event_type == "step_done":
        completed = list(progress.get("completed_steps") or [])
        if step and step not in completed:
            completed.append(step)
        progress["completed_steps"] = completed
        progress["step_status"] = "done"
        progress["message"] = message or f"Finished {step_label(step)}"
        progress["unit_current"] = None
        progress["unit_total"] = None
        progress["unit_label"] = None
        _append_timeline(progress, step, "done", progress["message"])

    elif event_type == "units":
        progress["current_step"] = step or progress.get("current_step")
        progress["current_label"] = step_label(str(progress["current_step"] or step))
        progress["step_status"] = "running"
        progress["unit_current"] = int(event.get("unit_current") or 0)
        progress["unit_total"] = int(event.get("unit_total") or 0)
        progress["unit_label"] = event.get("unit_label") or "units"
        unit_message = message or (
            f"{progress['unit_label']} {progress['unit_current']}/{progress['unit_total']}"
        )
        progress["message"] = unit_message
        _append_timeline(progress, str(progress["current_step"]), "running", unit_message)

    elif event_type == "message":
        if message:
            progress["message"] = message
            if progress.get("current_step"):
                _append_timeline(
                    progress,
                    str(progress["current_step"]),
                    str(progress.get("step_status") or "running"),
                    message,
                )

    progress = _sync_overall(progress)
    return update_job(
        job_id,
        progress=progress,
        completed_steps=progress.get("completed_steps") or [],
        message=progress.get("message"),
    )


def make_progress_emit(job_id: str):
    def emit(event: dict[str, Any]) -> None:
        apply_progress_event(job_id, event)

    return emit


def parse_vipde_progress_line(line: str) -> dict[str, int] | None:
    match = TILE_PROGRESS_RE.search(line)
    if not match:
        return None
    return {"unit_current": int(match.group(1)), "unit_total": int(match.group(2))}
