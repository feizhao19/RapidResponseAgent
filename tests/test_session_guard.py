"""Tests for session guard remapping and session AOI inference."""

from __future__ import annotations

import unittest

from geoagent.tools.assessment_session import infer_session_aoi_from_history
from geoagent.tools.chat_context import ChatTurn
from geoagent.tools.intent_router import IntentResult, classify_intent
from geoagent.tools.session_guard import apply_historical_session_guard


HISTORICAL_ASSISTANT = """### Damage Assessment for maxar_031311102212

Matched AOIs: maxar_031311102212

Verified assessment summary for Topanga, la_wildfires_jan2025:
damaged_count: 88
"""


class SessionGuardTests(unittest.TestCase):
    def test_infer_session_aoi_from_assistant_turn(self) -> None:
        history = [
            ChatTurn("user", "tell me more about this case"),
            ChatTurn("assistant", HISTORICAL_ASSISTANT),
        ]
        self.assertEqual(infer_session_aoi_from_history(history), "maxar_031311102212")

    def test_hospital_follow_up_remaps_new_assessment(self) -> None:
        history = [
            ChatTurn("user", "tell me more about this case"),
            ChatTurn("assistant", HISTORICAL_ASSISTANT),
        ]
        misclassified = IntentResult(
            intent="new_assessment",
            confidence=0.8,
            method="llm",
            slots={"question": "any hospital nearby?"},
            raw_text="any hospital nearby?",
        )
        result = apply_historical_session_guard(
            misclassified,
            [{"role": t.role, "content": t.content} for t in history],
        )
        self.assertEqual(result.intent, "historical_assessment")
        self.assertEqual(result.slots.get("aoi_id"), "maxar_031311102212")

    def test_hospital_question_rules_route_historical(self) -> None:
        history = [
            {"role": "user", "content": "tell me more about this case"},
            {"role": "assistant", "content": HISTORICAL_ASSISTANT},
        ]
        result = classify_intent("any hospital nearby?", use_llm=False, chat_history=history)
        self.assertEqual(result.intent, "historical_assessment")
        self.assertEqual(result.slots.get("aoi_id"), "maxar_031311102212")


if __name__ == "__main__":
    unittest.main()
