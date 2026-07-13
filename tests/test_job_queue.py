"""Tests for GPU job queue."""

from __future__ import annotations

import unittest
from pathlib import Path

from web.api.job_queue import enqueue_pipeline_job
from web.api.jobs import create_job, get_job


class JobQueueTests(unittest.TestCase):
    def test_enqueue_sets_queue_position(self) -> None:
        job = create_job(aoi_id="upload_test", auto_match_pre=True)
        job_id = job["job_id"]
        position = enqueue_pipeline_job(
            job_id,
            Path("/tmp/fake-aligned"),
            "upload_test",
        )
        self.assertGreaterEqual(position, 1)
        snapshot = get_job(job_id)
        self.assertIn(snapshot["status"], {"queued", "running"})
        self.assertIn("queue_position", snapshot)


if __name__ == "__main__":
    unittest.main()
