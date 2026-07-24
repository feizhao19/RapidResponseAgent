"""20 debug cases: tool vs RAG routing, forced tools, dual-path, citations, layering.

Run:
  PYTHONPATH=. python -m unittest tests.test_tool_rag_debug -v
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from geoagent.runtime.answer_policy import (
    combine_layered_answers,
    enforce_required_tools,
    required_ops_tools,
    wants_case_data_supplement,
    wants_guidance_supplement,
)
from geoagent.runtime.planner import combine_tool_answers
from geoagent.runtime.tool_router import plan_tools
from geoagent.tools.hierarchical_router import route_message
from geoagent.tools.intent_router import classify_intent
from geoagent.tools.knowledge_rag import (
    KnowledgeHit,
    ensure_guidance_citations,
    format_sources_markdown,
    render_knowledge_fallback,
)


def _hit(**kwargs: object) -> KnowledgeHit:
    defaults = dict(
        text="passage text",
        score=0.75,
        title="Doc",
        source="FEMA",
        source_url="https://example.gov/doc",
        section="Overview",
        doc_id="doc1",
    )
    defaults.update(kwargs)
    return KnowledgeHit(**defaults)  # type: ignore[arg-type]


class ToolRagDebugSuite(unittest.TestCase):
    """Exactly 20 cases used to debug tool / RAG balance."""

    # --- 01–08: L2 routing ---

    def test_01_destroyed_count_routes_to_stats(self) -> None:
        route = route_message("how many destroyed buildings?")
        self.assertEqual(route.l2, "damage_stats")
        self.assertEqual(route.tools(), ["get_damage_stats"])

    def test_02_nearest_hospital_routes_to_hospitals(self) -> None:
        route = route_message("where is the nearest hospital?")
        self.assertEqual(route.l2, "hospitals")
        self.assertEqual(route.tools(), ["find_nearest_hospitals"])

    def test_03_weather_conditions_not_hospitals(self) -> None:
        """Regression: substring 'er' inside 'weather' must not hit ER/hospitals."""
        route = route_message("can you give me the current weather conditions?")
        self.assertEqual(route.l2, "weather")
        self.assertEqual(route.tools(), ["weather_context"])

    def test_04_red_flag_meaning_is_guidance_not_weather(self) -> None:
        route = route_message("What does a Red Flag Warning mean?")
        self.assertEqual(route.l2, "guidance")
        self.assertEqual(route.tools(), ["query_guidance"])
        self.assertNotIn("weather_context", route.tools())

    def test_05_live_forecast_is_weather(self) -> None:
        route = route_message("What is the current weather forecast for Topanga?")
        self.assertEqual(route.l2, "weather")
        self.assertIn("weather_context", route.tools())

    def test_06_fema_damage_levels_is_guidance(self) -> None:
        route = route_message("FEMA IA destroyed major minor affected damage levels")
        self.assertEqual(route.l2, "guidance")
        self.assertEqual(route.tools(), ["query_guidance"])

    def test_07_critical_facilities_beats_hospitals_keyword(self) -> None:
        route = route_message("Why do EOCs care about hospitals as critical facilities?")
        self.assertEqual(route.l2, "guidance")
        self.assertIn("query_guidance", route.tools())
        self.assertNotIn("find_nearest_hospitals", route.tools())

    def test_08_nims_ics_is_guidance(self) -> None:
        route = route_message("What is NIMS ICS and how should EOC use damage maps?")
        self.assertEqual(route.l2, "guidance")
        self.assertIn("query_guidance", route.tools())

    # --- 09–12: forced-tool policy ---

    def test_09_force_stats_when_planner_drifts_to_historical(self) -> None:
        tools = enforce_required_tools("how many destroyed buildings?", ["query_historical"])
        self.assertIn("get_damage_stats", tools)

    def test_10_force_weather_for_current_forecast(self) -> None:
        self.assertIn(
            "weather_context",
            required_ops_tools("What is the current weather forecast?"),
        )

    def test_11_doctrine_does_not_force_weather(self) -> None:
        self.assertNotIn(
            "weather_context",
            required_ops_tools("What does a Red Flag Warning mean?"),
        )

    def test_12_l2_weather_always_includes_weather_tool(self) -> None:
        tools = enforce_required_tools("wind?", [], route_l2="weather")
        self.assertEqual(tools[0], "weather_context")

    # --- 13–15: dual-path hybrid ---

    def test_13_hybrid_count_plus_fema_levels(self) -> None:
        q = "how many destroyed buildings and what are FEMA damage levels?"
        tools = route_message(q).tools()
        self.assertIn("get_damage_stats", tools)
        self.assertIn("query_guidance", tools)
        self.assertTrue(wants_guidance_supplement(q))
        self.assertTrue(wants_case_data_supplement(q))

    def test_14_public_messaging_is_guidance(self) -> None:
        route = route_message("How should we message preliminary damage maps publicly?")
        self.assertEqual(route.l2, "guidance")
        self.assertIn("query_guidance", route.tools())

    def test_15_final_report_includes_generate_report(self) -> None:
        route = route_message("can you give me the final report")
        self.assertEqual(route.l2, "report")
        self.assertIn("generate_report", route.tools())

    # --- 16–17: plan_tools + intent integration ---

    def test_16_plan_tools_matches_hospital_route(self) -> None:
        q = "nearest hospital please"
        intent = classify_intent(q, use_llm=False)
        tools = plan_tools(q, intent, use_llm=False)
        self.assertEqual(tools, ["find_nearest_hospitals"])

    def test_17_plan_tools_guidance_for_fmag(self) -> None:
        q = "What is FEMA FMAG guidance?"
        intent = classify_intent(q, use_llm=False)
        tools = plan_tools(q, intent, use_llm=False)
        self.assertIn("query_guidance", tools)
        self.assertNotIn("get_damage_stats", tools)

    # --- 18–20: citations + layered answers ---

    def test_18_citations_always_appended_and_replace_llm_sources(self) -> None:
        hits = [
            _hit(
                title="FEMA PDA Guide",
                section="Purpose",
                source_url="https://example.gov/pda",
            )
        ]
        messy = "Destroyed means total loss.\n\n### Sources\n1. made-up"
        out = ensure_guidance_citations(messy, hits)
        self.assertIn("### Sources", out)
        self.assertIn("https://example.gov/pda", out)
        self.assertIn("FEMA PDA Guide", out)
        self.assertNotIn("made-up", out)

    def test_19_no_hit_refuses_to_invent_policy(self) -> None:
        text = render_knowledge_fallback("totally unknown xyz policy", [])
        low = text.casefold()
        self.assertIn("could not find matching", low)
        self.assertIn("will **not** invent", low)
        self.assertEqual(format_sources_markdown([]), "")

    def test_20_layered_answer_separates_case_and_guidance(self) -> None:
        results = [
            SimpleNamespace(tool="get_damage_stats", answer_markdown="Destroyed: 12"),
            SimpleNamespace(
                tool="query_guidance",
                answer_markdown="Destroyed means total loss of the structure.",
            ),
        ]
        text = combine_tool_answers(results)
        # Same path chat_graph uses.
        self.assertEqual(text, combine_layered_answers(results))
        self.assertIn("### Case data (from assessment tools)", text)
        self.assertIn("Destroyed: 12", text)
        self.assertIn("### Official guidance (public SOPs)", text)
        self.assertIn("Destroyed means total loss", text)
        self.assertIn("Case numbers come only from assessment tools", text)
        # Case section must appear before guidance section.
        self.assertLess(
            text.index("### Case data"),
            text.index("### Official guidance"),
        )


class ToolRagDebugSuiteExtra(unittest.TestCase):
    """Follow-up regressions found in live chat debug."""

    def test_21_response_process_routes_to_guidance(self) -> None:
        for q in (
            "tell me the response process",
            "what is the response process",
            "tell me the emergency response process",
        ):
            with self.subTest(q=q):
                route = route_message(q)
                self.assertEqual(route.l2, "guidance", msg=route.rationale)
                self.assertEqual(route.tools(), ["query_guidance"])

    def test_21b_mitigate_disaster_effects_routes_to_guidance(self) -> None:
        for q in (
            "I mean how to mitigate the disaster effects",
            "how to mitigate the disaster effects",
            "how can we mitigate wildfire impacts",
            "mitigation measures for this wildfire",
            "how to reduce disaster effects",
        ):
            with self.subTest(q=q):
                route = route_message(q)
                self.assertEqual(route.l2, "guidance", msg=f"{q} -> {route.rationale}")
                self.assertIn("query_guidance", route.tools())
                self.assertNotIn("query_historical", route.tools())

    def test_22_verifier_does_not_dump_stats_for_process_question(self) -> None:
        from geoagent.tools.answer_verifier import verify_answer
        from geoagent.tools.historical_query import CitedFact, QueryResult, StructuredQuery

        structured = QueryResult(
            query=StructuredQuery(raw_text="tell me the response process"),
            matched_aoi_ids=["upload_abc"],
            facts=[
                CitedFact("destroyed", 1050, "aoi_stats.json#destroyed", "upload_abc"),
                CitedFact("no_damage", 626, "aoi_stats.json#no_damage", "upload_abc"),
            ],
            notes=[],
        )
        draft = "The ICS response process has 5 phases and mobilized 1200 personnel."
        result = verify_answer(
            draft,
            structured_result=structured,
            question="tell me the response process",
        )
        self.assertFalse(result.passed)
        self.assertTrue(result.used_fallback)
        self.assertIsNotNone(result.corrected_answer)
        assert result.corrected_answer is not None
        self.assertNotIn("verified damage classes", result.corrected_answer.casefold())
        self.assertNotIn("1050", result.corrected_answer)
        self.assertIn("SOP guidance", result.corrected_answer)

    def test_23_verifier_still_dumps_stats_for_damage_questions(self) -> None:
        from geoagent.tools.answer_verifier import verify_answer
        from geoagent.tools.historical_query import CitedFact, QueryResult, StructuredQuery

        structured = QueryResult(
            query=StructuredQuery(raw_text="how many destroyed?"),
            matched_aoi_ids=["upload_abc"],
            facts=[
                CitedFact("destroyed", 1050, "aoi_stats.json#destroyed", "upload_abc"),
                CitedFact("city", "Los Angeles", "aoi_stats.json#city", "upload_abc"),
                CitedFact("event", "la_wildfires", "aoi_stats.json#event", "upload_abc"),
            ],
            notes=[],
        )
        draft = "There were 9999 destroyed buildings."  # unsupported number
        result = verify_answer(
            draft,
            structured_result=structured,
            question="how many destroyed buildings?",
        )
        self.assertFalse(result.passed)
        assert result.corrected_answer is not None
        self.assertIn("1050", result.corrected_answer)

    def test_24_ambiguous_question_clarifies_not_historical(self) -> None:
        from geoagent.tools.intent_router import classify_intent

        for q in (
            "tell me something useful",
            "what should we do next?",
            "any thoughts?",
        ):
            with self.subTest(q=q):
                route = route_message(q)
                self.assertEqual(route.l1, "meta", msg=route.rationale)
                self.assertEqual(route.legacy_intent, "clarify")
                self.assertIn("not sure which answer", (route.clarification or "").lower())
                intent = classify_intent(q, use_llm=False)
                self.assertEqual(intent.intent, "clarify")
                self.assertEqual(route.tools(), [])

    def test_25_which_area_handled_first_is_spatial_stats(self) -> None:
        history = [
            {"role": "user", "content": "how many destroyed buildings?"},
            {"role": "assistant", "content": "Destroyed: 1050"},
        ]
        for q in (
            "which area should be handled first?",
            "which areas should be handled first?",
            "where should we respond first?",
            "哪个区域应该先处理？",
            "先处理哪个区域",
        ):
            with self.subTest(q=q):
                route = route_message(q, chat_history=history)
                self.assertEqual(route.l1, "chat_qa", msg=route.rationale)
                self.assertEqual(route.l2, "damage_stats", msg=route.rationale)
                self.assertEqual(route.tools(), ["get_damage_stats"])
                self.assertNotIn("New chat", route.clarification or "")


if __name__ == "__main__":
    unittest.main()
