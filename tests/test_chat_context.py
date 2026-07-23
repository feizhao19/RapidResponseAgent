"""Tests for multi-turn chat context helpers."""

from __future__ import annotations

import unittest
from pathlib import Path

from geoagent.tools.chat_context import (
    ChatTurn,
    disambiguate_aoi,
    enrich_query_from_history,
    infer_aoi_from_history,
    is_follow_up,
    resolve_question_with_history,
)
from geoagent.tools.session_guard import is_historical_qa_session
from geoagent.tools.historical_index import build_assessment_index
from geoagent.tools.historical_query import execute_query, filter_records, parse_natural_language


ROOT = Path(__file__).resolve().parents[1]
PILOT_STATS = ROOT / "data/aligned/maxar_031311102212/aoi_out/aoi_stats.json"


class ChatContextTests(unittest.TestCase):
    def test_follow_up_detection(self) -> None:
        self.assertTrue(is_follow_up("what about destroyed?"))
        self.assertTrue(is_follow_up("what is the statistic information of this"))
        self.assertTrue(is_follow_up("I mean how many buildings it has"))
        self.assertFalse(is_follow_up("what happened in Topanga"))

    def test_resolve_city_from_history(self) -> None:
        history = [
            ChatTurn("user", "what happened in Topanga"),
            ChatTurn("assistant", "Topanga had 85 damaged buildings."),
        ]
        resolved = resolve_question_with_history("what about destroyed?", history)
        self.assertIn("Topanga", resolved)

    def test_resolve_pronoun_follow_up(self) -> None:
        history = [ChatTurn("user", "Topanga 2025 wildfire damaged count")]
        resolved = resolve_question_with_history("what is the statistic information of this", history)
        self.assertIn("Topanga", resolved)
        self.assertIn("Follow-up", resolved)

    def test_enrich_carries_city_and_metric(self) -> None:
        history = [ChatTurn("user", "Topanga 2025 wildfire damaged count")]
        query = parse_natural_language("how many?")
        query.raw_text = "how many?"
        query = enrich_query_from_history(query, history)
        self.assertEqual(query.city, "Topanga")
        self.assertEqual(query.metric, "damage_breakdown")

    def test_buildings_follow_up_uses_buildings_total(self) -> None:
        history = [
            ChatTurn("user", "Topanga 2025 wildfire damaged count"),
            ChatTurn("assistant", "The Topanga 2025 wildfire damaged count was 104."),
        ]
        query = parse_natural_language("I mean how many buildings it has")
        query.raw_text = "I mean how many buildings it has"
        query = enrich_query_from_history(query, history)
        self.assertEqual(query.metric, "buildings_total")
        self.assertEqual(query.city, "Topanga")

    @unittest.skipUnless(PILOT_STATS.is_file(), "pilot aoi_stats.json not present")
    def test_infer_aoi_from_assistant_number(self) -> None:
        index = build_assessment_index()
        records = filter_records(index, parse_natural_language("Topanga"))
        history = [
            ChatTurn("user", "Topanga 2025 wildfire damaged count"),
            ChatTurn("assistant", "The Topanga 2025 wildfire damaged count was 104."),
        ]
        self.assertEqual(infer_aoi_from_history(history, records), "upload_130ea1ac498a")

    @unittest.skipUnless(PILOT_STATS.is_file(), "pilot aoi_stats.json not present")
    def test_disambiguate_prefers_pilot_aoi_for_new_city_query(self) -> None:
        index = build_assessment_index()
        query = parse_natural_language("Topanga 2025 wildfire damaged count")
        query.raw_text = query.raw_text or "Topanga 2025 wildfire damaged count"
        records = filter_records(index, query)
        self.assertEqual(disambiguate_aoi(query, records, []), "maxar_031311102212")

    @unittest.skipUnless(PILOT_STATS.is_file(), "pilot aoi_stats.json not present")
    def test_scoped_buildings_query_after_damaged_follow_up(self) -> None:
        index = build_assessment_index()
        history = [
            ChatTurn("user", "Topanga 2025 wildfire damaged count"),
            ChatTurn("assistant", "The Topanga 2025 wildfire damaged count was 104."),
        ]
        query = parse_natural_language("I mean how many buildings it has")
        query.raw_text = "I mean how many buildings it has"
        query = enrich_query_from_history(query, history)
        records = filter_records(index, query)
        query.aoi_id = disambiguate_aoi(query, records, history)
        result = execute_query(query, index=index)
        self.assertEqual(query.aoi_id, "upload_130ea1ac498a")
        self.assertEqual(result.matched_aoi_ids, ["upload_130ea1ac498a"])
        total = [fact for fact in result.facts if fact.label == "buildings_total"]
        self.assertEqual(len(total), 1)
        self.assertEqual(total[0].value, 445)

    def test_historical_qa_session_detection(self) -> None:
        history = [
            ChatTurn("user", "Topanga damaged count"),
            ChatTurn("assistant", "85 damaged buildings."),
        ]
        self.assertTrue(is_historical_qa_session(history))
        self.assertFalse(is_historical_qa_session([]))


if __name__ == "__main__":
    unittest.main()
