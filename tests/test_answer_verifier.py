"""Tests for historical answer numeric verification."""

from __future__ import annotations

import unittest

from geoagent.tools.answer_verifier import verify_answer
from geoagent.tools.historical_query import CitedFact, QueryResult, StructuredQuery


def _topanga_result() -> QueryResult:
    query = StructuredQuery(raw_text="Topanga 2025 wildfire damaged count", city="Topanga", metric="damaged_count")
    facts = [
        CitedFact("city", "Topanga", "aligned/maxar_031311102212/aoi_out/aoi_stats.json#location.city", "maxar_031311102212"),
        CitedFact("buildings_total", 593, "aligned/maxar_031311102212/aoi_out/aoi_stats.json#buildings.total", "maxar_031311102212"),
        CitedFact("buildings_official", 593, "aligned/maxar_031311102212/aoi_out/aoi_stats.json#buildings.official", "maxar_031311102212"),
        CitedFact("damaged_count", 70, "aligned/maxar_031311102212/aoi_out/aoi_stats.json#damage_summary.damaged_count", "maxar_031311102212"),
        CitedFact("damaged_pct", 11.8, "aligned/maxar_031311102212/aoi_out/aoi_stats.json#damage_summary.damaged_pct", "maxar_031311102212"),
        CitedFact("destroyed_pct", 1.18, "aligned/maxar_031311102212/aoi_out/aoi_stats.json#damage_summary.destroyed_pct", "maxar_031311102212"),
    ]
    return QueryResult(query=query, matched_aoi_ids=["maxar_031311102212"], facts=facts)


class AnswerVerifierTests(unittest.TestCase):
    def test_accepts_clean_llm_answer(self) -> None:
        result = verify_answer(
            "The Topanga 2025 wildfire damaged count is 70, which is 11.8% of 593 buildings.",
            structured_result=_topanga_result(),
        )
        self.assertTrue(result.passed)

    def test_rejects_fused_numbers_when_official_grounded(self) -> None:
        result = verify_answer(
            "The damaged count is 85, which is 12.3% of 691 buildings.",
            structured_result=_topanga_result(),
        )
        self.assertFalse(result.passed)
        self.assertTrue(any("Unsupported" in issue for issue in result.issues))
        self.assertIn("70", result.corrected_answer or "")

    def test_fallback_is_deterministic(self) -> None:
        result = verify_answer(
            "The damaged count is 999.",
            structured_result=_topanga_result(),
        )
        self.assertFalse(result.passed)
        self.assertIn("70", result.corrected_answer or "")
        self.assertNotIn("999", result.corrected_answer or "")


if __name__ == "__main__":
    unittest.main()
