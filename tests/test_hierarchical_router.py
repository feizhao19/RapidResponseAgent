"""Tests for hierarchical L1→L2→L3 intent routing."""

from __future__ import annotations

import unittest

from geoagent.runtime.tool_router import plan_tools
from geoagent.tools.hierarchical_router import route_message
from geoagent.tools.intent_router import classify_intent


class HierarchicalRouterTests(unittest.TestCase):
    def test_capability_meta_route(self) -> None:
        route = route_message("can I ask more questions ?")
        self.assertEqual(route.l1, "meta")
        self.assertEqual(route.l2, "capability")
        self.assertEqual(route.l3, "inform")
        self.assertEqual(route.legacy_intent, "clarify")
        self.assertEqual(route.tools(), [])

    def test_damage_stats_count(self) -> None:
        route = route_message("how many damaged buildings?")
        self.assertEqual(route.l1, "chat_qa")
        self.assertEqual(route.l2, "damage_stats")
        self.assertEqual(route.l3, "count")
        self.assertEqual(route.tools(), ["get_damage_stats"])

    def test_hospitals_nearest(self) -> None:
        route = route_message("any hospital nearby?")
        self.assertEqual(route.l1, "chat_qa")
        self.assertEqual(route.l2, "hospitals")
        self.assertEqual(route.l3, "nearest")
        self.assertEqual(route.tools(), ["find_nearest_hospitals"])

    def test_weather_forecast(self) -> None:
        route = route_message("What's the wind forecast for Topanga?")
        self.assertEqual(route.l1, "chat_qa")
        self.assertEqual(route.l2, "weather")
        self.assertEqual(route.l3, "forecast")
        self.assertEqual(route.legacy_intent, "weather_context")

    def test_report_full(self) -> None:
        route = route_message("write a full FEMA report for this AOI")
        self.assertEqual(route.l1, "chat_qa")
        self.assertEqual(route.l2, "report")
        self.assertEqual(route.l3, "full")
        self.assertIn("generate_report", route.tools())

    def test_new_pipeline_with_quad(self) -> None:
        route = route_message("Analyze quad 031311102212")
        self.assertEqual(route.l1, "new_pipeline")
        self.assertEqual(route.l2, "pipeline_run")
        self.assertEqual(route.legacy_intent, "new_assessment")

    def test_named_aoi_with_summary_stays_chat_qa(self) -> None:
        route = route_message(
            "Summarize the damage assessment for maxar_031311102212 for an EOC briefing."
        )
        self.assertEqual(route.l1, "chat_qa")
        self.assertEqual(route.legacy_intent, "historical_assessment")
        self.assertEqual(route.slots.get("aoi_id"), "maxar_031311102212")

    def test_classify_intent_exposes_route_slots(self) -> None:
        result = classify_intent("how many destroyed buildings?", use_llm=False)
        self.assertEqual(result.intent, "historical_assessment")
        route = (result.slots or {}).get("route") or {}
        self.assertEqual(route.get("l1"), "chat_qa")
        self.assertEqual(route.get("l2"), "damage_stats")

    def test_plan_tools_uses_l2(self) -> None:
        result = classify_intent("nearest hospital please", use_llm=False)
        tools = plan_tools("nearest hospital please", result, use_llm=False)
        self.assertEqual(tools, ["find_nearest_hospitals"])


if __name__ == "__main__":
    unittest.main()
