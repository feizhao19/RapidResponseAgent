"""Tests for VLM discrepancy candidate selection and judgment normalization."""

from __future__ import annotations

from geoagent.tools.vlm_arbitrate import (
    DAMAGE_TIE_BREAK_PRIORITY,
    augment_chip,
    augment_chip_pair,
    build_damage_synthesis_user_prompt,
    build_synthesis_user_prompt,
    candidate_kind,
    finalize_damage_ensemble_judgment,
    finalize_ensemble_judgment,
    majority_vote_recommendation,
    normalize_damage_judgment,
    normalize_vlm_judgment,
    parse_json_object,
    presence_from_recommendation,
    recommendation_from_presence,
    select_candidates,
    select_damage_candidates,
)
from PIL import Image


def _feat(props: dict) -> dict:
    return {"type": "Feature", "properties": props, "geometry": {"type": "Point", "coordinates": [0, 0]}}


def test_candidate_kinds():
    assert candidate_kind({"building_origin": "detected"}) == "fp_orphan"
    assert candidate_kind({"assignment_status": "inferred", "building_origin": "lariac"}) == "fn_inferred"
    assert candidate_kind({"building_origin": "lariac", "assignment_status": "vipde"}) is None


def test_select_candidates_prioritizes_orphans_and_limit():
    features = [
        _feat({"building_origin": "lariac", "assignment_status": "inferred", "Shape_Area": 500, "BLD_ID": "A"}),
        _feat({"building_origin": "detected", "assignment_status": "vipde", "Shape_Area": 100, "BLD_ID": "DET_1"}),
        _feat({"building_origin": "detected", "assignment_status": "vipde", "Shape_Area": 300, "BLD_ID": "DET_2"}),
        _feat({"building_origin": "lariac", "assignment_status": "vipde", "Shape_Area": 999, "BLD_ID": "OK"}),
    ]
    rows = select_candidates(features, limit=2)
    assert [r["feature_id"] for r in rows] == ["DET_2", "DET_1"]


def test_select_candidates_damaged_only_skips_undamaged():
    features = [
        _feat(
            {
                "building_origin": "detected",
                "damage_label": "no_damage",
                "Shape_Area": 900,
                "BLD_ID": "OK",
            }
        ),
        _feat(
            {
                "building_origin": "detected",
                "damage_label": "destroyed",
                "Shape_Area": 100,
                "BLD_ID": "BAD",
            }
        ),
        _feat(
            {
                "assignment_status": "inferred",
                "damage_label": "no_damage_inferred",
                "Shape_Area": 800,
                "BLD_ID": "INF",
            }
        ),
        _feat(
            {
                "building_origin": "detected",
                "damage_label": "major",
                "Shape_Area": 50,
                "BLD_ID": "MAJ",
            }
        ),
    ]
    all_rows = select_candidates(features, limit=0)
    assert len(all_rows) == 4
    damaged = select_candidates(features, limit=0, damaged_only=True)
    assert [r["feature_id"] for r in damaged] == ["BAD", "MAJ"]


def test_parse_json_object_from_fenced_text():
    text = '```json\n{"short_description": "A flat lot.", "rationale": "No roof.", "building_present": true}\n```'
    data = parse_json_object(text)
    assert data["building_present"] is True
    assert data["short_description"] == "A flat lot."


def test_recommendation_from_presence():
    assert recommendation_from_presence(True) == "accept_as_building"
    assert recommendation_from_presence(False, kind="fp_orphan") == "reject_as_building"
    assert recommendation_from_presence(False, kind="fn_inferred") == "trust_official_map"
    assert recommendation_from_presence(None) == "needs_field_check"


def test_normalize_vlm_judgment_derives_recommendation():
    judgment = normalize_vlm_judgment(
        {
            "short_description": "Rectangular paved lot with painted stalls and parked cars, "
            "open asphalt surface, no roof structure visible in this chip.",
            "rationale": "The surface is open asphalt with parking markings and no enclosed structure "
            "or roof footprint, so this is not a building.",
            "building_present": False,
            "recommendation": "accept_as_building",  # model noise — ignored
        },
        kind="fp_orphan",
    )
    assert judgment["building_present"] is False
    assert judgment["recommendation"] == "reject_as_building"
    assert judgment["needs_field_check"] is False
    assert "short_description" in judgment
    keys = list(judgment.keys())
    assert keys.index("short_description") < keys.index("rationale")
    assert keys.index("rationale") < keys.index("building_present")
    assert "confidence" not in judgment
    assert "likely_cause" not in judgment


def test_augment_chip_produces_six_variants():
    image = Image.new("RGB", (32, 24), color=(120, 80, 40))
    variants = augment_chip(image)
    assert [label for label, _ in variants] == [
        "original",
        "rotate_90",
        "rotate_180",
        "rotate_270",
        "flip_horizontal",
        "flip_vertical",
    ]
    assert len({img.size for _, img in variants}) >= 2


def test_majority_vote_recommendation():
    winner, counts = majority_vote_recommendation(
        ["reject_as_building", "reject_as_building", "accept_as_building"]
    )
    assert winner == "reject_as_building"
    assert counts["reject_as_building"] == 2

    tie_winner, _ = majority_vote_recommendation(
        ["accept_as_building", "reject_as_building", "needs_field_check", "needs_field_check"]
    )
    assert tie_winner == "needs_field_check"


def test_finalize_ensemble_judgment_uses_vote():
    final = finalize_ensemble_judgment(
        {
            "short_description": "Unified rooftop with shadow.",
            "rationale": "Clear enclosed structure.",
            "building_present": False,
        },
        winning_recommendation="accept_as_building",
        kind="fp_orphan",
    )
    assert final["recommendation"] == "accept_as_building"
    assert final["building_present"] is True
    assert presence_from_recommendation("trust_official_map") is False


def test_build_synthesis_user_prompt_includes_agreeing_views():
    row = {
        "kind": "fp_orphan",
        "feature_id": "DET_1",
        "area": 120.0,
        "feature": {"properties": {"building_origin": "detected", "assignment_status": "vipde"}},
    }
    prompt = build_synthesis_user_prompt(
        row,
        winning_recommendation="reject_as_building",
        vote_counts={"reject_as_building": 4, "accept_as_building": 2},
        agreeing_views=[
            {
                "transform": "rotate_90",
                "judgment": {
                    "short_description": "Flat paved lot.",
                    "rationale": "No roof structure.",
                },
            }
        ],
    )
    assert "reject_as_building (4/6 augmented views agreed)" in prompt
    assert "rotate_90" in prompt
    assert "Flat paved lot." in prompt


def test_select_damage_candidates_defaults_to_destroyed_only():
    features = [
        _feat({"damage_label": "minor", "Shape_Area": 900, "BLD_ID": "M1", "severe_ratio": 0.1}),
        _feat({"damage_label": "destroyed", "Shape_Area": 100, "BLD_ID": "D1", "severe_ratio": 0.9}),
        _feat({"damage_label": "major", "Shape_Area": 500, "BLD_ID": "J1", "severe_ratio": 0.5}),
        _feat({"damage_label": "no_damage", "Shape_Area": 999, "BLD_ID": "OK"}),
    ]
    rows = select_damage_candidates(features, limit=10)
    assert [r["feature_id"] for r in rows] == ["D1"]
    assert rows[0]["kind"] == "damage_predicted"


def test_select_damage_candidates_can_include_minor_major():
    features = [
        _feat({"damage_label": "minor", "Shape_Area": 900, "BLD_ID": "M1", "severe_ratio": 0.1}),
        _feat({"damage_label": "destroyed", "Shape_Area": 100, "BLD_ID": "D1", "severe_ratio": 0.9}),
        _feat({"damage_label": "major", "Shape_Area": 500, "BLD_ID": "J1", "severe_ratio": 0.5}),
    ]
    rows = select_damage_candidates(
        features,
        limit=3,
        labels={"minor", "major", "destroyed"},
    )
    assert [r["feature_id"] for r in rows] == ["D1", "J1", "M1"]


def test_select_damage_candidates_excludes_presence_rejects():
    features = [
        _feat({"damage_label": "destroyed", "Shape_Area": 100, "BLD_ID": "DET_BAD", "severe_ratio": 0.9}),
        _feat({"damage_label": "destroyed", "Shape_Area": 80, "BLD_ID": "D_OK", "severe_ratio": 0.8}),
    ]
    rows = select_damage_candidates(
        features,
        limit=10,
        exclude_ids={"DET_BAD"},
    )
    assert [r["feature_id"] for r in rows] == ["D_OK"]


def test_rejected_building_ids_from_arbitration():
    from geoagent.tools.vlm_arbitrate import rejected_building_ids_from_arbitration

    payload = {
        "results": [
            {
                "feature_id": "DET_1",
                "vlm": {"recommendation": "reject_as_building"},
            },
            {
                "feature_id": "DET_2",
                "ensemble": {"winning_recommendation": "accept_as_building"},
                "vlm": {"recommendation": "accept_as_building"},
            },
            {
                "feature_id": "DET_3",
                "ensemble": {"winning_recommendation": "reject_as_building"},
            },
        ]
    }
    assert rejected_building_ids_from_arbitration(payload) == {"DET_1", "DET_3"}


def test_normalize_damage_judgment():
    judgment = normalize_damage_judgment(
        {
            "pre_description": "Intact rectangular rooftop with dark shadow.",
            "post_description": "Same footprint filled with rubble and missing roof planes.",
            "rationale": "Post chip shows collapse debris where the pre rooftop was intact.",
            "building_damaged": True,
            "recommendation": "not_damaged",  # model noise — ignored
        }
    )
    assert judgment["building_damaged"] is True
    assert judgment["recommendation"] == "damaged"
    assert judgment["needs_field_check"] is False
    keys = list(judgment.keys())
    assert keys.index("pre_description") < keys.index("post_description")
    assert keys.index("post_description") < keys.index("rationale")
    assert keys.index("rationale") < keys.index("building_damaged")


def test_augment_chip_pair_keeps_pre_post_aligned():
    pre = Image.new("RGB", (32, 24), color=(10, 20, 30))
    post = Image.new("RGB", (32, 24), color=(200, 100, 50))
    pairs = augment_chip_pair(pre, post)
    assert len(pairs) == 6
    for label, pre_view, post_view in pairs:
        assert pre_view.size == post_view.size
        assert label in {
            "original",
            "rotate_90",
            "rotate_180",
            "rotate_270",
            "flip_horizontal",
            "flip_vertical",
        }


def test_damage_majority_vote_tie_break():
    winner, counts = majority_vote_recommendation(
        ["damaged", "not_damaged", "damaged", "not_damaged"],
        tie_break=DAMAGE_TIE_BREAK_PRIORITY,
    )
    assert winner == "not_damaged"
    assert counts["damaged"] == 2


def test_finalize_damage_ensemble_judgment_uses_vote():
    final = finalize_damage_ensemble_judgment(
        {
            "pre_description": "Roof intact.",
            "post_description": "Roof gone.",
            "rationale": "Clear collapse.",
            "building_damaged": False,
        },
        winning_recommendation="damaged",
    )
    assert final["recommendation"] == "damaged"
    assert final["building_damaged"] is True


def test_build_damage_synthesis_user_prompt():
    row = {
        "kind": "damage_predicted",
        "feature_id": "D1",
        "area": 200.0,
        "damage_label": "destroyed",
        "feature": {"properties": {"damage_label": "destroyed", "damage_level": 4}},
    }
    prompt = build_damage_synthesis_user_prompt(
        row,
        winning_recommendation="damaged",
        vote_counts={"damaged": 5, "not_damaged": 1},
        agreeing_views=[
            {
                "transform": "flip_horizontal",
                "judgment": {
                    "pre_description": "Intact roof.",
                    "post_description": "Rubble.",
                    "rationale": "Collapsed.",
                },
            }
        ],
    )
    assert "damaged (5/6 augmented views agreed)" in prompt
    assert "Intact roof." in prompt
    assert "Rubble." in prompt

