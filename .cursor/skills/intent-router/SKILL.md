---
name: intent-router
description: Classify RapidResponseAgent user input into historical assessment, new imagery analysis, or weather advisory routes. Use when routing natural-language requests in geoagent.graph.run --ask or implementing intent classification.
---

# RapidResponseAgent Intent Router

Read `geoagent/skills/intent_router.md` for the full intent contract and JSON schema.

## When to use

- User sends natural language without `--question`, `--quad`, or `--weather`
- Implementing or debugging `geoagent.tools.intent_router`
- Adding new routing signals or slots

## Routes

| Intent | Downstream |
|--------|------------|
| `historical_assessment` | Historical RAG + numeric verifier |
| `new_assessment` | AOI pipeline (requires quad or aligned_dir) |
| `weather_context` | Open-Meteo advisory (not assessment stats) |
| `clarify` | Ask user to disambiguate |

## Session mode (web chat)

Once a conversation has entered **historical Q&A** (past assessment lookup), it **must not** route to `new_assessment` in the same session. Return `clarify` and tell the user to click **+ New chat** for uploads or new pipeline runs. Full rules live in `geoagent/skills/intent_router.md` under **Chat session modes**.

## CLI

```bash
python -m geoagent.graph.run --ask "Topanga damaged count" --intent-only
python -m geoagent.graph.run --ask "wind forecast for Topanga"
python -m geoagent.graph.run --ask "analyze quad 031311102212" --skip-preprocess --resume
```
