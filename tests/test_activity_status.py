"""Tests for chat activity status emission."""

from __future__ import annotations

from unittest.mock import patch

from geoagent.graph.chat_graph import invoke_chat_turn
from geoagent.runtime.memory import SessionStore
from geoagent.runtime.tools import ToolResult


def test_activity_status_labels():
    from geoagent.runtime.activity_status import make_status, tool_label, tool_phase

    assert "damage" in tool_label("get_damage_stats").casefold()
    assert tool_phase("query_guidance") == "rag"
    assert tool_phase("get_damage_stats") == "tool"
    event = make_status(phase="answering", label="Writing answer…")
    assert event["type"] == "status"
    assert event["phase"] == "answering"


def test_clarify_emits_routing_then_answering():
    events: list[dict] = []
    invoke_chat_turn(
        "hello",
        session_store=SessionStore(),
        use_llm=False,
        on_status=events.append,
        on_token=lambda _t: None,
    )
    phases = [e["phase"] for e in events]
    assert phases[0] == "routing"
    assert phases.count("routing") >= 2
    assert "answering" in phases
    assert events[0]["status"] == "running"
    assert any(e["phase"] == "routing" and e["status"] == "done" for e in events)


def test_tool_path_emits_tool_start_and_done():
    events: list[dict] = []

    def fake_run_tool(name: str, ctx):  # noqa: ANN001
        return ToolResult(
            tool=name,
            success=True,
            answer_markdown="Stats look fine.",
        )

    with patch("geoagent.graph.chat_graph.run_tool", side_effect=fake_run_tool):
        invoke_chat_turn(
            "How many buildings were destroyed?",
            session_store=SessionStore(),
            use_llm=False,
            active_aoi_id="demo_aoi",
            on_status=events.append,
            on_token=lambda _t: None,
        )

    tool_events = [e for e in events if e.get("tool")]
    assert tool_events, f"expected tool status events, got {events}"
    assert any(e["status"] == "running" for e in tool_events)
    assert any(e["status"] == "done" for e in tool_events)
    assert any(e["phase"] == "answering" for e in events)
