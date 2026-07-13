"""Tests for past-assessment VLM review job start."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from web.api.jobs import start_vlm_review_job
from web.api.models import VlmReviewRequest


def test_vlm_review_request_normalizes_mode() -> None:
    assert VlmReviewRequest(mode="Damage").mode == "damage"
    with pytest.raises(ValueError):
        VlmReviewRequest(mode="all")


def test_cancel_job_marks_cancelled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from web.api import jobs as jobs_mod

    monkeypatch.setattr(jobs_mod, "JOBS_ROOT", tmp_path)
    job = jobs_mod.create_job(aoi_id="maxar_test", job_kind="vlm_review")
    job_id = str(job["job_id"])
    jobs_mod.update_job(job_id, status="running", message="Running VLM…")
    event = jobs_mod.register_job_control(job_id)

    out = jobs_mod.cancel_job(job_id)
    assert out["status"] == "cancelled"
    assert event.is_set()


def test_start_vlm_review_job_queues(tmp_path: Path) -> None:
    aligned = tmp_path / "aligned" / "maxar_test"
    buildings = aligned / "buildings_out"
    buildings.mkdir(parents=True)
    (buildings / "buildings_with_damage.geojson").write_text(
        '{"type":"FeatureCollection","features":[]}\n'
    )

    record = {"aoi_id": "maxar_test", "aligned_dir": str(aligned)}
    fake_job = {
        "job_id": "job_test",
        "aoi_id": "maxar_test",
        "status": "queued",
        "job_kind": "vlm_review",
    }

    with (
        patch("web.api.services.find_aoi_record", return_value=record),
        patch("web.api.services.aligned_dir_for_record", return_value=aligned),
        patch("web.api.jobs.create_job", return_value=fake_job),
        patch("web.api.jobs.update_job", return_value=fake_job),
        patch("web.api.jobs.get_job", return_value=fake_job),
        patch("web.api.jobs.register_job_control"),
        patch("web.api.jobs.enqueue_pipeline_job") as enqueue,
    ):
        out = start_vlm_review_job("maxar_test", mode="discrepancy", limit=4)
        assert out["job_id"] == "job_test"
        enqueue.assert_called_once()
        kwargs = enqueue.call_args.kwargs
        assert kwargs["kind"] == "vlm_review"
        assert kwargs["vlm_mode"] == "discrepancy"
        assert kwargs["vlm_limit"] == 4
