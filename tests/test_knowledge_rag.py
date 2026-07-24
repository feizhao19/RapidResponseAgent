"""Tests for public SOP knowledge RAG (Chroma)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from geoagent.runtime.tool_router import plan_tools
from geoagent.tools.hierarchical_router import route_message
from geoagent.tools.intent_router import classify_intent
from geoagent.tools.knowledge_rag import (
    build_knowledge_index,
    iter_sop_documents,
    retrieve_knowledge,
)


class KnowledgeRagTests(unittest.TestCase):
    def test_seed_corpus_exists(self) -> None:
        docs = iter_sop_documents()
        self.assertGreaterEqual(len(docs), 3)
        self.assertTrue(any(doc["source_url"] for doc in docs))

    def test_guidance_route(self) -> None:
        for question in (
            "What is FEMA FMAG guidance for wildfires?",
            "Any SOP about wildfire evacuation planning?",
            "Explain Public Assistance debris removal PPDR policy",
        ):
            with self.subTest(question=question):
                route = route_message(question)
                self.assertEqual(route.l2, "guidance")
                self.assertEqual(route.tools(), ["query_guidance"])
                self.assertEqual(route.legacy_intent, "knowledge_guidance")
                intent = classify_intent(question, use_llm=False)
                self.assertEqual(plan_tools(question, intent, use_llm=False), ["query_guidance"])

    def test_chroma_retrieve(self) -> None:
        try:
            import chromadb  # noqa: F401
        except ImportError:
            self.skipTest("chromadb not installed")

        import os

        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

        from geoagent.tools.knowledge_rag import DEFAULT_CHROMA_DIR, collection_is_ready

        # Prefer the project index (already built) to avoid HF download flakiness in CI.
        if collection_is_ready(DEFAULT_CHROMA_DIR):
            hits = retrieve_knowledge(
                "What is an FMAG declaration for wildfire response?",
                persist_dir=DEFAULT_CHROMA_DIR,
                top_k=3,
            )
        else:
            with tempfile.TemporaryDirectory() as tmp:
                persist = Path(tmp) / "chroma"
                summary = build_knowledge_index(persist_dir=persist, reset=True)
                self.assertGreater(summary["chunk_count"], 0)
                hits = retrieve_knowledge(
                    "What is an FMAG declaration for wildfire response?",
                    persist_dir=persist,
                    top_k=3,
                )
        self.assertGreaterEqual(len(hits), 1)
        blob = " ".join(hit.text.casefold() for hit in hits)
        self.assertTrue("fmag" in blob or "fire management" in blob)


if __name__ == "__main__":
    unittest.main()
