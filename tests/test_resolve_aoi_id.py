"""Tests for AOI id resolution used by hospital/stats/report tools."""

from __future__ import annotations

from geoagent.runtime.memory import SessionStore
from geoagent.runtime.tools import ToolContext, _format_hospitals_markdown, _resolve_aoi_id
from geoagent.tools.intent_router import IntentResult


def _ctx(*, active: str | None, slot_aoi: str | None) -> ToolContext:
    slots = {"question": "where is the nearest hospital"}
    if slot_aoi is not None:
        slots["aoi_id"] = slot_aoi
    return ToolContext(
        question="where is the nearest hospital",
        session_store=SessionStore(),
        session_id="test",
        active_aoi_id=active,
        chat_history=[],
        intent=IntentResult(
            intent="historical_assessment",
            confidence=0.9,
            method="test",
            slots=slots,
        ),
    )


def test_rejects_from_session_placeholder() -> None:
    assert (
        _resolve_aoi_id(_ctx(active="maxar_031311103033", slot_aoi="from session"))
        == "maxar_031311103033"
    )


def test_explicit_slot_overrides_active_only_when_named_in_question() -> None:
    ctx = _ctx(active="maxar_031311103033", slot_aoi="maxar_031311102212")
    assert _resolve_aoi_id(ctx) == "maxar_031311103033"

    ctx_named = ToolContext(
        question="hospitals for maxar_031311102212",
        session_store=SessionStore(),
        session_id="test",
        active_aoi_id="maxar_031311103033",
        chat_history=[],
        intent=IntentResult(
            intent="historical_assessment",
            confidence=0.9,
            method="test",
            slots={"aoi_id": "maxar_031311102212"},
        ),
    )
    assert _resolve_aoi_id(ctx_named) == "maxar_031311102212"


def test_active_used_when_slot_missing() -> None:
    assert _resolve_aoi_id(_ctx(active="maxar_031311103033", slot_aoi=None)) == "maxar_031311103033"


def test_hospitals_markdown_includes_map_links() -> None:
    md = _format_hospitals_markdown(
        "maxar_031311103032",
        {
            "nearest": {
                "name": "Hathaway-Sycamores",
                "distance_km": 2.03,
                "distance_mi": 1.26,
                "coordinates_wgs84": [-118.144, 34.169],
                "website": "http://example.org",
            },
            "hospitals": [
                {
                    "name": "Hathaway-Sycamores",
                    "distance_km": 2.03,
                    "distance_mi": 1.26,
                    "coordinates_wgs84": [-118.144, 34.169],
                },
                {
                    "name": "Huntington Hospital",
                    "distance_km": 5.1,
                    "distance_mi": 3.17,
                    "coordinates_wgs84": [-118.15, 34.14],
                },
            ],
        },
    )
    assert "[Hathaway-Sycamores](#map-hospital?" in md
    assert "lon=-118.144000" in md
    assert "[Huntington Hospital](#map-hospital?" in md
