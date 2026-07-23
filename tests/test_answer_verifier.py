"""Tests for historical answer numeric verification."""

from __future__ import annotations

import unittest

from geoagent.tools.answer_verifier import verify_answer
from geoagent.tools.historical_query import CitedFact, QueryResult, StructuredQuery


def _topanga_result() -> QueryResult:
    query = StructuredQuery(
        raw_text="Topanga 2025 wildfire damage breakdown",
        city="Topanga",
        metric="damage_breakdown",
    )
    facts = [
        CitedFact("city", "Topanga", "aligned/maxar_031311102212/aoi_out/aoi_stats.json#location.city", "maxar_031311102212"),
        CitedFact("buildings_total", 593, "aligned/maxar_031311102212/aoi_out/aoi_stats.json#buildings.total", "maxar_031311102212"),
        CitedFact("buildings_official", 593, "aligned/maxar_031311102212/aoi_out/aoi_stats.json#buildings.official", "maxar_031311102212"),
        CitedFact("no_damage", 523, "aligned/maxar_031311102212/aoi_out/aoi_stats.json#by_effective_level.no_damage.count", "maxar_031311102212"),
        CitedFact("minor", 40, "aligned/maxar_031311102212/aoi_out/aoi_stats.json#by_effective_level.minor.count", "maxar_031311102212"),
        CitedFact("major", 23, "aligned/maxar_031311102212/aoi_out/aoi_stats.json#by_effective_level.major.count", "maxar_031311102212"),
        CitedFact("destroyed", 7, "aligned/maxar_031311102212/aoi_out/aoi_stats.json#by_effective_level.destroyed.count", "maxar_031311102212"),
    ]
    return QueryResult(query=query, matched_aoi_ids=["maxar_031311102212"], facts=facts)


class AnswerVerifierTests(unittest.TestCase):
    def test_accepts_clean_llm_answer(self) -> None:
        result = verify_answer(
            "Topanga has 593 buildings: 523 no damage, 40 minor, 23 major, 7 destroyed.",
            structured_result=_topanga_result(),
        )
        self.assertTrue(result.passed)

    def test_rejects_fused_numbers_when_official_grounded(self) -> None:
        result = verify_answer(
            "There are 85 destroyed buildings out of 691 total.",
            structured_result=_topanga_result(),
        )
        self.assertFalse(result.passed)
        self.assertTrue(any("Unsupported" in issue for issue in result.issues))
        self.assertIn("7", result.corrected_answer or "")

    def test_fallback_is_deterministic(self) -> None:
        result = verify_answer(
            "The destroyed count is 999.",
            structured_result=_topanga_result(),
        )
        self.assertFalse(result.passed)
        self.assertIn("destroyed", (result.corrected_answer or "").lower())
        self.assertNotIn("999", result.corrected_answer or "")


if __name__ == "__main__":
    unittest.main()
