"""Tests for answer policy: forced tools, dual-path, layered answers."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from geoagent.runtime.answer_policy import (
    combine_layered_answers,
    enforce_required_tools,
    required_ops_tools,
)
from geoagent.tools.hierarchical_router import route_message
from geoagent.tools.knowledge_rag import (
    KnowledgeHit,
    ensure_guidance_citations,
    format_sources_markdown,
    render_knowledge_fallback,
)


class AnswerPolicyTests(unittest.TestCase):
    def test_force_stats_for_how_many(self) -> None:
        self.assertEqual(required_ops_tools("how many destroyed buildings?"), ["get_damage_stats"])
        tools = enforce_required_tools("how many destroyed buildings?", ["query_historical"])
        self.assertIn("get_damage_stats", tools)

    def test_doctrine_red_flag_does_not_force_weather(self) -> None:
        q = "What does a Red Flag Warning mean?"
        self.assertNotIn("weather_context", required_ops_tools(q))
        route = route_message(q)
        self.assertEqual(route.l2, "guidance")
        self.assertEqual(route.tools(), ["query_guidance"])

    def test_current_forecast_forces_weather(self) -> None:
        q = "What is the current weather forecast?"
        self.assertIn("weather_context", required_ops_tools(q))

    def test_damage_levels_definition_stays_guidance(self) -> None:
        q = "FEMA IA destroyed major minor affected damage levels"
        route = route_message(q)
        self.assertEqual(route.l2, "guidance")
        self.assertEqual(route.tools(), ["query_guidance"])

    def test_hybrid_stats_and_fema_levels_dual_path(self) -> None:
        q = "how many destroyed buildings and what are FEMA damage levels?"
        route = route_message(q)
        tools = route.tools()
        self.assertIn("get_damage_stats", tools)
        self.assertIn("query_guidance", tools)

    def test_layered_combine(self) -> None:
        results = [
            SimpleNamespace(tool="get_damage_stats", answer_markdown="Destroyed: 12"),
            SimpleNamespace(
                tool="query_guidance",
                answer_markdown="### Official guidance (public SOPs)\n\nDestroyed means...",
            ),
        ]
        text = combine_layered_answers(results)
        self.assertIn("### Case data (from assessment tools)", text)
        self.assertIn("Destroyed: 12", text)
        self.assertIn("Official guidance", text)
        self.assertIn("Case numbers come only from assessment tools", text)

    def test_single_case_tool_still_labeled(self) -> None:
        results = [SimpleNamespace(tool="get_damage_stats", answer_markdown="Minor: 3")]
        text = combine_layered_answers(results)
        self.assertIn("### Case data (from assessment tools)", text)
        self.assertIn("Minor: 3", text)

    def test_guidance_citations_always_appended(self) -> None:
        hits = [
            KnowledgeHit(
                text="passage",
                score=0.8,
                title="FEMA PDA Guide",
                source="FEMA",
                source_url="https://example.gov/pda",
                section="Purpose",
                doc_id="fema_pda",
            )
        ]
        answer = ensure_guidance_citations("Destroyed means total loss.", hits)
        self.assertIn("### Sources", answer)
        self.assertIn("https://example.gov/pda", answer)
        self.assertIn("FEMA PDA Guide", answer)

    def test_no_hit_message(self) -> None:
        text = render_knowledge_fallback("unknown topic", [])
        self.assertIn("could not find matching", text.casefold())
        self.assertIn("will **not** invent", text.casefold())
        self.assertEqual(format_sources_markdown([]), "")


if __name__ == "__main__":
    unittest.main()
