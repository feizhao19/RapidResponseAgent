"""GPU-aware job queue for assessment pipeline workers."""

from __future__ import annotations

import os
import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

MAX_CONCURRENT_GPU_JOBS = max(1, int(os.environ.get("GEOAGENT_MAX_GPU_JOBS", "1")))

_gpu_semaphore = threading.Semaphore(MAX_CONCURRENT_GPU_JOBS)
_work_queue: queue.Queue[PipelineWorkItem | None] = queue.Queue()
_worker_lock = threading.Lock()
_worker_thread: threading.Thread | None = None
_runner: Callable[["PipelineWorkItem"], None] | None = None

JobKind = Literal["pipeline", "vlm_review"]
VlmReviewMode = Literal["both", "discrepancy", "damage"]


@dataclass(frozen=True)
class PipelineWorkItem:
    job_id: str
    aligned_dir: Path
    aoi_id: str
    session_id: str | None = None
    kind: JobKind = "pipeline"
    vlm_mode: VlmReviewMode = "both"
    vlm_limit: int = 8
    vlm_damaged_only: bool = True


def _ensure_worker() -> None:
    global _worker_thread
    with _worker_lock:
        if _worker_thread is not None and _worker_thread.is_alive():
            return
        if _runner is None:
            raise RuntimeError("Pipeline job runner is not configured")
        _worker_thread = threading.Thread(
            target=_worker_loop,
            name="geoagent-pipeline-queue",
            daemon=True,
        )
        _worker_thread.start()


def configure_pipeline_runner(runner: Callable[[PipelineWorkItem], None]) -> None:
    global _runner
    _runner = runner


def queue_depth() -> int:
    return _work_queue.qsize()


def active_gpu_slots() -> int:
    # Semaphore value is not introspectable; expose configured max instead.
    return MAX_CONCURRENT_GPU_JOBS


def enqueue_pipeline_job(
    job_id: str,
    aligned_dir: Path,
    aoi_id: str,
    *,
    session_id: str | None = None,
    kind: JobKind = "pipeline",
    vlm_mode: VlmReviewMode = "both",
    vlm_limit: int = 8,
    vlm_damaged_only: bool = True,
) -> int:
    """Queue a GPU job. Returns 1-based queue position."""
    from web.api.jobs import update_job

    _ensure_worker()
    position = queue_depth() + 1
    label = "VLM review" if kind == "vlm_review" else "assessment pipeline"
    if position <= MAX_CONCURRENT_GPU_JOBS:
        message = f"Starting {label}…"
        status = "running"
    else:
        waiting = position - MAX_CONCURRENT_GPU_JOBS
        message = (
            f"Queued for GPU ({waiting} job{'s' if waiting != 1 else ''} ahead)…"
        )
        status = "queued"
    update_job(
        job_id,
        status=status,
        message=message,
        session_id=session_id,
        queue_position=position,
        job_kind=kind,
        vlm_mode=vlm_mode if kind == "vlm_review" else None,
        vlm_limit=vlm_limit if kind == "vlm_review" else None,
        vlm_damaged_only=vlm_damaged_only if kind == "vlm_review" else None,
    )
    _work_queue.put(
        PipelineWorkItem(
            job_id=job_id,
            aligned_dir=aligned_dir,
            aoi_id=aoi_id,
            session_id=session_id,
            kind=kind,
            vlm_mode=vlm_mode,
            vlm_limit=vlm_limit,
            vlm_damaged_only=vlm_damaged_only,
        )
    )
    return position


def _worker_loop() -> None:
    assert _runner is not None
    from web.api.jobs import update_job

    while True:
        item = _work_queue.get()
        try:
            if item is None:
                return
            with _gpu_semaphore:
                label = "VLM review" if item.kind == "vlm_review" else "assessment pipeline"
                update_job(
                    item.job_id,
                    status="running",
                    message=f"Running {label}…",
                    queue_position=0,
                )
                _runner(item)
        finally:
            _work_queue.task_done()
