# RapidResponseAgent

Multimodal agent for post-disaster rapid response: Maxar/NOAA alignment, ViPDE damage perception, fusion, VLM discrepancy review, stats, reports, and LLM-assisted Q&A for response teams.

## How to open

Use **two terminals**, then open in your browser:

**→ http://127.0.0.1:5173**

### First-time setup

```bash
cd /path/to/RapidResponseAgent
conda activate sam
pip install -r requirements.txt
pip install -r web/requirements.txt

cp .env.example .env   # add HF_TOKEN for local Llama models
cd web/frontend && npm install && cd ../..
```

### Terminal 1 — Backend API (port 8000)

```bash
cd /path/to/RapidResponseAgent
conda activate sam
set -a && source .env && set +a
./web/run_api.sh
```

Check: `curl http://127.0.0.1:8000/api/health` → `{"status":"ok"}`

### Terminal 2 — Frontend dev server (port 5173)

```bash
cd /path/to/RapidResponseAgent/web/frontend
npm run dev
```

Vite proxies API requests to port 8000. In the chat panel, use **Report LLM** to pick **1B / 8B / 11B Vision**.

### Single-server mode (optional)

```bash
cd web/frontend && npm run build
cd ../..
./web/run_api.sh
```

Open **http://127.0.0.1:8000** (serves built frontend from `web/frontend/dist`).

More detail: **[web/README.md](web/README.md)**

## Layout

| Path | Purpose |
|------|---------|
| `geoagent/` | Agents, runtime, graph pipeline, tools, RAG |
| `geoagent/runtime/` | Session memory, tool router, planner |
| `perception/` | ViPDE model and inference |
| `web/` | FastAPI backend + React UI |
| `scripts/` | Private pipeline CLIs (not shipped in this repo) |
| `data/` | Imagery, aligned AOIs, sessions (local, not in git) |
| `.cache/` | Hugging Face / torch caches (local, not in git) |

## Environment

- Conda env **`sam`** for ViPDE + API (`./web/run_api.sh` uses `sam` if no `.venv`)
- **`HF_TOKEN`** in `.env` — accept Meta Llama licenses on Hugging Face first
- Optional: set `HF_HOME` / `TRANSFORMERS_CACHE` under `RapidResponseAgent/.cache/` so weights stay in-tree

Download Llama 3.2 11B Vision (~20 GB VRAM) via Hugging Face CLI or your private `scripts/` helpers after accepting the Meta license.

## VLM review

Footprint discrepancy arbitration and predicted-damage review run through the web UI (**VLM Building Review**) or private pipeline scripts (not included here). Pipeline flags: `skip_vlm_arbitrate=1` skips both; `skip_vlm_discrepancy=1` / `skip_vlm_damage_review=1` skip one side.