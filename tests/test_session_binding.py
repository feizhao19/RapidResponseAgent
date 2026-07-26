"""Tests for assessment session binding."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from geoagent.runtime.memory import SessionStore
from web.api.session_binding import bind_completed_assessment, format_assessment_completion_message


class SessionBindingTests(unittest.TestCase):
    def test_format_completion_message(self) -> None:
        text = format_assessment_completion_message(
            aoi_id="upload_abc123abc12",
            job_id="job_test",
            valid_pair_coverage=0.99,
        )
        self.assertIn("§RAPID_ASSESSMENT§", text)
        self.assertIn('"status":"completed"', text)
        self.assertIn("upload_abc123abc12", text)
        self.assertNotIn("job_test", text)
        self.assertNotIn("Valid pair coverage", text)

    def test_format_completion_message_includes_report_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "assessment_report_official.md"
            report.write_text(
                "# Post-Disaster Building Damage Assessment\n\n"
                "- Official building polygons in AOI: **12**\n",
                encoding="utf-8",
            )
            text = format_assessment_completion_message(
                aoi_id="upload_abc123abc12",
                job_id="job_test",
                assessment_report=str(report),
            )
            self.assertIn("# Post-Disaster Building Damage Assessment", text)
            self.assertIn("Official building polygons in AOI: **12**", text)
            self.assertNotIn(f"Report: `{report}`", text)

    def test_bind_completed_assessment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionStore(root=Path(tmp))
            record = store.create_session(title="Upload chat")
            bind_completed_assessment(
                session_id=record.session_id,
                aoi_id="upload_abc123abc12",
                job_id="job_test",
                store=store,
            )
            updated = store.get_session(record.session_id)
            self.assertEqual(updated.active_aoi_id, "upload_abc123abc12")
            messages = store.list_messages(record.session_id)
            self.assertTrue(
                any('"status":"completed"' in message["content"] for message in messages)
            )


if __name__ == "__main__":
    unittest.main()
