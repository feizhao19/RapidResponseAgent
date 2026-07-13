# RapidResponseAgent Web UI

Interactive web interface: multi-turn chat with server sessions, AOI map, assessment reports, hospital lookup, image upload jobs, and selectable local Llama models.

## Stack

- **Backend:** FastAPI (`web/api/`) — agent runtime, sessions, assessment jobs
- **Frontend:** Vite + React + Leaflet (`web/frontend/`)

## Prerequisites

- Conda env **`sam`** (or `.venv`) with `pip install -r requirements.txt` and `pip install -r web/requirements.txt`
- **ViPDE:** `segment_anything` in `sam` (see `perception/README.md`)
- **Node.js** 18+
- **`.env`:** copy `.env.example` → `.env`, set `HF_TOKEN`

## How to open (development)

**Two terminals** → browser **http://127.0.0.1:5173**

### Terminal 1 — API

```bash
cd /path/to/RapidResponseAgent
conda activate sam
set -a && source .env && set +a
source scripts/project_env.sh
./web/run_api.sh
```

- Listens on **http://127.0.0.1:8000**
- Loads `.env` + `project_env.sh` automatically
- Uses `.venv` if present, otherwise conda **`sam`**
- Auto-detects `VIPDE_PYTHON` for upload pipeline jobs

Other port:

```bash
PORT=8001 ./web/run_api.sh
```

### Terminal 2 — Frontend

```bash
cd /path/to/RapidResponseAgent/web/frontend
npm install    # first time only
npm run dev
```

Dev UI: **http://127.0.0.1:5173**

### Verify

```bash
curl -s http://127.0.0.1:8000/api/health
curl -s http://127.0.0.1:8000/api/aois | head
```

## Production-style (one server)

```bash
cd /path/to/RapidResponseAgent/web/frontend && npm install && npm run build
cd /path/to/RapidResponseAgent
./web/run_api.sh
```

Open **http://127.0.0.1:8000**

## LLM models

Weights load from `RapidResponseAgent/.cache/huggingface/hub/` when `project_env.sh` is sourced.

| UI label | Model |
|----------|--------|
| Llama 3.2 1B (fast) | `meta-llama/Llama-3.2-1B-Instruct` |
| Llama 3.1 8B (quality) | `meta-llama/Meta-Llama-3.1-8B-Instruct` |
| Llama 3.2 11B Vision | `meta-llama/Llama-3.2-11B-Vision-Instruct` (text mode, ~20 GB VRAM) |

Download 11B Vision:

```bash
source scripts/project_env.sh
set -a && source .env && set +a
CLEAN=0 bash scripts/download_hf_model.sh meta-llama/Llama-3.2-11B-Vision-Instruct
```

Verify GPU load:

```bash
python scripts/verify_llm_gpu.py --model 11b
```

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/aois` | List indexed AOIs |
| GET | `/api/aois/{aoi_id}` | AOI detail, stats, report, hospitals |
| DELETE | `/api/aois/{aoi_id}` | Remove past assessment |
| GET | `/api/aois/{aoi_id}/buildings` | Building footprints (GeoJSON) |
| GET | `/api/data/{path}` | Static artifacts (PNG, JSON) |
| POST | `/api/ask` | Chat / agent turn (`model`, `session_id` optional) |
| POST | `/api/sessions` | Create server-side chat session |
| GET | `/api/sessions/{id}` | Load session + messages |
| POST | `/api/assessments/upload` | Upload pre/post GeoTIFFs, start job |
| GET | `/api/assessments/jobs/{job_id}` | Poll upload job status |

### Example

```bash
curl -s -X POST http://127.0.0.1:8000/api/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"Altadena damaged building count","use_llm":true,"model":"meta-llama/Llama-3.2-1B-Instruct"}'
```
