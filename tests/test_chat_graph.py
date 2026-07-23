"""Tests for chat LangGraph entry nodes, AOI gates, and sticky AOI."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from geoagent.graph.chat_graph import (
    _entry_from_tools,
    _sticky_resolve_aoi,
    build_chat_graph,
    reset_chat_graph_cache,
    route_after_prepare,
)
from geoagent.runtime.agent import run_agent_turn
from geoagent.runtime.memory import SessionStore
from geoagent.runtime.tools import ToolResult
from geoagent.tools.intent_router import IntentResult


class ChatGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_chat_graph_cache()

    def test_graph_compiles_with_expected_nodes(self) -> None:
        app = build_chat_graph()
        self.assertTrue(callable(app.invoke))

    def test_route_after_prepare_branches(self) -> None:
        self.assertEqual(route_after_prepare({"branch": "clarify"}), "clarify")
        self.assertEqual(route_after_prepare({"branch": "weather"}), "weather")
        self.assertEqual(route_after_prepare({"branch": "damage_stats"}), "damage_stats")
        self.assertEqual(route_after_prepare({"branch": "hospitals"}), "hospitals")
        self.assertEqual(route_after_prepare({"branch": "report"}), "report")

    def test_entry_from_tools(self) -> None:
        self.assertEqual(_entry_from_tools(["weather_context"]), "weather")
        self.assertEqual(_entry_from_tools(["get_damage_stats"]), "damage_stats")
        self.assertEqual(
            _entry_from_tools(["get_damage_stats", "generate_report"]),
            "tools",
        )

    def test_sticky_aoi_keeps_session_on_follow_up(self) -> None:
        aoi = _sticky_resolve_aoi(
            question="what about destroyed?",
            routed_question="what about destroyed?",
            ui_aoi=None,
            session_aoi="upload_aaaaaaaa1111",
            history=[],
            slot_aoi="upload_bbbbbbbb2222",
        )
        self.assertEqual(aoi, "upload_aaaaaaaa1111")

    def test_sticky_aoi_allows_explicit_switch(self) -> None:
        aoi = _sticky_resolve_aoi(
            question="stats for upload_bbbbbbbb2222",
            routed_question="stats for upload_bbbbbbbb2222",
            ui_aoi=None,
            session_aoi="upload_aaaaaaaa1111",
            history=[],
            slot_aoi="upload_bbbbbbbb2222",
        )
        self.assertEqual(aoi, "upload_bbbbbbbb2222")

    def test_ui_aoi_wins(self) -> None:
        aoi = _sticky_resolve_aoi(
            question="how many damaged?",
            routed_question="how many damaged?",
            ui_aoi="upload_cccccccc3333",
            session_aoi="upload_aaaaaaaa1111",
            history=[],
            slot_aoi="upload_bbbbbbbb2222",
        )
        self.assertEqual(aoi, "upload_cccccccc3333")

    def test_clarify_turn_via_graph(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionStore(root=Path(tmp))
            fake = IntentResult(
                intent="clarify",
                confidence=0.9,
                method="rules",
                slots={"route": {"l1": "meta", "l2": "capability", "l3": "inform"}},
                rationale="test",
                clarification="Please clarify your request.",
                raw_text="hello?",
            )
            with patch("geoagent.graph.chat_graph.classify_intent", return_value=fake):
                result = run_agent_turn(
                    "hello?",
                    session_store=store,
                    use_llm=False,
                )
            self.assertEqual(result.intent, "clarify")
            self.assertEqual(result.last_node, "clarify")
            self.assertIn("clarify", (result.answer_markdown or "").lower())
            self.assertEqual(result.route.get("l1"), "meta")

    def test_aoi_gate_blocks_stats_without_aoi(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionStore(root=Path(tmp))
            fake = IntentResult(
                intent="historical_assessment",
                confidence=0.95,
                method="rules",
                slots={"route": {"l1": "chat_qa", "l2": "damage_stats", "l3": "count"}},
                rationale="stats",
                raw_text="how many damaged?",
            )
            with (
                patch("geoagent.graph.chat_graph.classify_intent", return_value=fake),
                patch(
                    "geoagent.graph.chat_graph.plan_tools",
                    return_value=["get_damage_stats"],
                ),
            ):
                result = run_agent_turn(
                    "how many damaged?",
                    session_store=store,
                    use_llm=False,
                )
            self.assertEqual(result.last_node, "aoi_gate")
            self.assertIn("past assessment", (result.answer_markdown or "").lower())
            self.assertIn("missing_active_aoi", result.errors)

    def test_follow_up_keeps_session_aoi_across_intents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionStore(root=Path(tmp))
            session = store.create_session(active_aoi_id="upload_stickyaoi01")
            store.append_message(session.session_id, role="user", content="Topanga damaged count")
            store.append_message(
                session.session_id,
                role="assistant",
                content="104 damaged for upload_stickyaoi01",
            )

            stats_intent = IntentResult(
                intent="historical_assessment",
                confidence=0.9,
                method="rules",
                slots={"route": {"l1": "chat_qa", "l2": "damage_stats", "l3": "count"}},
                rationale="stats",
                raw_text="what about destroyed?",
            )
            mock_result = ToolResult(
                tool="get_damage_stats",
                success=True,
                answer_markdown="Destroyed: 12",
            )
            with (
                patch("geoagent.graph.chat_graph.classify_intent", return_value=stats_intent),
                patch(
                    "geoagent.graph.chat_graph.plan_tools",
                    return_value=["get_damage_stats"],
                ),
                patch("geoagent.graph.chat_graph.run_tool", return_value=mock_result) as run_tool,
            ):
                result = run_agent_turn(
                    "what about destroyed?",
                    session_id=session.session_id,
                    session_store=store,
                    use_llm=False,
                )

            self.assertEqual(result.active_aoi_id, "upload_stickyaoi01")
            self.assertEqual(result.last_node, "damage_stats")
            ctx = run_tool.call_args[0][1]
            self.assertEqual(ctx.active_aoi_id, "upload_stickyaoi01")
            refreshed = store.get_session(session.session_id)
            self.assertEqual(refreshed.active_aoi_id, "upload_stickyaoi01")
            self.assertEqual(refreshed.last_node, "damage_stats")


if __name__ == "__main__":
    unittest.main()
