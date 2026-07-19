# Scripts

Pipeline and agent CLI scripts (`align_pre_post.py`, VLM arbitration helpers, HF download helpers, etc.) are **not included** in this repository by default.

The web UI and `perception` docs/configs are the supported public surface. The `geoagent/` package and full offline pipelines are **available by request** from the author (see the root README License contact).

## VLM preference → DPO (Visual Verifier)

After collecting **Agree / Reject** feedback in **VLM Building Review**:

```bash
# One-shot: backfill ensemble pools → export DPO JSONL
python scripts/run_vlm_dpo_pipeline.py --export-only

# Full train on a CUDA machine (writes data/vlm_dpo/runs/latest/adapter)
pip install -r requirements-dpo.txt
python scripts/run_vlm_dpo_pipeline.py --train

# Point VLM review inference at the adapter, then restart the API
export VLM_DPO_ADAPTER=/path/to/RapidResponseAgent/data/vlm_dpo/runs/latest/adapter
```

Manual steps (equivalent):

```bash
python scripts/backfill_vlm_preference_pools.py
python scripts/export_vlm_dpo_dataset.py --output data/vlm_dpo/dpo_pairs.jsonl
python scripts/train_vlm_dpo.py --dry-run --dataset data/vlm_dpo/dpo_pairs.jsonl
python scripts/train_vlm_dpo.py --dataset data/vlm_dpo/dpo_pairs.jsonl
```

Preference source: `data/vlm_preferences/{aoi_id}.jsonl`  
Shared helpers: `web/api/vlm_dpo_dataset.py`, `web/api/vlm_preferences.py`  
Inference hook: `geoagent.tools.llm_client` loads `VLM_DPO_ADAPTER` (or `VISUAL_VERIFIER_ADAPTER`) automatically.

Each Agree/Reject labels all ensemble augmentation views against the preferred
recommendation and always seeds the opposite pool with the forced counterfactual,
then export expands `accept_responses × reject_responses` into DPO pairs.
