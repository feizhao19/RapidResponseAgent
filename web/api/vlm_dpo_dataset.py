"""Build DPO training records from collected VLM human preferences.

Preference JSONL (from Agree/Reject UI) → multimodal DPO rows for
Llama-3.2-11B-Vision-Instruct fine-tuning.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from geoagent.tools.historical_index import DATA

PREFERENCE_DIR = DATA / "vlm_preferences"
DEFAULT_EXPORT_DIR = DATA / "vlm_dpo"


def judgment_to_assistant_text(judgment: dict[str, Any], *, review_type: str) -> str:
    """Serialize a VLM judgment as the assistant completion used in DPO."""
    if review_type == "damage":
        payload = {
            "pre_description": judgment.get("pre_description"),
            "post_description": judgment.get("post_description"),
            "rationale": judgment.get("rationale"),
            "building_damaged": judgment.get("building_damaged"),
            "recommendation": judgment.get("recommendation"),
        }
    else:
        payload = {
            "short_description": judgment.get("short_description"),
            "rationale": judgment.get("rationale"),
            "building_present": judgment.get("building_present"),
            "recommendation": judgment.get("recommendation"),
        }
    return json.dumps(payload, ensure_ascii=False)


def build_user_prompt(*, review_type: str, kind: str | None = None) -> str:
    """Text instruction paired with chip image(s) for Visual Verifier DPO."""
    if review_type == "damage":
        return (
            "You are a visual verifier for post-disaster building damage assessment. "
            "Image 1 is the pre-disaster chip; image 2 is the post-disaster chip. "
            "Decide whether the building is damaged. "
            "Return JSON with keys: pre_description, post_description, rationale, "
            "building_damaged (boolean), recommendation "
            "(`damaged` | `not_damaged` | `needs_field_check`)."
        )
    kind_note = f" Candidate kind: {kind}." if kind else ""
    return (
        "You are a visual verifier for building footprint arbitration on "
        "pre-disaster remote-sensing imagery. "
        "Decide whether a building is present in the highlighted footprint."
        f"{kind_note} "
        "Return JSON with keys: short_description, rationale, "
        "building_present (boolean), recommendation "
        "(`accept_as_building` | `reject_as_building` | `trust_official_map` | "
        "`needs_field_check`)."
    )


def resolve_chip_paths(
    record: dict[str, Any],
    *,
    data_root: Path = DATA,
) -> list[Path]:
    """Resolve absolute chip paths for a preference record."""
    aoi_id = str(record.get("aoi_id") or "")
    aligned = data_root / "aligned" / aoi_id
    paths: list[Path] = []
    for key in ("pre_chip", "post_chip"):
        rel = record.get(key)
        if not rel:
            continue
        candidate = Path(str(rel))
        if not candidate.is_absolute():
            candidate = aligned / candidate
        if candidate.is_file():
            paths.append(candidate.resolve())
    return paths


def _accept_reject_pools(record: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Recover accept/reject pools from v2 preferences or legacy single pairs."""
    accept = record.get("accept_responses")
    reject = record.get("reject_responses")
    if isinstance(accept, list) and isinstance(reject, list) and accept and reject:
        return (
            [x for x in accept if isinstance(x, dict) and x.get("recommendation")],
            [x for x in reject if isinstance(x, dict) and x.get("recommendation")],
        )
    chosen = record.get("chosen")
    rejected = record.get("rejected")
    if isinstance(chosen, dict) and isinstance(rejected, dict):
        if chosen.get("recommendation") and rejected.get("recommendation"):
            return [chosen], [rejected]
    return [], []


def preference_to_dpo_rows(
    record: dict[str, Any],
    *,
    data_root: Path = DATA,
) -> list[dict[str, Any]]:
    """Expand one human preference into all accept×reject DPO training rows.

    Ensemble views matching the preferred recommendation become accept responses;
    disagreeing views become reject responses. Forced counterfactual seeding
    guarantees both pools are non-empty, so every feedback yields ≥1 DPO pair.
    """
    if record.get("type") and record.get("type") != "vlm_dpo_preference":
        return []
    review_type = str(record.get("review_type") or "").strip()
    if review_type not in {"discrepancy", "damage"}:
        return []

    accept_pool, reject_pool = _accept_reject_pools(record)
    if not accept_pool or not reject_pool:
        return []

    images = resolve_chip_paths(record, data_root=data_root)
    if review_type == "damage" and len(images) < 2:
        return []
    if review_type == "discrepancy" and len(images) < 1:
        return []

    prompt = build_user_prompt(review_type=review_type, kind=str(record.get("kind") or "") or None)
    image_paths = [str(path) for path in images]
    base_id = f"{record.get('aoi_id')}::{record.get('feature_id')}::{review_type}::{record.get('created_at')}"
    rows: list[dict[str, Any]] = []
    pair_i = 0
    for accept in accept_pool:
        for reject in reject_pool:
            if accept.get("recommendation") == reject.get("recommendation"):
                continue
            rows.append(
                {
                    "id": f"{base_id}::pair{pair_i}",
                    "aoi_id": record.get("aoi_id"),
                    "feature_id": record.get("feature_id"),
                    "review_type": review_type,
                    "decision": record.get("decision"),
                    "preferred_recommendation": record.get("preferred_recommendation"),
                    "prompt": prompt,
                    "images": image_paths,
                    "chosen": judgment_to_assistant_text(accept, review_type=review_type),
                    "rejected": judgment_to_assistant_text(reject, review_type=review_type),
                    "chosen_recommendation": accept.get("recommendation"),
                    "rejected_recommendation": reject.get("recommendation"),
                    "chosen_source": accept.get("response_source"),
                    "rejected_source": reject.get("response_source"),
                    "chosen_transform": accept.get("transform"),
                    "rejected_transform": reject.get("transform"),
                    "created_at": record.get("created_at"),
                }
            )
            pair_i += 1
    return rows


def preference_to_dpo_row(
    record: dict[str, Any],
    *,
    data_root: Path = DATA,
) -> dict[str, Any] | None:
    """Backward-compatible helper: first expanded DPO row, if any."""
    rows = preference_to_dpo_rows(record, data_root=data_root)
    return rows[0] if rows else None


def iter_preference_records(preference_dir: Path = PREFERENCE_DIR) -> Iterator[dict[str, Any]]:
    if not preference_dir.is_dir():
        yield from ()
        return
    for path in sorted(preference_dir.glob("*.jsonl")):
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in {path}:{line_no}") from exc
            if isinstance(obj, dict):
                yield obj


def export_dpo_dataset(
    *,
    preference_dir: Path = PREFERENCE_DIR,
    output_path: Path,
    data_root: Path = DATA,
) -> dict[str, Any]:
    """Write multimodal DPO JSONL and return a small export summary."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    skipped = 0
    for record in iter_preference_records(preference_dir):
        expanded = preference_to_dpo_rows(record, data_root=data_root)
        if not expanded:
            skipped += 1
            continue
        rows.extend(expanded)

    with output_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    by_type: dict[str, int] = {}
    for row in rows:
        key = str(row.get("review_type") or "unknown")
        by_type[key] = by_type.get(key, 0) + 1

    return {
        "output_path": str(output_path),
        "n_exported": len(rows),
        "n_skipped_preferences": skipped,
        "by_review_type": by_type,
    }


def build_user_content(prompt: str, n_images: int) -> list[dict[str, Any]]:
    """Multimodal user content matching ``chat_vision`` (image placeholders + text)."""
    if n_images < 1:
        raise ValueError("n_images must be >= 1")
    content: list[dict[str, Any]] = [{"type": "image"} for _ in range(n_images)]
    content.append({"type": "text", "text": prompt})
    return content


def row_to_trl_vision_sample(
    row: dict[str, Any],
    *,
    load_images: bool = False,
) -> dict[str, Any]:
    """Convert an exported DPO JSONL row into TRL Vision Preference format.

    TRL ``DataCollatorForVisionPreference`` expects:
    - ``images``: list of PIL images (or loadable paths when using our loader)
    - conversational ``prompt`` / ``chosen`` / ``rejected`` message lists
    """
    image_paths = [str(p) for p in (row.get("images") or [])]
    if not image_paths:
        raise ValueError(f"DPO row missing images: {row.get('id')}")

    prompt_text = str(row.get("prompt") or "").strip()
    chosen_text = str(row.get("chosen") or "").strip()
    rejected_text = str(row.get("rejected") or "").strip()
    if not prompt_text or not chosen_text or not rejected_text:
        raise ValueError(f"DPO row missing prompt/chosen/rejected: {row.get('id')}")

    user_content = build_user_content(prompt_text, n_images=len(image_paths))
    sample: dict[str, Any] = {
        "id": row.get("id"),
        "images": image_paths,
        "prompt": [{"role": "user", "content": user_content}],
        "chosen": [{"role": "assistant", "content": chosen_text}],
        "rejected": [{"role": "assistant", "content": rejected_text}],
    }
    if load_images:
        sample["images"] = load_pil_images(image_paths)
    return sample


def load_pil_images(image_paths: list[str]):
    """Load RGB PIL images from paths (imported lazily so export stays lightweight)."""
    from PIL import Image

    images = []
    for path in image_paths:
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f"Missing DPO chip image: {path}")
        images.append(Image.open(p).convert("RGB"))
    return images


def encode_mllama_preference_example(
    *,
    processor: Any,
    pil_images: list[Any],
    prompt_messages: list[dict[str, Any]],
    completion_text: str,
) -> dict[str, Any]:
    """Tokenize one (prompt + completion) pair with chips, matching ``chat_vision``.

    Returns processor tensors plus ``prompt_len`` so callers can build
    completion masks for preference training.
    """
    prompt_str = processor.apply_chat_template(prompt_messages, add_generation_prompt=True)
    full_messages = list(prompt_messages) + [
        {"role": "assistant", "content": completion_text},
    ]
    # Some processors only template user turns cleanly; fall back to prompt + completion text.
    try:
        full_str = processor.apply_chat_template(full_messages, add_generation_prompt=False)
    except Exception:
        full_str = prompt_str + completion_text

    prompt_inputs = processor(
        pil_images,
        prompt_str,
        add_special_tokens=False,
        return_tensors="pt",
    )
    full_inputs = processor(
        pil_images,
        full_str,
        add_special_tokens=False,
        return_tensors="pt",
    )
    prompt_len = int(prompt_inputs["input_ids"].shape[-1])
    return {
        "prompt_inputs": prompt_inputs,
        "full_inputs": full_inputs,
        "prompt_len": prompt_len,
        "prompt_str": prompt_str,
        "full_str": full_str,
    }
