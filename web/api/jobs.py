"""Background assessment job tracking for web uploads."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from geoagent.graph.aoi_graph import run_aoi_pipeline
from geoagent.graph.state import PipelineState
from geoagent.tools.historical_index import DATA
from geoagent.tools.python_env import resolve_vipde_python
from web.api.job_progress import apply_progress_event, make_progress_emit, mark_job_progress_complete
from web.api.job_queue import PipelineWorkItem, configure_pipeline_runner, enqueue_pipeline_job
from web.api.session_binding import bind_completed_assessment

JobStatusName = Literal["queued", "aligning", "running", "completed", "failed", "cancelled"]

JOBS_ROOT = DATA / "uploads"
MAX_UPLOAD_BYTES = 300 * 1024 * 1024
_lock = threading.Lock()
_control_lock = threading.Lock()
_job_controls: dict[str, dict[str, Any]] = {}


def register_job_control(job_id: str) -> threading.Event:
    with _control_lock:
        existing = _job_controls.get(job_id)
        if existing and existing.get("cancel") is not None:
            return existing["cancel"]
        cancel = threading.Event()
        _job_controls[job_id] = {"cancel": cancel, "process": None}
        return cancel


def bind_job_process(job_id: str, process: Any) -> None:
    with _control_lock:
        ctrl = _job_controls.get(job_id)
        if not ctrl:
            return
        ctrl["process"] = process
        if ctrl["cancel"].is_set() and process.poll() is None:
            _terminate_bound_process(process)


def clear_job_control(job_id: str) -> None:
    with _control_lock:
        _job_controls.pop(job_id, None)


def _terminate_bound_process(process: Any) -> None:
    import os
    import signal

    try:
        if getattr(process, "pid", None) and hasattr(os, "killpg"):
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.terminate()
        except (ProcessLookupError, OSError):
            pass


def cancel_job(job_id: str) -> dict[str, Any]:
    """Request cancellation of a queued/running job and kill its subprocess if any."""
    job = get_job(job_id)
    status = str(job.get("status") or "")
    if status in {"completed", "failed", "cancelled"}:
        return job

    with _control_lock:
        ctrl = _job_controls.get(job_id)
        if ctrl:
            ctrl["cancel"].set()
            process = ctrl.get("process")
            if process is not None:
                _terminate_bound_process(process)

    return update_job(
        job_id,
        status="cancelled",
        message="Cancelled by user",
        queue_position=0,
    )


def new_job_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"job_{stamp}_{uuid.uuid4().hex[:8]}"


def new_upload_aoi_id() -> str:
    return f"upload_{uuid.uuid4().hex[:12]}"


def job_dir(job_id: str) -> Path:
    return JOBS_ROOT / job_id


def job_path(job_id: str) -> Path:
    return job_dir(job_id) / "job.json"


def _write_job(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    path = job_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return payload


def create_job(
    *,
    aoi_id: str,
    auto_match_pre: bool = False,
    session_id: str | None = None,
    job_kind: str = "assessment",
) -> dict[str, Any]:
    job_id = new_job_id()
    payload = {
        "job_id": job_id,
        "aoi_id": aoi_id,
        "session_id": session_id,
        "status": "queued",
        "job_kind": job_kind,
        "auto_match_pre": auto_match_pre,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "message": "Job created",
        "completed_steps": [],
        "errors": [],
        "queue_position": 0,
    }
    return _write_job(job_id, payload)


def update_job(job_id: str, **fields: Any) -> dict[str, Any]:
    with _lock:
        path = job_path(job_id)
        if not path.is_file():
            raise KeyError(f"Job not found: {job_id}")
        current = json.loads(path.read_text())
        current.update(fields)
        return _write_job(job_id, current)


def get_job(job_id: str) -> dict[str, Any]:
    with _lock:
        path = job_path(job_id)
        if not path.is_file():
            raise KeyError(f"Job not found: {job_id}")
        return json.loads(path.read_text())


def validate_geotiff(path: Path) -> None:
    suffix = path.suffix.lower()
    if suffix not in {".tif", ".tiff"}:
        raise ValueError(f"Expected GeoTIFF (.tif/.tiff), got {path.name}")

    size = path.stat().st_size
    if size <= 0:
        raise ValueError(f"{path.name} is empty")
    if size > MAX_UPLOAD_BYTES:
        raise ValueError(f"{path.name} exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit")

    import rasterio

    with rasterio.open(path) as dataset:
        if dataset.crs is None:
            raise ValueError(f"{path.name} has no CRS; upload a georeferenced GeoTIFF")
        if dataset.count < 1:
            raise ValueError(f"{path.name} has no raster bands")


def _run_pipeline_work(item: PipelineWorkItem) -> None:
    if item.kind == "vlm_review":
        _run_vlm_review_work(item)
        return

    job_id = item.job_id
    aligned_dir = item.aligned_dir
    aoi_id = item.aoi_id
    session_id = item.session_id
    try:
        apply_progress_event(
            job_id,
            {
                "type": "step_start",
                "step": "route",
                "message": "Routing to assessment pipeline…",
            },
        )
        apply_progress_event(job_id, {"type": "step_done", "step": "route"})
        vipde_python = resolve_vipde_python()
        state: PipelineState = {
            "aligned_dir": str(aligned_dir.resolve()),
            "aoi_id": aoi_id,
            "skip_preprocess": True,
            "event": "la_wildfires_jan2025",
            "vipde_python": vipde_python,
            "_progress_emit": make_progress_emit(job_id),
        }
        final = run_aoi_pipeline(state)
        errors = list(final.get("errors") or [])
        completed = list(final.get("completed_steps") or [])
        job_snapshot = get_job(job_id)
        valid_pair_coverage = job_snapshot.get("valid_pair_coverage")
        if errors:
            update_job(
                job_id,
                status="failed",
                message="Pipeline finished with errors",
                completed_steps=completed,
                errors=errors,
                aligned_dir=str(aligned_dir),
                assessment_report=final.get("assessment_report"),
                queue_position=0,
            )
            return

        update_job(
            job_id,
            status="completed",
            message="Assessment completed",
            errors=[],
            aligned_dir=str(aligned_dir),
            assessment_report=final.get("assessment_report"),
            aoi_stats_json=final.get("aoi_stats_json"),
            queue_position=0,
        )
        mark_job_progress_complete(
            job_id,
            message="Assessment completed — results are ready.",
        )
        if session_id:
            bind_completed_assessment(
                session_id=session_id,
                aoi_id=aoi_id,
                job_id=job_id,
                valid_pair_coverage=valid_pair_coverage,
                assessment_report=final.get("assessment_report"),
            )
    except Exception as exc:  # noqa: BLE001 — persist job failure for UI polling
        update_job(
            job_id,
            status="failed",
            message=str(exc),
            errors=[str(exc)],
            queue_position=0,
        )


def _run_vlm_review_work(item: PipelineWorkItem) -> None:
    from geoagent.agents.vlm_arbitrate_agent import run_vlm_arbitrate
    from geoagent.graph.runner import JobCancelled

    job_id = item.job_id
    aligned_dir = item.aligned_dir
    aoi_id = item.aoi_id
    cancel_event = register_job_control(job_id)
    try:
        if cancel_event.is_set() or get_job(job_id).get("status") == "cancelled":
            update_job(job_id, status="cancelled", message="Cancelled by user", queue_position=0)
            return

        apply_progress_event(
            job_id,
            {
                "type": "step_start",
                "step": "vlm_arbitrate",
                "message": "VLM reviewing footprints and predicted damage…",
            },
        )
        state: PipelineState = {
            "aligned_dir": str(aligned_dir.resolve()),
            "aoi_id": aoi_id,
            "resume": False,
            "fusion_mode": "max",
            "vlm_arbitrate_limit": item.vlm_limit,
            "vlm_damage_limit": item.vlm_limit,
            "skip_vlm_discrepancy": item.vlm_mode == "damage",
            "skip_vlm_damage_review": item.vlm_mode == "discrepancy",
            "vlm_discrepancy_damaged_only": bool(item.vlm_damaged_only),
            "_progress_emit": make_progress_emit(job_id),
            "_job_cancel_event": cancel_event,
            "_bind_job_process": lambda process: bind_job_process(job_id, process),
        }
        updates = run_vlm_arbitrate(state)
        if cancel_event.is_set() or get_job(job_id).get("status") == "cancelled":
            update_job(job_id, status="cancelled", message="Cancelled by user", queue_position=0)
            return
        completed = list(updates.get("completed_steps") or ["vlm_arbitrate"])
        update_job(
            job_id,
            status="completed",
            message="VLM review completed",
            errors=[],
            completed_steps=completed,
            aligned_dir=str(aligned_dir),
            vlm_arbitration_json=updates.get("vlm_arbitration_json"),
            vlm_damage_review_json=updates.get("vlm_damage_review_json"),
            queue_position=0,
        )
        apply_progress_event(job_id, {"type": "step_done", "step": "vlm_arbitrate"})
        mark_job_progress_complete(job_id, message="VLM review completed — results are ready.")
    except JobCancelled as exc:
        update_job(
            job_id,
            status="cancelled",
            message=str(exc) or "Cancelled by user",
            errors=[],
            queue_position=0,
        )
    except Exception as exc:  # noqa: BLE001 — persist job failure for UI polling
        if cancel_event.is_set() or get_job(job_id).get("status") == "cancelled":
            update_job(job_id, status="cancelled", message="Cancelled by user", queue_position=0)
            return
        update_job(
            job_id,
            status="failed",
            message=str(exc),
            errors=[str(exc)],
            queue_position=0,
        )
    finally:
        clear_job_control(job_id)


configure_pipeline_runner(_run_pipeline_work)


def start_pipeline_job(
    job_id: str,
    aligned_dir: Path,
    aoi_id: str,
    *,
    session_id: str | None = None,
) -> int:
    return enqueue_pipeline_job(
        job_id,
        aligned_dir,
        aoi_id,
        session_id=session_id,
        kind="pipeline",
    )


def start_vlm_review_job(
    aoi_id: str,
    *,
    mode: Literal["both", "discrepancy", "damage"] = "both",
    limit: int = 8,
    damaged_only: bool = True,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Queue VLM footprint/damage review for an existing past assessment."""
    from web.api.services import aligned_dir_for_record, find_aoi_record

    if mode not in {"both", "discrepancy", "damage"}:
        raise ValueError("mode must be both, discrepancy, or damage")
    limit = max(1, min(int(limit), 64))

    record = find_aoi_record(aoi_id)
    aligned_dir = aligned_dir_for_record(record)
    buildings = aligned_dir / "buildings_out" / "buildings_with_damage.geojson"
    if not buildings.is_file():
        raise FileNotFoundError(
            f"No fused buildings for `{aoi_id}`. Complete fusion before VLM review."
        )

    job = create_job(aoi_id=aoi_id, session_id=session_id, job_kind="vlm_review")
    job_id = str(job["job_id"])
    register_job_control(job_id)
    update_job(
        job_id,
        message="Queued VLM review",
        aligned_dir=str(aligned_dir),
        vlm_mode=mode,
        vlm_limit=limit,
        vlm_damaged_only=damaged_only,
    )
    enqueue_pipeline_job(
        job_id,
        aligned_dir,
        aoi_id,
        session_id=session_id,
        kind="vlm_review",
        vlm_mode=mode,
        vlm_limit=limit,
        vlm_damaged_only=damaged_only,
    )
    return get_job(job_id)
