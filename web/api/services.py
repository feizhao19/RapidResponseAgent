"""Business logic for the RapidResponseAgent web API."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import geopandas as gpd
import numpy as np
import rasterio
from PIL import Image
from rasterio.enums import Resampling
from rasterio.features import geometry_window
from rasterio.transform import Affine, xy
from rasterio.warp import transform as warp_transform
from rasterio.windows import Window
from shapely.geometry import mapping

from geoagent.graph.router import run_geoagent
from geoagent.graph.state import PipelineState
from geoagent.runtime.agent import run_agent_turn
from geoagent.tools.aoi_stats import enrich_stats_with_building_scopes
from geoagent.tools.case_label import enrich_record_with_case_label
from geoagent.tools.historical_index import DATA, DEFAULT_INDEX_PATH, delete_assessment_aoi, load_assessment_index
from geoagent.tools.intent_router import classify_intent

ROOT = Path(__file__).resolve().parents[2]
BUILDINGS_FILENAME = "buildings_with_damage.geojson"
BUILDING_PROPS = (
    "BLD_ID",
    "damage_label",
    "damage_level",
    "building_origin",
    "assignment_status",
    "AREA",
)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _load_json_file(path_str: str | None) -> dict[str, Any] | None:
    if not path_str:
        return None
    path = Path(path_str)
    if not path.is_file():
        return None
    return _read_json(path)


def find_aoi_record(aoi_id: str) -> dict[str, Any]:
    index = load_assessment_index()
    for record in index.get("records", []):
        if record.get("aoi_id") == aoi_id:
            return record
    raise KeyError(f"AOI not found: {aoi_id}")


def aligned_dir_for_record(record: dict[str, Any]) -> Path:
    rel = record.get("aligned_dir")
    if not rel:
        raise FileNotFoundError(f"No aligned_dir for AOI {record.get('aoi_id')}")
    return (DATA / rel).resolve()


def list_aois() -> dict[str, Any]:
    index = load_assessment_index()
    records = [enrich_record_with_case_label(record) for record in index.get("records", [])]
    return {
        "aoi_count": index.get("aoi_count", 0),
        "events": index.get("events", []),
        "records": records,
    }


def remove_aoi(aoi_id: str, *, delete_files: bool = True) -> dict[str, Any]:
    """Delete a past assessment and refresh the index."""
    result = delete_assessment_aoi(aoi_id, delete_files=delete_files)
    get_buildings_geojson_wgs84.cache_clear()
    return result


def get_aoi_detail(aoi_id: str) -> dict[str, Any]:
    record = find_aoi_record(aoi_id)
    aligned_dir = aligned_dir_for_record(record)
    aoi_out = aligned_dir / "aoi_out"

    detail = enrich_record_with_case_label(dict(record))
    for name, filename in (
        ("stats", "aoi_stats.json"),
        ("location", "location.json"),
        ("hospitals", "nearest_hospitals.json"),
        ("manifest", "job_manifest.json"),
    ):
        path = aoi_out / filename
        if path.is_file():
            detail[name] = _read_json(path)

    buildings_path = aligned_dir / "buildings_out" / BUILDINGS_FILENAME
    if detail.get("stats") and buildings_path.is_file():
        try:
            buildings_gdf = gpd.read_file(buildings_path)
            detail["stats"] = enrich_stats_with_building_scopes(detail["stats"], buildings_gdf)
        except Exception:
            pass

    for scope, filename in (
        ("official", "assessment_report_official.md"),
        ("fused", "assessment_report_fused.md"),
    ):
        report_path = aoi_out / filename
        if report_path.is_file():
            detail[f"report_markdown_{scope}"] = report_path.read_text()

    legacy_report = aoi_out / "assessment_report.md"
    if legacy_report.is_file() and not detail.get("report_markdown_official"):
        detail["report_markdown_official"] = legacy_report.read_text()

    if not detail.get("report_markdown_fused") and detail.get("report_markdown_official"):
        detail["report_markdown_fused"] = detail["report_markdown_official"]

    if detail.get("report_markdown_official"):
        detail["report_markdown"] = detail["report_markdown_official"]

    meta_path = aligned_dir / "meta.json"
    if meta_path.is_file():
        meta = _read_json(meta_path)
        detail["imagery_bounds_wgs84"] = (meta.get("grid") or {}).get("bounds_wgs84")
        detail["imagery_corners_wgs84"] = imagery_corners_from_meta(meta)
        detail["registration"] = meta.get("registration")

    detail["imagery"] = {
        "pre": (aligned_dir / "pre.tif").is_file(),
        "post": (aligned_dir / "post.tif").is_file(),
    }
    detail["artifacts"] = {
        **(record.get("artifacts") or {}),
        "buildings_geojson": str(buildings_path.relative_to(DATA)) if buildings_path.is_file() else None,
        "damage_overlay_pre": _artifact_rel(aligned_dir, "buildings_out/pre_building_damage_overlay.png"),
        "damage_overlay_post": _artifact_rel(aligned_dir, "buildings_out/post_building_damage_overlay.png"),
        "vlm_arbitration_json": _artifact_rel(aligned_dir, "buildings_out/vlm_arbitration.json"),
        "vlm_damage_review_json": _artifact_rel(aligned_dir, "buildings_out/vlm_damage_review.json"),
    }

    try:
        aligned_rel = aligned_dir.relative_to(DATA).as_posix()
    except ValueError:
        aligned_rel = None

    def _attach_chip_urls(payload: dict) -> dict:
        if not aligned_rel:
            return payload
        for row in payload.get("results") or []:
            for chip_key in ("pre_chip", "post_chip"):
                chip_rel = row.get(chip_key)
                if chip_rel:
                    row[f"{chip_key}_url"] = f"{aligned_rel}/{chip_rel}"
        return payload

    from web.api.vlm_preferences import enrich_vlm_payload

    vlm_path = aligned_dir / "buildings_out" / "vlm_arbitration.json"
    if vlm_path.is_file():
        detail["vlm_arbitration"] = _attach_chip_urls(
            enrich_vlm_payload(_read_json(vlm_path), review_type="discrepancy") or {}
        )

    damage_path = aligned_dir / "buildings_out" / "vlm_damage_review.json"
    if damage_path.is_file():
        detail["vlm_damage_review"] = _attach_chip_urls(
            enrich_vlm_payload(_read_json(damage_path), review_type="damage") or {}
        )

    return detail


def submit_vlm_preference(
    aoi_id: str,
    *,
    review_type: str,
    feature_id: str,
    decision: str,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Record human agree/disagree on the default VLM answer for DPO pairs."""
    from web.api.vlm_preferences import record_preference

    record = find_aoi_record(aoi_id)
    aligned_dir = aligned_dir_for_record(record)
    return record_preference(
        aoi_id=aoi_id,
        aligned_dir=aligned_dir,
        review_type=review_type,  # type: ignore[arg-type]
        feature_id=feature_id,
        decision=decision,  # type: ignore[arg-type]
        session_id=session_id,
    )


def _artifact_rel(aligned_dir: Path, rel: str) -> str | None:
    path = aligned_dir / rel
    if not path.is_file():
        return None
    try:
        return str(path.relative_to(DATA))
    except ValueError:
        return str(path)


@lru_cache(maxsize=4)
def get_buildings_geojson_wgs84(aoi_id: str) -> dict[str, Any]:
    record = find_aoi_record(aoi_id)
    aligned_dir = aligned_dir_for_record(record)
    buildings_path = aligned_dir / "buildings_out" / BUILDINGS_FILENAME
    if not buildings_path.is_file():
        raise FileNotFoundError(f"Buildings GeoJSON not found for {aoi_id}")

    gdf = gpd.read_file(buildings_path)
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:32611")
    gdf = gdf.to_crs("EPSG:4326")

    keep = [col for col in BUILDING_PROPS if col in gdf.columns]
    if keep:
        gdf = gdf[keep + ["geometry"]]

    return json.loads(gdf.to_json())


def imagery_corners_from_meta(meta: dict[str, Any]) -> dict[str, list[float]] | None:
    grid = meta.get("grid") or {}
    transform_list = grid.get("transform")
    height = grid.get("height")
    width = grid.get("width")
    crs = grid.get("crs")
    if not transform_list or not height or not width or not crs:
        return None

    transform = Affine(*transform_list[:6])
    corner_pairs = [
        xy(transform, 0, 0, offset="ul"),
        xy(transform, 0, width, offset="ur"),
        xy(transform, height, 0, offset="ll"),
    ]
    xs = [point[0] for point in corner_pairs]
    ys = [point[1] for point in corner_pairs]
    lons, lats = warp_transform(crs, "EPSG:4326", xs, ys)
    return {
        "topLeft": [lats[0], lons[0]],
        "topRight": [lats[1], lons[1]],
        "bottomLeft": [lats[2], lons[2]],
    }


def get_imagery_preview(aoi_id: str, which: Literal["pre", "post"]) -> Path:
    if which not in ("pre", "post"):
        raise ValueError(f"Invalid imagery type: {which}")

    record = find_aoi_record(aoi_id)
    aligned_dir = aligned_dir_for_record(record)
    tif_path = aligned_dir / f"{which}.tif"
    if not tif_path.is_file():
        raise FileNotFoundError(f"{which}.tif not found for {aoi_id}")

    cache_path = aligned_dir / "buildings_out" / f"web_preview_{which}.jpg"
    if cache_path.is_file() and cache_path.stat().st_mtime >= tif_path.stat().st_mtime:
        return cache_path

    # Drop stale cache when source GeoTIFF changes.
    if cache_path.is_file():
        cache_path.unlink()

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    max_dim = 2048
    with rasterio.open(tif_path) as src:
        band_count = min(3, src.count)
        height, width = src.height, src.width
        scale = min(1.0, max_dim / max(height, width))
        out_h = max(1, int(height * scale))
        out_w = max(1, int(width * scale))
        data = src.read(
            indexes=tuple(range(1, band_count + 1)),
            out_shape=(band_count, out_h, out_w),
            resampling=Resampling.bilinear,
        )

    if band_count == 1:
        rgb = np.stack([data[0], data[0], data[0]], axis=0)
    else:
        rgb = data[:3]

    if rgb.dtype != np.uint8:
        rgb = np.clip(rgb, 0, 255).astype(np.uint8)

    image = Image.fromarray(np.transpose(rgb, (1, 2, 0)), mode="RGB")
    image.save(cache_path, "JPEG", quality=88, optimize=True)
    return cache_path


def _expand_window(window: Window, padding_px: int) -> Window:
    return Window(
        max(0, window.col_off - padding_px),
        max(0, window.row_off - padding_px),
        window.width + 2 * padding_px,
        window.height + 2 * padding_px,
    )


def _find_building_row(aoi_id: str, bld_id: str):
    record = find_aoi_record(aoi_id)
    aligned_dir = aligned_dir_for_record(record)
    buildings_path = aligned_dir / "buildings_out" / BUILDINGS_FILENAME
    if not buildings_path.is_file():
        raise FileNotFoundError(f"Buildings GeoJSON not found for {aoi_id}")

    gdf = gpd.read_file(buildings_path)
    if "BLD_ID" not in gdf.columns:
        raise KeyError("BLD_ID column missing from buildings GeoJSON")

    matches = gdf[gdf["BLD_ID"].astype(str) == str(bld_id)]
    if matches.empty:
        raise KeyError(f"Building {bld_id} not found in {aoi_id}")
    return aligned_dir, matches.iloc[0], gdf.crs


def get_building_chip(
    aoi_id: str,
    bld_id: str,
    which: Literal["pre", "post"],
    *,
    padding_px: int = 40,
    max_dim: int = 320,
) -> Path:
    if which not in ("pre", "post"):
        raise ValueError(f"Invalid imagery type: {which}")

    aligned_dir, row, gdf_crs = _find_building_row(aoi_id, bld_id)
    tif_path = aligned_dir / f"{which}.tif"
    if not tif_path.is_file():
        raise FileNotFoundError(f"{which}.tif not found for {aoi_id}")

    safe_id = str(bld_id).replace("/", "_")
    cache_path = aligned_dir / "buildings_out" / "chips" / f"{safe_id}_{which}.jpg"
    tif_mtime = tif_path.stat().st_mtime
    if cache_path.is_file() and cache_path.stat().st_mtime >= tif_mtime:
        return cache_path

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    geometry = row.geometry

    with rasterio.open(tif_path) as src:
        if gdf_crs and src.crs and gdf_crs != src.crs:
            geometry = gpd.GeoSeries([geometry], crs=gdf_crs).to_crs(src.crs).iloc[0]

        window = geometry_window(src, [mapping(geometry)])
        window = _expand_window(window, padding_px)
        window = window.intersection(Window(0, 0, src.width, src.height))

        band_count = min(3, src.count)
        data = src.read(
            indexes=tuple(range(1, band_count + 1)),
            window=window,
        )

    if band_count == 1:
        rgb = np.stack([data[0], data[0], data[0]], axis=0)
    else:
        rgb = data[:3]

    if rgb.dtype != np.uint8:
        rgb = np.clip(rgb, 0, 255).astype(np.uint8)

    rgb = np.transpose(rgb, (1, 2, 0))
    height, width = rgb.shape[:2]
    scale = min(1.0, max_dim / max(height, width))
    if scale < 1.0:
        out_h = max(1, int(height * scale))
        out_w = max(1, int(width * scale))
        image = Image.fromarray(rgb, mode="RGB").resize((out_w, out_h), Image.Resampling.LANCZOS)
    else:
        image = Image.fromarray(rgb, mode="RGB")

    image.save(cache_path, "JPEG", quality=90, optimize=True)
    return cache_path


def resolve_data_file(rel_path: str) -> Path:
    candidate = (DATA / rel_path).resolve()
    data_root = DATA.resolve()
    if not str(candidate).startswith(str(data_root)):
        raise PermissionError("Path escapes data root")
    if not candidate.is_file():
        raise FileNotFoundError(rel_path)
    return candidate


def run_ask(
    question: str,
    *,
    history: list[dict[str, str]] | None = None,
    session_id: str | None = None,
    active_aoi_id: str | None = None,
    use_llm: bool = True,
    retrieve_only: bool = False,
    intent_only: bool = False,
    model: str | None = None,
    use_agent_runtime: bool = True,
) -> dict[str, Any]:
    if use_agent_runtime:
        result = run_agent_turn(
            question,
            session_id=session_id,
            active_aoi_id=active_aoi_id,
            use_llm=use_llm,
            retrieve_only=retrieve_only,
            intent_only=intent_only,
            model=model,
            client_history=history,
        )
        return result.to_api_dict()

    if intent_only:
        result = classify_intent(question, use_llm=False)
        return {
            "intent": result.intent,
            "intent_confidence": result.confidence,
            "intent_method": result.method,
            "intent_rationale": result.rationale,
            "clarification": result.clarification,
        }

    state: PipelineState = {
        "user_input": question,
        "chat_history": history or [],
        "use_llm": use_llm,
        "use_llm_router": use_llm,
        "retrieve_only": retrieve_only,
        "default_to_historical": True,
        "assessment_index": str(DEFAULT_INDEX_PATH),
    }
    if model:
        state["llm_model"] = model
    final = run_geoagent(state)

    response: dict[str, Any] = {
        "intent": final.get("intent"),
        "intent_confidence": final.get("intent_confidence"),
        "intent_method": final.get("intent_method"),
        "intent_rationale": final.get("intent_rationale"),
        "clarification": final.get("intent_clarification"),
        "errors": final.get("errors") or [],
    }

    historical = _load_json_file(final.get("historical_answer_json"))
    if historical:
        response["historical"] = historical
        response["answer_markdown"] = historical.get("answer_markdown")

    weather = _load_json_file(final.get("weather_answer_json"))
    if weather:
        response["weather"] = weather
        response["answer_markdown"] = weather.get("answer_markdown")

    if final.get("intent") == "new_assessment":
        response["pipeline"] = {
            "message": "New imagery assessment is available via CLI for long-running ViPDE jobs.",
            "aligned_dir": final.get("aligned_dir"),
            "aoi_id": final.get("aoi_id"),
            "completed_steps": final.get("completed_steps") or [],
            "assessment_report": final.get("assessment_report"),
            "errors": final.get("errors") or [],
        }
        if final.get("assessment_report"):
            report_path = Path(final["assessment_report"])
            if report_path.is_file():
                response["answer_markdown"] = report_path.read_text()

    if final.get("intent") == "clarify" and final.get("intent_clarification"):
        response["answer_markdown"] = final["intent_clarification"]

    return response
