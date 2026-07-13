"""Tests for completed assessment session follow-up context."""

from __future__ import annotations

import json
import unittest

from geoagent.tools.assessment_session import (
    infer_completed_assessment_aoi,
    infer_session_aoi_from_history,
    is_assessment_session_follow_up,
    normalize_slot_aoi_id,
    resolve_assessment_follow_up,
)
from geoagent.tools.chat_context import ChatTurn, resolve_question_with_history
from geoagent.agents.intent_agent import run_intent_classification


COMPLETED_ASSISTANT = """**Assessment completed**

Job `job_20260706_035812_e1268ed5` · completed

**Overall progress: 100/100**

Results for **upload_4cfc23e994d4** are loaded on the right."""


class AssessmentSessionTests(unittest.TestCase):
    def test_infer_completed_assessment_aoi(self) -> None:
        history = [
            ChatTurn("user", "Analysis on the input post.tif"),
            ChatTurn("assistant", COMPLETED_ASSISTANT),
        ]
        self.assertEqual(infer_completed_assessment_aoi(history), "upload_4cfc23e994d4")

    def test_infer_session_aoi_from_assistant_context(self) -> None:
        history = [
            ChatTurn("user", "tell me more about this case"),
            ChatTurn(
                "assistant",
                "Matched AOIs: maxar_031311102212\n\ndamaged_count: 88",
            ),
        ]
        self.assertEqual(infer_session_aoi_from_history(history), "maxar_031311102212")

    def test_infer_session_aoi_from_damage_narrative(self) -> None:
        from geoagent.tools.historical_index import build_assessment_index, write_assessment_index
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            aligned = data_root / "aligned" / "upload_4e4f58731905"
            aoi_out = aligned / "aoi_out"
            aoi_out.mkdir(parents=True)
            (aoi_out / "aoi_stats.json").write_text(
                json.dumps(
                    {
                        "aoi_id": "upload_4e4f58731905",
                        "event": "la_wildfires_jan2025",
                        "damage_summary": {"damaged_count": 95},
                        "buildings": {"total": 624},
                    }
                )
            )
            index_path = data_root / "assessment_index.json"
            write_assessment_index(index_path, build_assessment_index(data_root=data_root))

            import geoagent.tools.assessment_session as assessment_session

            original = assessment_session.load_assessment_index
            assessment_session.load_assessment_index = lambda path=index_path: original(path)
            try:
                history = [
                    ChatTurn("user", "What happened?"),
                    ChatTurn(
                        "assistant",
                        "95 buildings were damaged, which is 15.22% of the total 624 buildings.",
                    ),
                ]
                self.assertEqual(
                    infer_session_aoi_from_history(history),
                    "upload_4e4f58731905",
                )
            finally:
                assessment_session.load_assessment_index = original

    def test_follow_up_phrases(self) -> None:
        self.assertTrue(is_assessment_session_follow_up("what did we do?"))
        self.assertTrue(is_assessment_session_follow_up("我们做了什么？"))
        # Disaster-impact questions should not be treated as pipeline walkthroughs.
        self.assertFalse(is_assessment_session_follow_up("tell me what happened"))
        self.assertFalse(is_assessment_session_follow_up("what happened"))

    def test_resolve_question_scopes_to_aoi(self) -> None:
        history = [
            ChatTurn("user", "Analysis on the input post.tif"),
            ChatTurn("assistant", COMPLETED_ASSISTANT),
        ]
        resolved = resolve_question_with_history("what did we do?", history)
        self.assertIn("upload_4cfc23e994d4", resolved)
        self.assertNotIn("Analysis on the input", resolved)

    def test_intent_routes_assessment_follow_up_to_historical(self) -> None:
        history = [
            {"role": "user", "content": "Analysis on the input post.tif"},
            {"role": "assistant", "content": COMPLETED_ASSISTANT},
        ]
        updates = run_intent_classification(
            {
                "user_input": "what did we do?",
                "chat_history": history,
                "use_llm": False,
            }
        )
        self.assertEqual(updates["intent"], "historical_assessment")
        self.assertEqual(updates["session_aoi_id"], "upload_4cfc23e994d4")
        self.assertEqual(updates["intent_method"], "assessment_session")

    def test_normalize_slot_aoi_id_rejects_placeholders(self) -> None:
        self.assertIsNone(normalize_slot_aoi_id("from session"))
        self.assertIsNone(normalize_slot_aoi_id("session"))
        self.assertIsNone(normalize_slot_aoi_id(""))
        self.assertIsNone(normalize_slot_aoi_id(None))
        self.assertEqual(normalize_slot_aoi_id("maxar_031311103033"), "maxar_031311103033")
        self.assertEqual(
            normalize_slot_aoi_id("use maxar_031311102212 from session"),
            "maxar_031311102212",
        )


if __name__ == "__main__":
    unittest.main()
