"""Tests for Mission Priority engine + routing."""

from __future__ import annotations

import unittest

from geoagent.runtime.tool_router import plan_tools_by_rules
from geoagent.tools.hierarchical_router import route_message
from geoagent.tools.intent_router import IntentResult
from geoagent.tools.mission_priority import (
    build_mission_priority,
    format_mission_priority_markdown,
    recommend_action,
    wants_mission_priority,
)


def _cell(
    *,
    direction: str,
    destroyed: int = 0,
    major: int = 0,
    minor: int = 0,
    total: int | None = None,
    impact: int | None = None,
) -> dict:
    buildings = total if total is not None else destroyed + major + minor + 10
    damaged = destroyed + major + minor
    score = impact if impact is not None else destroyed * 4 + major * 2 + minor
    return {
        "direction": direction,
        "buildings_total": buildings,
        "damaged_count": damaged,
        "impact_score": score,
        "by_effective_level": {
            "destroyed": destroyed,
            "major": major,
            "minor": minor,
            "no_damage": max(0, buildings - damaged),
        },
    }


class MissionPriorityEngineTests(unittest.TestCase):
    def test_recommend_sar_for_heavy_destroyed(self) -> None:
        self.assertEqual(
            recommend_action(_cell(direction="Center", destroyed=6, major=1)),
            "Immediate Search & Rescue",
        )

    def test_recommend_fire_for_major_cluster(self) -> None:
        self.assertEqual(
            recommend_action(_cell(direction="North", destroyed=0, major=6, minor=1)),
            "Fire suppression / hazard control",
        )

    def test_recommend_inspection_for_minor_dominant(self) -> None:
        self.assertEqual(
            recommend_action(_cell(direction="South", destroyed=0, major=0, minor=5)),
            "Rapid inspection",
        )

    def test_build_priority_cards_with_facilities(self) -> None:
        stats = {
            "aoi_id": "demo_aoi",
            "spatial_grid_3x3": {
                "bounds_wgs84": [-118.6, 34.0, -118.5, 34.1],
                "most_affected": [
                    _cell(direction="Northwest", destroyed=8, major=2, impact=40),
                    _cell(direction="Center", destroyed=1, major=4, impact=20),
                    _cell(direction="Southeast", destroyed=0, major=0, minor=4, impact=4),
                ],
            },
        }
        facilities = {
            "facility_kind": "all",
            "by_kind": {
                "hospital": {
                    "hospitals": [
                        {
                            "name": "Demo Hospital",
                            "coordinates_wgs84": [-118.55, 34.05],
                            "distance_km": 1.0,
                        }
                    ]
                },
                "fire_station": {
                    "facilities": [
                        {
                            "name": "Demo Fire",
                            "coordinates_wgs84": [-118.52, 34.08],
                            "distance_km": 2.0,
                        }
                    ]
                },
            },
        }
        mission = build_mission_priority(stats, facilities_payload=facilities, top_n=3)
        self.assertEqual(mission["priority_count"], 3)
        self.assertEqual(mission["priorities"][0]["direction"], "Northwest")
        self.assertEqual(mission["priorities"][0]["direction_label"], "Northwest")
        self.assertEqual(mission["priorities"][0]["recommend"], "Immediate Search & Rescue")
        self.assertIsNotNone(mission["priorities"][0]["nearest_hospital"])
        self.assertIsNotNone(mission["priorities"][0]["nearest_fire_station"])

        md = format_mission_priority_markdown(mission)
        self.assertIn("### Priority 1 — Northwest", md)
        self.assertIn("**Recommend:**", md)
        self.assertIn("Demo Hospital", md)
        self.assertIn("Demo Fire", md)


class MissionPriorityRoutingTests(unittest.TestCase):
    def test_keyword_detector(self) -> None:
        self.assertTrue(wants_mission_priority("Give me the mission priority briefing"))
        self.assertTrue(wants_mission_priority("Where should we go first?"))
        self.assertTrue(wants_mission_priority("EOC briefing for this AOI"))
        self.assertTrue(wants_mission_priority("what is the priority?"))
        self.assertFalse(wants_mission_priority("how many destroyed buildings?"))
        self.assertFalse(wants_mission_priority("Why do EOCs care about hospitals?"))

    def test_routes_to_mission_priority_tool(self) -> None:
        for q in (
            "mission priority",
            "operational priority for this AOI",
            "where should we go first",
            "what is the priority?",
            "Priority 1 areas",
            "incident command briefing",
        ):
            with self.subTest(q=q):
                route = route_message(q)
                self.assertEqual(route.l2, "mission_priority", q)
                self.assertEqual(route.tools(), ["get_mission_priority"], q)

    def test_guidance_eoc_doctrine_still_guidance(self) -> None:
        route = route_message("Why do EOCs care about hospitals as critical facilities?")
        self.assertEqual(route.l2, "guidance")
        self.assertIn("query_guidance", route.tools())
        self.assertNotIn("get_mission_priority", route.tools())

    def test_plan_tools_by_rules(self) -> None:
        intent = IntentResult(
            intent="historical_assessment",
            confidence=1.0,
            method="test",
            slots={"route": {"l1": "chat_qa", "l2": "mission_priority", "l3": "summarize"}},
        )
        tools = plan_tools_by_rules("mission priority", intent)
        self.assertEqual(tools, ["get_mission_priority"])


if __name__ == "__main__":
    unittest.main()
