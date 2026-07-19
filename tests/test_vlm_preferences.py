"""Tests for VLM preference / counterfactual pairing used for DPO collection."""

from __future__ import annotations

import json
from pathlib import Path

from web.api.vlm_preferences import (
    build_accept_reject_pools,
    build_counterfactual,
    enrich_vlm_payload,
    opposite_recommendation,
    record_preference,
)


def test_opposite_recommendation_mapping():
    assert opposite_recommendation("discrepancy", "accept_as_building") == "reject_as_building"
    assert opposite_recommendation("discrepancy", "reject_as_building") == "accept_as_building"
    assert opposite_recommendation("damage", "damaged") == "not_damaged"
    assert opposite_recommendation("damage", "needs_field_check") is None


def test_build_counterfactual_uses_ensemble_minority_when_available():
    row = {
        "feature_id": "DET_1",
        "vlm": {
            "short_description": "Looks like a building",
            "rationale": "Roof cues",
            "building_present": True,
            "recommendation": "accept_as_building",
            "needs_field_check": False,
        },
        "ensemble": {
            "views": [
                {
                    "recommendation": "reject_as_building",
                    "judgment": {
                        "short_description": "Open pavement",
                        "rationale": "No walls",
                        "building_present": False,
                        "recommendation": "reject_as_building",
                    },
                }
            ]
        },
    }
    cf = build_counterfactual(row, review_type="discrepancy")
    assert cf is not None
    assert cf["recommendation"] == "reject_as_building"
    assert cf["building_present"] is False
    assert cf["hypothesis_source"] == "ensemble_minority"
    assert "Open pavement" in cf["short_description"]


def test_build_counterfactual_synthesizes_when_no_minority(tmp_path: Path):
    row = {
        "feature_id": "DET_2",
        "vlm": {
            "short_description": "Parking lot",
            "rationale": "Flat paved area",
            "building_present": False,
            "recommendation": "reject_as_building",
            "needs_field_check": False,
        },
        "ensemble": {"views": []},
    }
    cf = build_counterfactual(row, review_type="discrepancy")
    assert cf is not None
    assert cf["recommendation"] == "accept_as_building"
    assert cf["building_present"] is True
    assert cf["hypothesis_source"] == "synthesized_opposite"


def test_record_preference_disagree_chooses_counterfactual(tmp_path: Path, monkeypatch):
    aligned = tmp_path / "aligned" / "demo"
    out = aligned / "buildings_out"
    out.mkdir(parents=True)
    payload = {
        "aoi_id": "demo",
        "results": [
            {
                "feature_id": "DET_9",
                "kind": "fp_orphan",
                "pre_chip": "buildings_out/chips_vlm/DET_9_pre.jpg",
                "vlm": {
                    "short_description": "Looks like a building",
                    "rationale": "Roof cues",
                    "building_present": True,
                    "recommendation": "accept_as_building",
                    "needs_field_check": False,
                },
            }
        ],
    }
    (out / "vlm_arbitration.json").write_text(json.dumps(payload))

    import web.api.vlm_preferences as prefs

    monkeypatch.setattr(prefs, "PREFERENCE_DIR", tmp_path / "vlm_preferences")
    monkeypatch.setattr(prefs, "DATA", tmp_path)

    recorded = record_preference(
        aoi_id="demo",
        aligned_dir=aligned,
        review_type="discrepancy",
        feature_id="DET_9",
        decision="disagree",
        session_id="s1",
    )
    assert recorded["decision"] == "disagree"
    assert recorded["chosen_role"] == "counterfactual"
    assert recorded["rejected_role"] == "default"
    assert recorded["chosen"]["recommendation"] == "reject_as_building"
    assert recorded["rejected"]["recommendation"] == "accept_as_building"

    updated = json.loads((out / "vlm_arbitration.json").read_text())
    row = updated["results"][0]
    assert row["human_preference"]["decision"] == "disagree"
    assert row["counterfactual"]["recommendation"] == "reject_as_building"

    lines = (tmp_path / "vlm_preferences" / "demo.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["type"] == "vlm_dpo_preference"


def test_enrich_vlm_payload_sets_default_alias():
    payload = {
        "results": [
            {
                "feature_id": "A",
                "vlm": {
                    "building_damaged": True,
                    "recommendation": "damaged",
                    "rationale": "collapsed",
                    "needs_field_check": False,
                },
            }
        ]
    }
    enrich_vlm_payload(payload, review_type="damage")
    row = payload["results"][0]
    assert row["default_response"]["recommendation"] == "damaged"
    assert row["counterfactual"]["recommendation"] == "not_damaged"


def test_build_accept_reject_pools_labels_ensemble_and_guarantees_both_sides():
    target = {
        "vlm": {
            "short_description": "building",
            "rationale": "roof",
            "building_present": True,
            "recommendation": "accept_as_building",
            "needs_field_check": False,
        },
        "counterfactual": {
            "short_description": "not building",
            "rationale": "pavement",
            "building_present": False,
            "recommendation": "reject_as_building",
            "needs_field_check": False,
            "hypothesis_source": "synthesized_opposite",
        },
        "ensemble": {
            "views": [
                {
                    "transform": "original",
                    "recommendation": "accept_as_building",
                    "judgment": {
                        "short_description": "building-a",
                        "rationale": "walls",
                        "building_present": True,
                        "recommendation": "accept_as_building",
                    },
                },
                {
                    "transform": "rotate_90",
                    "recommendation": "reject_as_building",
                    "judgment": {
                        "short_description": "lot",
                        "rationale": "flat",
                        "building_present": False,
                        "recommendation": "reject_as_building",
                    },
                },
                {
                    "transform": "flip_h",
                    "recommendation": "accept_as_building",
                    "judgment": {
                        "short_description": "building-b",
                        "rationale": "roof2",
                        "building_present": True,
                        "recommendation": "accept_as_building",
                    },
                },
            ]
        },
    }
    default = target["vlm"]
    cf = target["counterfactual"]

    accept, reject, labeled = build_accept_reject_pools(
        target=target, default=default, counterfactual=cf, decision="agree"
    )
    assert all(r["recommendation"] == "accept_as_building" for r in accept)
    assert all(r["recommendation"] == "reject_as_building" for r in reject)
    assert len(accept) >= 2  # default + ensemble matches
    assert len(reject) >= 2  # counterfactual + disagreeing view
    assert {x["label"] for x in labeled} == {"accept", "reject"}
    assert len(accept) * len(reject) >= 4

    accept2, reject2, _ = build_accept_reject_pools(
        target=target, default=default, counterfactual=cf, decision="disagree"
    )
    assert all(r["recommendation"] == "reject_as_building" for r in accept2)
    assert all(r["recommendation"] == "accept_as_building" for r in reject2)


def test_record_preference_stores_accept_reject_pools(tmp_path: Path, monkeypatch):
    aligned = tmp_path / "aligned" / "demo"
    out = aligned / "buildings_out"
    out.mkdir(parents=True)
    payload = {
        "aoi_id": "demo",
        "results": [
            {
                "feature_id": "DET_9",
                "kind": "fp_orphan",
                "pre_chip": "buildings_out/chips_vlm/DET_9_pre.jpg",
                "vlm": {
                    "short_description": "Looks like a building",
                    "rationale": "Roof cues",
                    "building_present": True,
                    "recommendation": "accept_as_building",
                    "needs_field_check": False,
                },
                "ensemble": {
                    "views": [
                        {
                            "transform": "original",
                            "recommendation": "accept_as_building",
                            "judgment": {
                                "short_description": "building",
                                "rationale": "walls",
                                "building_present": True,
                                "recommendation": "accept_as_building",
                            },
                        },
                        {
                            "transform": "rotate_90",
                            "recommendation": "reject_as_building",
                            "judgment": {
                                "short_description": "open",
                                "rationale": "flat",
                                "building_present": False,
                                "recommendation": "reject_as_building",
                            },
                        },
                    ]
                },
            }
        ],
    }
    (out / "vlm_arbitration.json").write_text(json.dumps(payload))

    import web.api.vlm_preferences as prefs

    monkeypatch.setattr(prefs, "PREFERENCE_DIR", tmp_path / "vlm_preferences")
    monkeypatch.setattr(prefs, "DATA", tmp_path)

    recorded = record_preference(
        aoi_id="demo",
        aligned_dir=aligned,
        review_type="discrepancy",
        feature_id="DET_9",
        decision="agree",
        session_id="s1",
    )
    assert recorded["schema_version"] == 2
    assert recorded["dpo_pair_count"] == len(recorded["accept_responses"]) * len(recorded["reject_responses"])
    assert recorded["dpo_pair_count"] >= 2
    assert any(x.get("response_source") == "ensemble_view" for x in recorded["accept_responses"])
    assert any(x.get("response_source") == "counterfactual" for x in recorded["reject_responses"])
