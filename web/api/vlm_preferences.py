"""VLM human preference pairs for DPO of the Visual Verifier.

Flow:
- Default VLM answer is shown in the UI.
- Backend keeps an opposite (counterfactual) hypothesis-guided response.
- Agree  → chosen=default, rejected=counterfactual
- Disagree → chosen=counterfactual, rejected=default
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from geoagent.tools.historical_index import DATA

ReviewType = Literal["discrepancy", "damage"]
Decision = Literal["agree", "disagree"]

PREFERENCE_DIR = DATA / "vlm_preferences"

DISCREPANCY_OPPOSITES = {
    "accept_as_building": "reject_as_building",
    "reject_as_building": "accept_as_building",
    "trust_official_map": "reject_as_building",
}

DAMAGE_OPPOSITES = {
    "damaged": "not_damaged",
    "not_damaged": "damaged",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_bool(value: Any) -> bool | None:
    if value is True or value == "true":
        return True
    if value is False or value == "false":
        return False
    return None


def opposite_recommendation(review_type: ReviewType, recommendation: str | None) -> str | None:
    rec = str(recommendation or "").strip()
    if not rec or rec == "needs_field_check":
        return None
    mapping = DISCREPANCY_OPPOSITES if review_type == "discrepancy" else DAMAGE_OPPOSITES
    return mapping.get(rec)


def _judgment_from_ensemble_opposite(
    row: dict[str, Any],
    *,
    opposite_rec: str,
) -> dict[str, Any] | None:
    views = ((row.get("ensemble") or {}).get("views")) or []
    for view in views:
        if str(view.get("recommendation") or "") != opposite_rec:
            continue
        judgment = view.get("judgment")
        if isinstance(judgment, dict) and judgment:
            out = dict(judgment)
            out["recommendation"] = opposite_rec
            out["needs_field_check"] = False
            out["hypothesis_source"] = "ensemble_minority"
            return out
    return None


def _synthesize_counterfactual(
    row: dict[str, Any],
    *,
    review_type: ReviewType,
    opposite_rec: str,
) -> dict[str, Any]:
    default = dict(row.get("vlm") or {})
    if review_type == "discrepancy":
        present = opposite_rec == "accept_as_building"
        hypothesis = "building" if present else "non_building"
        if present:
            short = (
                "Hypothesis-guided building reading: the footprint outline, roof-like "
                "surface, and surrounding context are consistent with a built structure."
            )
            rationale = (
                "Under the building hypothesis, edges and material patterns read as a "
                "structure rather than open pavement/vegetation alone."
            )
        else:
            short = (
                "Hypothesis-guided non-building reading: the highlighted area looks more "
                "like pavement, yard, canopy, or open ground than a discrete building."
            )
            rationale = (
                "Under the non-building hypothesis, the geometry and texture lack clear "
                "walls/rooftop cues that would confirm a building."
            )
        return {
            "short_description": short,
            "rationale": rationale,
            "building_present": present,
            "recommendation": opposite_rec,
            "needs_field_check": False,
            "hypothesis": hypothesis,
            "hypothesis_source": "synthesized_opposite",
            "prompted_from_default": default.get("recommendation"),
        }

    damaged = opposite_rec == "damaged"
    hypothesis = "damaged" if damaged else "not_damaged"
    pre = str(default.get("pre_description") or "").strip() or (
        "Pre-disaster view of the candidate building footprint."
    )
    if damaged:
        post = (
            "Hypothesis-guided damaged reading: post-disaster change suggests structural "
            "loss, debris, or collapse relative to the pre-disaster building."
        )
        rationale = (
            "Under the damaged hypothesis, pre/post differences indicate meaningful "
            "building damage rather than intact occupancy."
        )
    else:
        post = (
            "Hypothesis-guided intact reading: the post-disaster building still appears "
            "standing with roof/walls largely preserved versus the pre-disaster view."
        )
        rationale = (
            "Under the not-damaged hypothesis, pre/post comparison does not support "
            "destroyed/severe damage for this footprint."
        )
    return {
        "pre_description": pre,
        "post_description": post,
        "rationale": rationale,
        "building_damaged": damaged,
        "recommendation": opposite_rec,
        "needs_field_check": False,
        "hypothesis": hypothesis,
        "hypothesis_source": "synthesized_opposite",
        "prompted_from_default": default.get("recommendation"),
    }


def build_counterfactual(row: dict[str, Any], *, review_type: ReviewType) -> dict[str, Any] | None:
    """Build opposite hypothesis response for a default VLM result row."""
    existing = row.get("counterfactual")
    if isinstance(existing, dict) and existing.get("recommendation"):
        return existing

    default = row.get("vlm") or {}
    if not isinstance(default, dict) or not default:
        return None
    if default.get("needs_field_check") or row.get("error") or row.get("dry_run"):
        return None

    opposite_rec = opposite_recommendation(review_type, str(default.get("recommendation") or ""))
    if not opposite_rec:
        return None

    from_ensemble = _judgment_from_ensemble_opposite(row, opposite_rec=opposite_rec)
    if from_ensemble is not None:
        if review_type == "discrepancy":
            present = _coerce_bool(from_ensemble.get("building_present"))
            if present is None:
                present = opposite_rec == "accept_as_building"
            from_ensemble["building_present"] = present
            from_ensemble["hypothesis"] = "building" if present else "non_building"
        else:
            damaged = _coerce_bool(from_ensemble.get("building_damaged"))
            if damaged is None:
                damaged = opposite_rec == "damaged"
            from_ensemble["building_damaged"] = damaged
            from_ensemble["hypothesis"] = "damaged" if damaged else "not_damaged"
        from_ensemble["prompted_from_default"] = default.get("recommendation")
        return from_ensemble

    return _synthesize_counterfactual(row, review_type=review_type, opposite_rec=opposite_rec)


def enrich_vlm_payload(payload: dict[str, Any] | None, *, review_type: ReviewType) -> dict[str, Any] | None:
    """Attach counterfactual answers onto each result (in place)."""
    if not payload:
        return payload
    for row in payload.get("results") or []:
        if not isinstance(row, dict):
            continue
        counterfactual = build_counterfactual(row, review_type=review_type)
        if counterfactual is not None:
            row["counterfactual"] = counterfactual
        if row.get("vlm"):
            row["default_response"] = row["vlm"]
    return payload



def _usable_judgment(judgment: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(judgment, dict) or not judgment:
        return None
    rec = str(judgment.get("recommendation") or "").strip()
    if not rec or rec == "needs_field_check" or judgment.get("needs_field_check"):
        return None
    return judgment


def preferred_recommendation(default: dict[str, Any], counterfactual: dict[str, Any], decision: Decision) -> str:
    if decision == "agree":
        return str(default.get("recommendation") or "")
    return str(counterfactual.get("recommendation") or "")


def build_accept_reject_pools(
    *,
    target: dict[str, Any],
    default: dict[str, Any],
    counterfactual: dict[str, Any],
    decision: Decision,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Label default/counterfactual/ensemble views by human preference.

    Returns (accept_pool, reject_pool, ensemble_labeled).
    Forced counterfactual guarantees both pools are non-empty when defaults are binary.
    """
    preferred = preferred_recommendation(default, counterfactual, decision)
    if not preferred:
        raise ValueError("Could not determine preferred recommendation from human decision")

    accept_pool: list[dict[str, Any]] = []
    reject_pool: list[dict[str, Any]] = []
    ensemble_labeled: list[dict[str, Any]] = []
    seen_accept: set[str] = set()
    seen_reject: set[str] = set()

    def _key(judgment: dict[str, Any]) -> str:
        return json.dumps(
            {
                "recommendation": judgment.get("recommendation"),
                "rationale": judgment.get("rationale"),
                "short_description": judgment.get("short_description"),
                "pre_description": judgment.get("pre_description"),
                "post_description": judgment.get("post_description"),
                "building_present": judgment.get("building_present"),
                "building_damaged": judgment.get("building_damaged"),
            },
            sort_keys=True,
            ensure_ascii=False,
        )

    def _add(pool: list[dict[str, Any]], seen: set[str], judgment: dict[str, Any], *, source: str, transform: str | None = None) -> None:
        item = dict(judgment)
        item["response_source"] = source
        if transform:
            item["transform"] = transform
        key = _key(item)
        if key in seen:
            return
        seen.add(key)
        pool.append(item)

    # Always seed both sides from default + forced counterfactual.
    if decision == "agree":
        _add(accept_pool, seen_accept, default, source="default")
        _add(reject_pool, seen_reject, counterfactual, source="counterfactual")
    else:
        _add(accept_pool, seen_accept, counterfactual, source="counterfactual")
        _add(reject_pool, seen_reject, default, source="default")

    views = ((target.get("ensemble") or {}).get("views")) or []
    for view in views:
        if not isinstance(view, dict):
            continue
        judgment = _usable_judgment(view.get("judgment") if isinstance(view.get("judgment"), dict) else None)
        if judgment is None:
            # Fall back to recommendation-only shells when judgment text is missing.
            rec = str(view.get("recommendation") or "").strip()
            if not rec or rec == "needs_field_check":
                continue
            judgment = {"recommendation": rec, "rationale": None}
        rec = str(judgment.get("recommendation") or view.get("recommendation") or "").strip()
        if not rec or rec == "needs_field_check":
            continue
        transform = str(view.get("transform") or "") or None
        label = "accept" if rec == preferred else "reject"
        ensemble_labeled.append(
            {
                "transform": transform,
                "recommendation": rec,
                "label": label,
                "judgment": judgment,
            }
        )
        if label == "accept":
            _add(accept_pool, seen_accept, judgment, source="ensemble_view", transform=transform)
        else:
            _add(reject_pool, seen_reject, judgment, source="ensemble_view", transform=transform)

    if not accept_pool or not reject_pool:
        raise ValueError("Accept/reject pools incomplete even after counterfactual seeding")
    return accept_pool, reject_pool, ensemble_labeled


def preference_path(aoi_id: str) -> Path:
    return PREFERENCE_DIR / f"{aoi_id}.jsonl"


def review_json_path(aligned_dir: Path, review_type: ReviewType) -> Path:
    name = "vlm_arbitration.json" if review_type == "discrepancy" else "vlm_damage_review.json"
    return aligned_dir / "buildings_out" / name


def record_preference(
    *,
    aoi_id: str,
    aligned_dir: Path,
    review_type: ReviewType,
    feature_id: str,
    decision: Decision,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Persist a human preference pair and annotate the AOI VLM result JSON."""
    path = review_json_path(aligned_dir, review_type)
    if not path.is_file():
        raise FileNotFoundError(f"No {review_type} VLM results for {aoi_id}")

    payload = json.loads(path.read_text())
    enrich_vlm_payload(payload, review_type=review_type)

    target: dict[str, Any] | None = None
    for row in payload.get("results") or []:
        if str(row.get("feature_id")) == str(feature_id):
            target = row
            break
    if target is None:
        raise KeyError(f"feature_id not found in {review_type} results: {feature_id}")

    default = target.get("vlm")
    counterfactual = target.get("counterfactual")
    if not isinstance(default, dict) or not default:
        raise ValueError("Default VLM response is missing for this feature")
    if not isinstance(counterfactual, dict) or not counterfactual.get("recommendation"):
        raise ValueError("Counterfactual response is unavailable for this feature")
    if default.get("needs_field_check") or target.get("error") or target.get("dry_run"):
        raise ValueError("Preferences are only collected for completed binary VLM judgments")

    accept_pool, reject_pool, ensemble_labeled = build_accept_reject_pools(
        target=target,
        default=default,
        counterfactual=counterfactual,
        decision=decision,
    )
    # Primary pair: first accept × first reject (includes default/counterfactual seeds).
    chosen, rejected = accept_pool[0], reject_pool[0]
    chosen_role = str(chosen.get("response_source") or "accept")
    rejected_role = str(rejected.get("response_source") or "reject")
    preferred = preferred_recommendation(default, counterfactual, decision)

    created_at = _utc_now()
    preference = {
        "type": "vlm_dpo_preference",
        "schema_version": 2,
        "aoi_id": aoi_id,
        "feature_id": feature_id,
        "review_type": review_type,
        "decision": decision,
        "preferred_recommendation": preferred,
        "chosen_role": chosen_role,
        "rejected_role": rejected_role,
        "chosen": chosen,
        "rejected": rejected,
        "accept_responses": accept_pool,
        "reject_responses": reject_pool,
        "ensemble_labeled": ensemble_labeled,
        "dpo_pair_count": len(accept_pool) * len(reject_pool),
        "default_recommendation": default.get("recommendation"),
        "counterfactual_recommendation": counterfactual.get("recommendation"),
        "pre_chip": target.get("pre_chip"),
        "post_chip": target.get("post_chip"),
        "kind": target.get("kind"),
        "session_id": session_id,
        "created_at": created_at,
    }

    target["human_preference"] = {
        "decision": decision,
        "preferred_recommendation": preferred,
        "chosen_role": chosen_role,
        "rejected_role": rejected_role,
        "accept_count": len(accept_pool),
        "reject_count": len(reject_pool),
        "dpo_pair_count": len(accept_pool) * len(reject_pool),
        "created_at": created_at,
        "session_id": session_id,
    }

    path.write_text(json.dumps(payload, indent=2) + "\n")

    PREFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    with preference_path(aoi_id).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(preference, ensure_ascii=False) + "\n")

    return preference
