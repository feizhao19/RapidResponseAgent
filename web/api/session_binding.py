"""Bind completed assessment jobs to server-side chat sessions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from geoagent.runtime.memory import SessionStore

_store = SessionStore()

# Keep chat messages usable; full report usually fits well under this.
_MAX_REPORT_CHARS = 60_000

_MARKER_START = "§RAPID_ASSESSMENT§"
_MARKER_END = "§END§"


def _load_report_markdown(assessment_report: str | None) -> str | None:
    if not assessment_report:
        return None
    path = Path(assessment_report)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return None
    if len(text) > _MAX_REPORT_CHARS:
        text = text[:_MAX_REPORT_CHARS].rstrip() + "\n\n… (report truncated)"
    return text


def format_assessment_completion_message(
    *,
    aoi_id: str,
    job_id: str,
    valid_pair_coverage: float | None = None,
    assessment_report: str | None = None,
) -> str:
    del job_id, valid_pair_coverage  # kept for call-site compatibility; not shown in chat
    payload = {
        "v": 1,
        "status": "completed",
        "percent": 100,
        "step": "Results ready",
        "detail": None,
        "aoiId": aoi_id,
    }
    block = f"{_MARKER_START}{json.dumps(payload, separators=(',', ':'))}{_MARKER_END}"
    report_md = _load_report_markdown(assessment_report)
    if report_md:
        return f"{block}\n\n---\n\n{report_md}"
    return block


def bind_completed_assessment(
    *,
    session_id: str,
    aoi_id: str,
    job_id: str,
    valid_pair_coverage: float | None = None,
    assessment_report: str | None = None,
    store: SessionStore | None = None,
) -> dict[str, Any]:
    """Set session AOI context and append a completion assistant turn."""
    session_store = store or _store
    session_store.get_session(session_id)
    session_store.update_session(session_id, active_aoi_id=aoi_id)
    content = format_assessment_completion_message(
        aoi_id=aoi_id,
        job_id=job_id,
        valid_pair_coverage=valid_pair_coverage,
        assessment_report=assessment_report,
    )
    message = session_store.append_message(
        session_id,
        role="assistant",
        content=content,
        meta="new_assessment",
    )
    session_store.append_episode(
        session_id,
        {
            "episode_id": f"job-{job_id}",
            "event": "assessment_completed",
            "job_id": job_id,
            "aoi_id": aoi_id,
            "active_aoi_id": aoi_id,
        },
    )
    return message
