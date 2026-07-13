# RapidResponseAgent

**RapidResponseAgent** is a multimodal agent for **post-disaster rapid response**. It turns pre/post remote-sensing imagery into building-level damage assessments, then answers operational questions in a map-centric chat UI—stats, nearest hospitals, weather context, historical cases, and written reports.

Built for emergency operations, research partners, and field analysts who need a fast path from imagery to actionable situational awareness.

### Demo

[![RapidResponseAgent demo](https://img.youtube.com/vi/lIQxRoqIp14/maxresdefault.jpg)](https://www.youtube.com/watch?v=lIQxRoqIp14)

Watch the walkthrough: **[YouTube — RapidResponseAgent demo](https://www.youtube.com/watch?v=lIQxRoqIp14)**

> **Early release:** not everything from the full system is published yet (notably ViPDE internals, weights, and pipeline `scripts/`). We plan to **release remaining pieces gradually**—see [Release status](#release-status).

---

## What it does

| Capability | Description |
|------------|-------------|
| **Damage assessment** | Align pre/post imagery → run **ViPDE** pixel damage perception → fuse with official building footprints (LARIAC) |
| **VLM review** | Llama Vision double-checks footprint mismatches and “destroyed” labels with pre/post chips |
| **Map + panels** | Leaflet map with imagery overlays, damage polygons, hospitals, region stats, and assessment report |
| **Grounded chat** | Multi-turn Q&A scoped to the active AOI: damage stats, hospitals, weather, historical RAG, report generation |
| **New assessments** | Upload post (and optional pre) GeoTIFF, or auto-match pre from a local Maxar catalog, and run the full pipeline |

Demo geography centers on **Los Angeles wildfires (Jan 2025)** Maxar/NOAA cases (e.g. Altadena / Topanga-area quads such as `maxar_031311103033`).

---

## How it works

```text
Imagery (Maxar pre + NOAA post, or upload)
        │
        ▼
┌─────────────────── Assessment pipeline (LangGraph) ───────────────────┐
│  preprocess → location → ViPDE perception → footprint fusion          │
│       → VLM arbitrate / damage review → stats → hospitals             │
│       → report ∥ map visualization → finalize (indexes)               │
└───────────────────────────────────────────────────────────────────────┘
        │
        ▼
Chat agent (intent router + tools)  ←→  Web UI (map, stats, report, VLM)
```

**Chat tools:** `get_damage_stats`, `find_nearest_hospitals`, `weather_context`, `query_historical`, `generate_report`.

**Intents:** `new_assessment` | `historical_assessment` | `weather_context` | `clarify`.

---

## Repository layout

| Path | Role |
|------|------|
| `geoagent/` | Agents, LangGraph AOI pipeline, runtime (memory / planner / tool router), skills, tools |
| `perception/` | ViPDE inference entrypoints, configs, docs; proprietary package lives under `vipde/` (local only) |
| `web/` | FastAPI backend + React / Vite / Leaflet UI |
| `scripts/` | Offline pipeline CLIs (align, fusion, VLM, reports, model download) — may be omitted in some distributions |
| `data/` | Local imagery, aligned AOIs, sessions, indexes (not in git) |
| `.cache/` | Hugging Face / torch caches (not in git) |

---

## Stack

| Layer | Choices |
|-------|---------|
| Perception | **ViPDE** (SAM / ViT-B), PyTorch, CUDA |
| Fusion / GIS | rasterio, geopandas, LARIAC footprints |
| Orchestration | LangGraph + LangChain |
| LLMs | Local Llama 3.2 **1B** / Llama 3.1 **8B** / Llama 3.2 **11B Vision** (Hugging Face) |
| RAG | sentence-transformers over assessment artifacts |
| Backend | FastAPI |
| Frontend | React 18, TypeScript, Vite, Leaflet |
| External | OpenStreetMap Overpass (hospitals), weather APIs, Maxar ARD + NOAA ERI imagery |

---

## Quick start (Web UI)

Use **two terminals**, then open **http://127.0.0.1:5173**.

### First-time setup

```bash
cd /path/to/RapidResponseAgent
conda activate sam
pip install -r requirements.txt
pip install -r web/requirements.txt

cp .env.example .env   # set HF_TOKEN (accept Meta Llama licenses on Hugging Face)
cd web/frontend && npm install && cd ../..
```

ViPDE weights and the proprietary `perception/vipde` package must be installed locally (see [`perception/README.md`](perception/README.md)). They are **not** shipped in git.

### Terminal 1 — API (port 8000)

```bash
cd /path/to/RapidResponseAgent
conda activate sam
set -a && source .env && set +a
# Optional if present: source scripts/project_env.sh   # keeps HF weights under ./.cache
./web/run_api.sh
```

Health check: `curl http://127.0.0.1:8000/api/health` → `{"status":"ok"}`

### Terminal 2 — Frontend (port 5173)

```bash
cd /path/to/RapidResponseAgent/web/frontend
npm run dev
```

In chat, use **Report LLM** to pick **1B / 8B / 11B Vision**.

### Single-server mode (optional)

```bash
cd web/frontend && npm run build
cd ../..
./web/run_api.sh
```

Open **http://127.0.0.1:8000** (serves `web/frontend/dist`).

More detail: [`web/README.md`](web/README.md).

---

## Typical UI workflow

1. Start a chat session and select an indexed AOI (or upload imagery for a **new assessment**).
2. Wait for the pipeline job (`aligning` → `running` → `completed`).
3. Explore the map: pre/post imagery, building polygons by damage class, hospitals.
4. Open **stats / report / VLM Building Review** panels; optionally re-run footprint or damage VLM review.
5. Ask grounded questions, e.g. damage counts for the active AOI, nearest hospitals, weather outlook, or a comparison to a past case.

---

## VLM building review

After fusion, Llama 3.2 Vision can review:

- **Footprint discrepancies** — e.g. ViPDE blobs outside LARIAC (`fp_orphan`) or footprints with little ViPDE signal (`fn_inferred`)
- **Predicted damage** — pre + post chips for buildings labeled `destroyed`, recommending `damaged` / `not_damaged`

Reviews use an augmented-view ensemble (rotations + flips), majority vote, then a short rationale. Prefer the **web UI** controls on an existing AOI; offline CLIs live under `scripts/` when that directory is included in your checkout.

Pipeline skip flags: `skip_vlm_arbitrate=1`, `skip_vlm_discrepancy=1`, `skip_vlm_damage_review=1`.

---

## Models & environment

| UI label | Hugging Face id |
|----------|-----------------|
| Llama 3.2 1B (fast) | `meta-llama/Llama-3.2-1B-Instruct` |
| Llama 3.1 8B (quality) | `meta-llama/Meta-Llama-3.1-8B-Instruct` |
| Llama 3.2 11B Vision | `meta-llama/Llama-3.2-11B-Vision-Instruct` (~20 GB VRAM) |

- Conda env **`sam`** for ViPDE + API (`./web/run_api.sh` uses `sam` if no `.venv`)
- Put **`HF_TOKEN`** in `.env` after accepting Meta licenses
- Prefer caching weights under `RapidResponseAgent/.cache/` (via `scripts/project_env.sh` or `HF_HOME`)

---

## Release status

This repository is an **early, partial release**. Several components that power a full local deployment are **not published yet** and will be opened **gradually** in later releases:

| Item | Current status |
|------|----------------|
| **ViPDE package source** (`perception/vipde/models`, `utils`) | Not released; placeholder only in git |
| **ViPDE weights** (`perception/checkpoints/`) | Not redistributed; access by request |
| **Pipeline scripts** (`scripts/`) | Not included in this checkout yet |
| **Local data / caches** (`data/`, `.cache/`, `.env`) | Never committed (machine-local) |

What *is* here today focuses on the agent orchestration, web UI, and documentation so collaborators can understand the system and follow the [demo](https://www.youtube.com/watch?v=lIQxRoqIp14). Expect more surface area (scripts, packaging, and—where licensing allows—perception artifacts) in upcoming releases.

Academic / government / humanitarian use of ViPDE packaging is described under [`perception/LICENSE`](perception/LICENSE). Commercial and operational rights are reserved — see [`perception/COMMERCIAL_LICENSING.md`](perception/COMMERCIAL_LICENSING.md).

---

## License notes

- Agent orchestration and web UI: see repository terms / project LICENSE where provided.
- **ViPDE** model code and weights: separate proprietary terms; do not assume open redistribution from a clone alone.
