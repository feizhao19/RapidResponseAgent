"""Handle user GeoTIFF uploads and kick off assessment jobs."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from geoagent.tools.preprocess import run_upload_align
from web.api.job_progress import apply_progress_event
from web.api.jobs import (
    create_job,
    job_dir,
    new_upload_aoi_id,
    start_pipeline_job,
    update_job,
    validate_geotiff,
)


def _start_footprint_prefetch(aligned_dir: Path) -> None:
    """Fire-and-forget footprint cache warm after align (overlaps queue + ViPDE)."""
    import threading

    def _warm() -> None:
        try:
            from geoagent.tools.building_footprints import prefetch_official_footprints

            prefetch_official_footprints(aligned_dir, source="overture")
        except Exception as exc:  # noqa: BLE001 — fusion retries; never fail upload
            print(f"Early footprint prefetch failed (will retry in pipeline): {exc}")

    threading.Thread(
        target=_warm,
        name=f"footprint-prefetch-{aligned_dir.name}",
        daemon=True,
    ).start()


async def save_upload_file(upload: UploadFile, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as handle:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
    validate_geotiff(destination)


async def submit_assessment_upload(
    *,
    post: UploadFile,
    pre: UploadFile | None,
    auto_match_pre: bool,
    session_id: str | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    if pre is None and not auto_match_pre:
        raise ValueError("Upload a pre GeoTIFF or enable automatic pre matching.")

    if session_id:
        from geoagent.runtime.memory import SessionStore

        store = SessionStore()
        store.get_or_create_session(session_id)
        if message and message.strip():
            store.append_message(session_id, role="user", content=message.strip())

    aoi_id = new_upload_aoi_id()
    job = create_job(aoi_id=aoi_id, auto_match_pre=auto_match_pre, session_id=session_id)
    job_id = str(job["job_id"])
    apply_progress_event(job_id, {"type": "step_start", "step": "upload", "message": "Receiving upload…"})
    apply_progress_event(job_id, {"type": "step_done", "step": "upload", "message": "Upload received"})
    staging = job_dir(job_id)

    post_path = staging / "post.tif"
    await save_upload_file(post, post_path)

    pre_path: Path | None = None
    if pre is not None:
        pre_path = staging / "pre.tif"
        await save_upload_file(pre, pre_path)

    update_job(
        job_id,
        status="aligning",
        message="Aligning pre/post GeoTIFF pair…",
        upload={
            "post_filename": post.filename,
            "pre_filename": pre.filename if pre else None,
            "auto_match_pre": auto_match_pre,
        },
    )
    apply_progress_event(
        job_id,
        {"type": "step_start", "step": "align", "message": "Aligning pre/post GeoTIFF pair…"},
    )

    try:
        aligned_dir, meta = run_upload_align(
            post_path=post_path,
            pre_path=pre_path,
            auto_match_pre=auto_match_pre,
            aoi_id=aoi_id,
        )
    except Exception as exc:
        update_job(
            job_id,
            status="failed",
            message=str(exc),
            errors=[str(exc)],
        )
        return get_job_payload(job_id)

    update_job(
        job_id,
        status="queued",
        message="Alignment complete; starting assessment pipeline…",
        aligned_dir=str(aligned_dir),
        meta=meta,
        pre_match=meta.get("pre_match"),
        valid_pair_coverage=meta.get("valid_pair_coverage"),
    )
    apply_progress_event(
        job_id,
        {"type": "step_done", "step": "align", "message": "Alignment complete"},
    )

    # Warm Overture/LARIAC cache while the job waits in queue / ViPDE runs.
    _start_footprint_prefetch(aligned_dir)

    # Keep a copy of uploads alongside the job record for audit/debugging.
    archive = staging / "inputs"
    archive.mkdir(parents=True, exist_ok=True)
    shutil.copy2(post_path, archive / "post.tif")
    if pre_path and pre_path.is_file():
        shutil.copy2(pre_path, archive / "pre.tif")

    start_pipeline_job(job_id, aligned_dir, aoi_id, session_id=session_id)
    return get_job_payload(job_id)


def get_job_payload(job_id: str) -> dict[str, Any]:
    from web.api.jobs import get_job

    job = get_job(job_id)
    return {
        "job_id": job["job_id"],
        "aoi_id": job.get("aoi_id"),
        "session_id": job.get("session_id"),
        "status": job.get("status"),
        "message": job.get("message"),
        "job_kind": job.get("job_kind"),
        "vlm_mode": job.get("vlm_mode"),
        "vlm_limit": job.get("vlm_limit"),
        "vlm_damaged_only": job.get("vlm_damaged_only"),
        "auto_match_pre": job.get("auto_match_pre"),
        "pre_match": job.get("pre_match"),
        "valid_pair_coverage": job.get("valid_pair_coverage"),
        "completed_steps": job.get("completed_steps") or [],
        "progress": job.get("progress"),
        "errors": job.get("errors") or [],
        "aligned_dir": job.get("aligned_dir"),
        "queue_position": job.get("queue_position"),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
    }
