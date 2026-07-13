"""Tests for runtime tool planning."""

from __future__ import annotations

from geoagent.runtime.planner import plan_tools
from geoagent.tools.intent_router import IntentResult


def _intent(name: str) -> IntentResult:
    return IntentResult(intent=name, confidence=0.9, method="rules", rationale="test")


def test_plan_weather() -> None:
    tools = plan_tools("What is the wind forecast for Topanga?", _intent("weather_context"))
    assert tools == ["weather_context"]


def test_plan_hospitals() -> None:
    tools = plan_tools(
        "Find nearest hospitals for Topanga",
        _intent("historical_assessment"),
        active_aoi_id="maxar_031311102212",
    )
    assert tools == ["find_nearest_hospitals"]


def test_plan_briefing_prefers_historical() -> None:
    tools = plan_tools(
        f"Summarize the damage assessment for maxar_031311102212 for an EOC briefing.",
        _intent("historical_assessment"),
        active_aoi_id="maxar_031311102212",
    )
    assert tools == ["query_historical"]


def test_plan_report_with_stats() -> None:
    tools = plan_tools(
        "How many damaged buildings and generate full report?",
        _intent("historical_assessment"),
        active_aoi_id="maxar_031311102212",
    )
    assert "generate_report" in tools
    assert "get_damage_stats" in tools


def test_plan_stats_without_aoi() -> None:
    tools = plan_tools("Topanga damaged count", _intent("historical_assessment"))
    assert tools == ["get_damage_stats"]


def test_plan_new_assessment_empty() -> None:
    tools = plan_tools("Run a new assessment", _intent("new_assessment"))
    assert tools == []
