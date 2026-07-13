"""Bind completed assessment jobs to server-side chat sessions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from geoagent.runtime.memory import SessionStore

_store = SessionStore()


def format_assessment_completion_message(
    *,
    aoi_id: str,
    job_id: str,
    valid_pair_coverage: float | None = None,
    assessment_report: str | None = None,
) -> str:
    lines = [
        "**Assessment completed**",
        "",
        f"Job `{job_id}` · completed",
        "",
        "**Overall progress: 100/100**",
    ]
    if valid_pair_coverage is not None:
        lines.append(f"Valid pair coverage: **{valid_pair_coverage * 100:.1f}%**")
    lines.append(f"Results for **{aoi_id}** are loaded on the right.")
    if assessment_report and Path(assessment_report).is_file():
        lines.append(f"Report: `{assessment_report}`")
    return "\n\n".join(lines)


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
