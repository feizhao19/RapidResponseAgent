"""Tests for hybrid intent router."""

from __future__ import annotations

import unittest

from geoagent.tools.chat_context import ChatTurn
from geoagent.tools.session_guard import is_historical_qa_session
from geoagent.tools.intent_router import classify_by_rules, classify_intent


class IntentRouterRuleTests(unittest.TestCase):
    def test_historical_topanga_damage(self) -> None:
        result = classify_by_rules("Topanga 2025 wildfire damaged count")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.intent, "historical_assessment")
        self.assertEqual(result.slots.get("city"), "Topanga")

    def test_historical_what_happened_in_city(self) -> None:
        result = classify_by_rules("what happened in Topanga")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.intent, "historical_assessment")
        self.assertEqual(result.slots.get("city"), "Topanga")

    def test_chat_default_routes_open_questions_to_historical(self) -> None:
        result = classify_intent("help me with damage", use_llm=False)
        self.assertEqual(result.intent, "historical_assessment")

    def test_quad_with_historical_keywords(self) -> None:
        result = classify_by_rules(
            "Summarize the damage assessment for maxar_031311102212 for an EOC briefing."
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.intent, "historical_assessment")
        self.assertEqual(result.slots.get("aoi_id"), "maxar_031311102212")

    def test_new_assessment_quad(self) -> None:
        result = classify_by_rules("Analyze quad 031311102212 with resume")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.intent, "new_assessment")
        self.assertEqual(result.slots.get("quad"), "031311102212")

    def test_weather_forecast(self) -> None:
        result = classify_by_rules("What is the wind forecast for Topanga tomorrow?")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.intent, "weather_context")
        self.assertEqual(result.slots.get("city"), "Topanga")

    def test_ambiguous_without_default_becomes_clarify(self) -> None:
        result = classify_intent("hello", use_llm=False, default_to_historical=False)
        self.assertEqual(result.intent, "clarify")

    def test_new_assessment_without_quad_clarifies(self) -> None:
        result = classify_by_rules("Run the pipeline to preprocess and analyze new imagery")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.intent, "clarify")

    def test_historical_session_blocks_new_assessment(self) -> None:
        history = [
            {"role": "user", "content": "Topanga 2025 wildfire damaged count"},
            {"role": "assistant", "content": "The damaged count was 85."},
        ]
        self.assertTrue(is_historical_qa_session([ChatTurn("user", history[0]["content"]), ChatTurn("assistant", history[1]["content"])]))
        result = classify_intent("Analyze quad 031311102212", use_llm=False, chat_history=history)
        self.assertEqual(result.intent, "clarify")
        self.assertEqual(result.method, "session_guard")
        self.assertIn("New chat", result.clarification or "")

    def test_fresh_session_allows_new_assessment(self) -> None:
        result = classify_intent("Analyze quad 031311102212", use_llm=False, chat_history=[])
        self.assertEqual(result.intent, "new_assessment")


if __name__ == "__main__":
    unittest.main()
