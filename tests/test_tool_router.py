"""Tests for LLM tool router skill and rule fallback."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from geoagent.runtime.tool_router import (
    plan_tools,
    plan_tools_by_llm,
    plan_tools_by_rules,
)
from geoagent.tools.intent_router import IntentResult


def _intent(name: str) -> IntentResult:
    return IntentResult(intent=name, confidence=0.9, method="rules", rationale="test")


def test_rules_hospital_follow_up() -> None:
    tools = plan_tools_by_rules(
        "any hospital nearby?",
        _intent("historical_assessment"),
        active_aoi_id="maxar_031311102212",
    )
    assert tools == ["find_nearest_hospitals"]


def test_rules_briefing() -> None:
    tools = plan_tools_by_rules(
        "Summarize the damage assessment for an EOC briefing.",
        _intent("historical_assessment"),
        active_aoi_id="maxar_031311102212",
    )
    assert tools == ["query_historical"]


def test_llm_router_parses_json() -> None:
    payload = '{"tools": ["find_nearest_hospitals"], "rationale": "Hospital follow-up"}'
    with patch("geoagent.runtime.tool_router.chat", return_value=payload):
        tools = plan_tools_by_llm(
            "any hospital nearby?",
            _intent("historical_assessment"),
            active_aoi_id="maxar_031311102212",
            chat_history=[],
        )
    assert tools == ["find_nearest_hospitals"]


def test_plan_tools_falls_back_when_llm_fails() -> None:
    with patch("geoagent.runtime.tool_router.plan_tools_by_llm", side_effect=RuntimeError("boom")):
        tools = plan_tools(
            "any hospital nearby?",
            _intent("historical_assessment"),
            active_aoi_id="maxar_031311102212",
            use_llm=True,
        )
    assert tools == ["find_nearest_hospitals"]
