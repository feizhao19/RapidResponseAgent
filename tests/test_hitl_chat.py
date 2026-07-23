"""Tests for human-in-the-loop confirm / cancel in chat graph."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from geoagent.graph.chat_graph import reset_chat_graph_cache
from geoagent.runtime.agent import run_agent_turn
from geoagent.runtime.hitl import is_cancellation, is_confirmation
from geoagent.runtime.memory import SessionStore
from geoagent.runtime.tools import ToolResult
from geoagent.tools.intent_router import IntentResult


class HitlHelpersTests(unittest.TestCase):
    def test_confirm_phrases(self) -> None:
        self.assertTrue(is_confirmation("yes"))
        self.assertTrue(is_confirmation("继续"))
        self.assertFalse(is_confirmation("how many damaged?"))

    def test_cancel_phrases(self) -> None:
        self.assertTrue(is_cancellation("no"))
        self.assertTrue(is_cancellation("取消"))
        self.assertFalse(is_cancellation("nearest hospital"))


class HitlChatGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_chat_graph_cache()

    def test_multi_tool_plan_pauses_for_confirm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionStore(root=Path(tmp))
            fake = IntentResult(
                intent="historical_assessment",
                confidence=0.9,
                method="rules",
                slots={
                    "aoi_id": "upload_stickyaoi01",
                    "route": {"l1": "chat_qa", "l2": "report", "l3": "full"},
                },
                rationale="stats+report",
                raw_text="stats and full report",
            )
            with (
                patch("geoagent.graph.chat_graph.classify_intent", return_value=fake),
                patch(
                    "geoagent.graph.chat_graph.plan_tools",
                    return_value=["get_damage_stats", "generate_report"],
                ),
            ):
                result = run_agent_turn(
                    "stats and full report",
                    session_store=store,
                    active_aoi_id="upload_stickyaoi01",
                    use_llm=False,
                )
            self.assertEqual(result.last_node, "await_confirm")
            self.assertIn("yes", (result.answer_markdown or "").lower())
            session = store.get_session(result.session_id)
            self.assertIsNotNone(session.pending_action)
            self.assertEqual(
                session.pending_action.get("tools"),
                ["get_damage_stats", "generate_report"],
            )

    def test_yes_resumes_pending_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionStore(root=Path(tmp))
            session = store.create_session(active_aoi_id="upload_stickyaoi01")
            store.update_session(
                session.session_id,
                pending_action={
                    "kind": "multi_tool_confirm",
                    "tools": ["get_damage_stats", "generate_report"],
                    "entry_node": "tools",
                    "aoi_id": "upload_stickyaoi01",
                    "question": "stats and report",
                },
            )

            def _fake_run(tool_name: str, ctx):  # noqa: ANN001
                return ToolResult(
                    tool=tool_name,
                    success=True,
                    answer_markdown=f"ok:{tool_name}",
                )

            with patch("geoagent.graph.chat_graph.run_tool", side_effect=_fake_run):
                result = run_agent_turn(
                    "yes",
                    session_id=session.session_id,
                    session_store=store,
                    use_llm=False,
                )
            self.assertEqual(result.tools_called, ["get_damage_stats", "generate_report"])
            self.assertIn("ok:get_damage_stats", result.answer_markdown or "")
            refreshed = store.get_session(session.session_id)
            self.assertIsNone(refreshed.pending_action)

    def test_no_cancels_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionStore(root=Path(tmp))
            session = store.create_session(active_aoi_id="upload_stickyaoi01")
            store.update_session(
                session.session_id,
                pending_action={
                    "kind": "multi_tool_confirm",
                    "tools": ["get_damage_stats", "generate_report"],
                    "entry_node": "tools",
                    "aoi_id": "upload_stickyaoi01",
                    "question": "stats and report",
                },
            )
            result = run_agent_turn(
                "no",
                session_id=session.session_id,
                session_store=store,
                use_llm=False,
            )
            self.assertEqual(result.last_node, "hitl_cancel")
            self.assertIn("cancelled", (result.answer_markdown or "").lower())
            refreshed = store.get_session(session.session_id)
            self.assertIsNone(refreshed.pending_action)


if __name__ == "__main__":
    unittest.main()
