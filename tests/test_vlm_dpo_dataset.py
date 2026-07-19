"""Tests for VLM preference → DPO dataset export."""

from __future__ import annotations

import json
from pathlib import Path

from web.api.vlm_dpo_dataset import (
    export_dpo_dataset,
    judgment_to_assistant_text,
    preference_to_dpo_row,
    preference_to_dpo_rows,
    row_to_trl_vision_sample,
)


def test_judgment_to_assistant_text_discrepancy():
    text = judgment_to_assistant_text(
        {
            "short_description": "roof",
            "rationale": "edges",
            "building_present": True,
            "recommendation": "accept_as_building",
        },
        review_type="discrepancy",
    )
    payload = json.loads(text)
    assert payload["building_present"] is True
    assert payload["recommendation"] == "accept_as_building"


def test_preference_to_dpo_row_requires_chips(tmp_path: Path):
    pre = tmp_path / "aligned" / "demo" / "buildings_out" / "chips_vlm"
    pre.mkdir(parents=True)
    chip = pre / "DET_1_pre.jpg"
    chip.write_bytes(b"fake")

    record = {
        "type": "vlm_dpo_preference",
        "aoi_id": "demo",
        "feature_id": "DET_1",
        "review_type": "discrepancy",
        "decision": "disagree",
        "kind": "fp_orphan",
        "pre_chip": "buildings_out/chips_vlm/DET_1_pre.jpg",
        "created_at": "2026-01-01T00:00:00+00:00",
        "chosen": {
            "short_description": "not building",
            "rationale": "pavement",
            "building_present": False,
            "recommendation": "reject_as_building",
        },
        "rejected": {
            "short_description": "building",
            "rationale": "roof",
            "building_present": True,
            "recommendation": "accept_as_building",
        },
    }
    row = preference_to_dpo_row(record, data_root=tmp_path)
    assert row is not None
    assert row["review_type"] == "discrepancy"
    assert Path(row["images"][0]).name == "DET_1_pre.jpg"
    assert "reject_as_building" in row["chosen"]
    assert "accept_as_building" in row["rejected"]


def test_export_dpo_dataset(tmp_path: Path):
    prefs = tmp_path / "vlm_preferences"
    prefs.mkdir()
    pre = tmp_path / "aligned" / "demo" / "buildings_out" / "chips_vlm"
    pre.mkdir(parents=True)
    chip = pre / "DET_1_pre.jpg"
    chip.write_bytes(b"fake")

    record = {
        "type": "vlm_dpo_preference",
        "aoi_id": "demo",
        "feature_id": "DET_1",
        "review_type": "discrepancy",
        "decision": "agree",
        "pre_chip": "buildings_out/chips_vlm/DET_1_pre.jpg",
        "created_at": "2026-01-01T00:00:00+00:00",
        "chosen": {
            "short_description": "building",
            "rationale": "roof",
            "building_present": True,
            "recommendation": "accept_as_building",
        },
        "rejected": {
            "short_description": "not building",
            "rationale": "pavement",
            "building_present": False,
            "recommendation": "reject_as_building",
        },
    }
    (prefs / "demo.jsonl").write_text(json.dumps(record) + "\n")
    out = tmp_path / "dpo_pairs.jsonl"
    summary = export_dpo_dataset(preference_dir=prefs, output_path=out, data_root=tmp_path)
    assert summary["n_exported"] == 1
    assert out.is_file()
    exported = json.loads(out.read_text().splitlines()[0])
    assert exported["chosen_recommendation"] == "accept_as_building"


def test_row_to_trl_vision_sample_has_image_placeholders(tmp_path: Path):
    chip = tmp_path / "chip.jpg"
    # Minimal valid JPEG headerless bytes are fine for path existence only; PIL load tested separately.
    chip.write_bytes(b"\xff\xd8\xff\xd9")
    row = {
        "id": "demo::DET_1::discrepancy::t",
        "prompt": "Decide if a building is present.",
        "images": [str(chip)],
        "chosen": '{"recommendation":"accept_as_building"}',
        "rejected": '{"recommendation":"reject_as_building"}',
    }
    sample = row_to_trl_vision_sample(row, load_images=False)
    assert sample["prompt"][0]["role"] == "user"
    types = [part["type"] for part in sample["prompt"][0]["content"]]
    assert types == ["image", "text"]
    assert sample["chosen"][0]["role"] == "assistant"
    assert sample["rejected"][0]["role"] == "assistant"


def test_row_to_trl_vision_sample_loads_pil(tmp_path: Path):
    from PIL import Image

    chip = tmp_path / "chip.png"
    Image.new("RGB", (8, 8), color=(12, 34, 56)).save(chip)
    row = {
        "id": "x",
        "prompt": "prompt",
        "images": [str(chip)],
        "chosen": "chosen",
        "rejected": "rejected",
    }
    sample = row_to_trl_vision_sample(row, load_images=True)
    assert len(sample["images"]) == 1
    assert sample["images"][0].size == (8, 8)


def test_preference_to_dpo_rows_expands_accept_reject_cartesian(tmp_path: Path):
    chip = tmp_path / "aligned" / "demo" / "buildings_out" / "chips_vlm" / "DET_1_pre.jpg"
    chip.parent.mkdir(parents=True)
    chip.write_bytes(b"fake")
    record = {
        "type": "vlm_dpo_preference",
        "schema_version": 2,
        "aoi_id": "demo",
        "feature_id": "DET_1",
        "review_type": "discrepancy",
        "decision": "agree",
        "preferred_recommendation": "accept_as_building",
        "pre_chip": "buildings_out/chips_vlm/DET_1_pre.jpg",
        "created_at": "2026-01-01T00:00:00+00:00",
        "accept_responses": [
            {"recommendation": "accept_as_building", "rationale": "a", "building_present": True, "response_source": "default"},
            {"recommendation": "accept_as_building", "rationale": "b", "building_present": True, "response_source": "ensemble_view", "transform": "rotate_90"},
        ],
        "reject_responses": [
            {"recommendation": "reject_as_building", "rationale": "c", "building_present": False, "response_source": "counterfactual"},
            {"recommendation": "reject_as_building", "rationale": "d", "building_present": False, "response_source": "ensemble_view", "transform": "original"},
        ],
    }
    rows = preference_to_dpo_rows(record, data_root=tmp_path)
    assert len(rows) == 4  # 2x2
    assert {r["chosen_recommendation"] for r in rows} == {"accept_as_building"}
    assert {r["rejected_recommendation"] for r in rows} == {"reject_as_building"}


def test_resolve_vlm_dpo_adapter_default_and_env(tmp_path: Path, monkeypatch):
    from geoagent.tools import llm_client

    monkeypatch.setattr(llm_client, "project_root", lambda: tmp_path)
    monkeypatch.delenv("VLM_DPO_ADAPTER", raising=False)
    monkeypatch.delenv("VISUAL_VERIFIER_ADAPTER", raising=False)
    assert llm_client.resolve_vlm_dpo_adapter() is None

    adapter = tmp_path / "data" / "vlm_dpo" / "runs" / "latest" / "adapter"
    adapter.mkdir(parents=True)
    (adapter / "adapter_config.json").write_text("{}")
    found = llm_client.resolve_vlm_dpo_adapter()
    assert found == adapter.resolve()

    custom = tmp_path / "custom_adapter"
    custom.mkdir()
    (custom / "adapter_config.json").write_text("{}")
    monkeypatch.setenv("VLM_DPO_ADAPTER", str(custom))
    assert llm_client.resolve_vlm_dpo_adapter() == custom.resolve()
