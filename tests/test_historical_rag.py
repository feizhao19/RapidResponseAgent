"""RAG retrieval tests for historical assessment artifacts."""

from __future__ import annotations

import unittest
from pathlib import Path

from geoagent.tools.historical_index import DATA
from geoagent.tools.historical_rag import build_rag_chunks, retrieve_chunks, write_rag_index
from geoagent.tools.historical_rag_answer import answer_with_rag

PILOT_STATS = DATA / "aligned/maxar_031311102212/aoi_out/aoi_stats.json"


@unittest.skipUnless(PILOT_STATS.is_file(), "pilot assessment artifacts not present")
class HistoricalRAGTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        write_rag_index(data_root=DATA)

    def test_builds_multiple_chunks(self) -> None:
        chunks = build_rag_chunks(data_root=DATA)
        self.assertGreaterEqual(len(chunks), 4)
        sections = {chunk.section for chunk in chunks}
        self.assertIn("Executive Summary", sections)

    def test_retrieves_topanga_damage_context(self) -> None:
        hits = retrieve_chunks(
            "Topanga 2025 wildfire damaged count",
            top_k=3,
            aoi_ids=["maxar_031311102212"],
        )
        self.assertGreaterEqual(len(hits), 1)
        joined = "\n".join(hit["text"] for hit in hits)
        self.assertIn("85", joined)
        self.assertIn("Topanga", joined)

    def test_retrieve_only_answer(self) -> None:
        result = answer_with_rag(
            "Topanga 2025 wildfire damaged count",
            use_llm=False,
            retrieve_only=True,
            top_k=3,
        )
        self.assertFalse(result.used_llm)
        self.assertIn("Retrieval Preview", result.answer_markdown)

    def test_structured_answer_without_llm(self) -> None:
        result = answer_with_rag(
            "Topanga 2025 wildfire damaged count",
            use_llm=False,
            retrieve_only=False,
            top_k=3,
        )
        self.assertFalse(result.used_llm)
        self.assertIn("85", result.answer_markdown)
        self.assertIn("Historical Assessment Answer", result.answer_markdown)
        self.assertGreaterEqual(len(result.retrieved_chunks), 1)


if __name__ == "__main__":
    unittest.main()
