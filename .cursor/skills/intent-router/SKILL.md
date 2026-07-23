---
name: intent-router
description: Classify RapidResponseAgent user input with hierarchical L1/L2/L3 routing (session mode → capability → action). Use when routing natural-language requests in geoagent.graph.run --ask or implementing intent classification.
---

# RapidResponseAgent Intent Router

Read `geoagent/skills/intent_router.md` for the full layer contract.

Implementation: `geoagent/tools/hierarchical_router.py` (rules-first). Legacy flat intents are derived for API compatibility via `geoagent/tools/intent_router.py`. Web turns execute on `geoagent/graph/chat_graph.py`.

**Unit of work:** one imagery AOI = one past assessment (no event-level rollups).

## When to use

- User sends natural language without `--question`, `--quad`, or `--weather`
- Implementing or debugging hierarchical routing
- Adding new L2 domains or L3 actions

## Layers

| Layer | Values |
|-------|--------|
| L1 | `meta`, `chat_qa`, `new_pipeline` |
| L2 | `capability`, `damage_stats`, `hospitals`, `weather`, `report`, `assessment_overview`, `pipeline_run`, `none` |
| L3 | `inform`, `count`, `list`, `nearest`, `forecast`, `summarize`, `full`, `start`, `status`, `general` |

## Session mode (web chat)

Once a conversation has entered **historical Q&A**, do **not** route to `new_pipeline` in the same session. Return meta/clarify and tell the user to click **+ New chat**.

## CLI

```bash
python -m geoagent.graph.run --ask "Topanga damaged count" --intent-only
python -m geoagent.graph.run --ask "What is the wind forecast for Topanga?"
python -m geoagent.graph.run --ask "Analyze quad 031311102212" --skip-preprocess --resume
```
