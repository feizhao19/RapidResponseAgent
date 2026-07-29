"""Nearest critical facilities via OpenStreetMap Overpass (hospitals, fire, police, shelters)."""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Literal

from geoagent.tools.overpass_client import OVERPASS_ENDPOINTS, post_overpass

FacilityKind = Literal["hospital", "fire_station", "police", "shelter"]

DEFAULT_SEARCH_RADIUS_MI = 10.0
# Overpass around:* is meters; derive km from the operational mile cap.
DEFAULT_SEARCH_RADIUS_KM = DEFAULT_SEARCH_RADIUS_MI * 1.609344  # ≈ 16.1 km
DEFAULT_LIMIT = 5
# Keep a wider inventory in cache (includes unnamed OSM nodes) for later use.
CACHE_STORE_LIMIT = 40
EARTH_RADIUS_KM = 6371.0

FACILITY_SPECS: dict[FacilityKind, dict[str, Any]] = {
    "hospital": {
        "label_singular": "hospital",
        "label_plural": "hospitals",
        "cache_name": "nearest_hospitals.json",
        "list_key": "hospitals",
        "default_name": "Unnamed hospital",
        "overpass_filters": (
            '["amenity"="hospital"]',
            '["healthcare"="hospital"]',
        ),
        "keywords": (
            "hospital",
            "hospitals",
            "emergency room",
            "medical",
            "clinic",
            "ambulance",
            "医院",
            "急诊",
        ),
        "word_keywords": ("er",),
    },
    "fire_station": {
        "label_singular": "fire station",
        "label_plural": "fire stations",
        "cache_name": "nearest_fire_stations.json",
        "list_key": "facilities",
        "default_name": "Unnamed fire station",
        "overpass_filters": (
            '["amenity"="fire_station"]',
        ),
        "keywords": (
            "fire station",
            "fire stations",
            "fire department",
            "fire dept",
            "firefighter",
            "消防",
            "消防站",
            "救火",
        ),
    },
    "police": {
        "label_singular": "police station",
        "label_plural": "police stations",
        "cache_name": "nearest_police.json",
        "list_key": "facilities",
        "default_name": "Unnamed police station",
        "overpass_filters": (
            '["amenity"="police"]',
        ),
        "keywords": (
            "police",
            "police station",
            "sheriff",
            "law enforcement",
            "警察",
            "警局",
            "派出所",
        ),
    },
    "shelter": {
        "label_singular": "shelter",
        "label_plural": "shelters",
        "cache_name": "nearest_shelters.json",
        "list_key": "facilities",
        "default_name": "Unnamed shelter",
        "overpass_filters": (
            '["amenity"="shelter"]',
            '["emergency"="assembly_point"]',
            '["social_facility"="shelter"]',
            '["shelter"="yes"]',
        ),
        "keywords": (
            "shelter",
            "shelters",
            "evacuation shelter",
            "emergency shelter",
            "assembly point",
            "避难所",
            "收容所",
            "安置点",
        ),
    },
}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _element_coordinates(element: dict[str, Any]) -> tuple[float, float] | None:
    if element.get("type") == "node":
        if "lat" in element and "lon" in element:
            return float(element["lat"]), float(element["lon"])
        return None
    center = element.get("center") or {}
    if "lat" in center and "lon" in center:
        return float(center["lat"]), float(center["lon"])
    return None


def _pick_tag(tags: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        value = tags.get(key)
        if value:
            return value.strip()
    return None


def is_unnamed_facility_name(name: Any) -> bool:
    """True for blank / placeholder OSM names like 'Unnamed hospital'."""
    text = str(name or "").strip()
    if not text:
        return True
    lowered = text.casefold()
    if lowered.startswith("unnamed"):
        return True
    for spec in FACILITY_SPECS.values():
        if lowered == str(spec.get("default_name") or "").casefold():
            return True
    return False


def is_named_facility(item: dict[str, Any] | None) -> bool:
    return isinstance(item, dict) and not is_unnamed_facility_name(item.get("name"))


def filter_named_facilities(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Drop placeholder Unnamed* rows (legacy helper; prefer ``rank_facilities_for_display``)."""
    if not items:
        return []
    return [item for item in items if is_named_facility(item)]


def _facility_distance_km(item: dict[str, Any]) -> float:
    try:
        return float(item.get("distance_km") or item.get("distance_mi") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def rank_facilities_for_display(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Prefer named facilities, then Unnamed*; within each group keep distance order.

    Unnamed OSM rows stay in the inventory / cache, but sink below named rows so
    chat, mission priority, and nearest picks surface real names first.
    """
    if not items:
        return []
    named = [item for item in items if is_named_facility(item)]
    unnamed = [item for item in items if isinstance(item, dict) and not is_named_facility(item)]
    named.sort(key=_facility_distance_km)
    unnamed.sort(key=_facility_distance_km)
    return named + unnamed


def _format_address(tags: dict[str, str]) -> str | None:
    """Build a readable address from OSM addr:* tags when present."""
    full = _pick_tag(tags, "addr:full")
    if full:
        return full
    parts: list[str] = []
    housenumber = _pick_tag(tags, "addr:housenumber")
    street = _pick_tag(tags, "addr:street")
    if housenumber and street:
        parts.append(f"{housenumber} {street}")
    elif street:
        parts.append(street)
    elif housenumber:
        parts.append(housenumber)
    for key in ("addr:unit", "addr:city", "addr:state", "addr:postcode"):
        value = _pick_tag(tags, key)
        if value:
            parts.append(value)
    return ", ".join(parts) if parts else None


_GENERIC_FACILITY_TOKENS = (
    "facilities",
    "facility",
    "critical facilities",
    "critical facility",
    "available facilities",
    "nearby facilities",
    "nearest facilities",
    "应急设施",
    "周边设施",
    "附近设施",
    "关键设施",
)

ALL_FACILITY_KINDS: tuple[FacilityKind, ...] = ("hospital", "fire_station", "police", "shelter")

# "facilities other than hospitals" / "besides hospitals" / "except hospitals"
_EXCLUDE_HOSPITAL_RE = re.compile(
    r"(?:other than|besides|except(?: for)?|excluding|without)\s+hospitals?\b"
    r"|\b(?:not|no)\s+hospitals?\b"
    r"|\bnon[- ]hospitals?\b",
    re.IGNORECASE,
)


def detect_facility_kind(question: str) -> FacilityKind | None:
    """Pick the most specific facility kind mentioned in the question."""
    lowered = (question or "").casefold()
    # Ignore "other than hospitals" / "besides hospitals" so exclusion clauses do not
    # force a hospital-only lookup when the user wants fire/police/shelters.
    lowered = _EXCLUDE_HOSPITAL_RE.sub(" ", lowered)
    # Prefer non-hospital kinds first so "fire station near hospital" still can be disambiguated
    # by explicit fire/police/shelter tokens.
    order: tuple[FacilityKind, ...] = ("fire_station", "police", "shelter", "hospital")
    for kind in order:
        spec = FACILITY_SPECS[kind]
        if any(token in lowered for token in spec["keywords"]):
            return kind
        for word in spec.get("word_keywords") or ():
            if re.search(rf"\b{re.escape(word)}\b", lowered):
                return kind
    return None


def wants_facilities_excluding_hospitals(question: str) -> bool:
    """True for asks like 'nearby facilities other than hospitals'."""
    lowered = (question or "").casefold()
    if not _EXCLUDE_HOSPITAL_RE.search(lowered):
        return False
    return any(token in lowered for token in _GENERIC_FACILITY_TOKENS)


def wants_generic_facilities(question: str) -> bool:
    """True when the ask wants mixed critical facilities, not one specific kind."""
    if wants_facilities_excluding_hospitals(question):
        return True
    if detect_facility_kind(question) is not None:
        return False
    lowered = (question or "").casefold()
    return any(token in lowered for token in _GENERIC_FACILITY_TOKENS)


def resolve_facility_kinds(
    question: str,
    *,
    slots: dict[str, Any] | None = None,
) -> list[FacilityKind]:
    """Resolve which facility kinds to fetch for a natural-language ask."""
    slots = slots or {}
    if wants_facilities_excluding_hospitals(question):
        return [kind for kind in ALL_FACILITY_KINDS if kind != "hospital"]

    slot_kind = slots.get("facility_kind")
    if slot_kind == "all" or wants_generic_facilities(question):
        return list(ALL_FACILITY_KINDS)

    kind = detect_facility_kind(question)
    if kind is None and slot_kind in FACILITY_SPECS:
        kind = slot_kind  # type: ignore[assignment]
    if kind in FACILITY_SPECS:
        return [kind]  # type: ignore[list-item]
    return list(ALL_FACILITY_KINDS)


def _nwr_clauses(filters: tuple[str, ...], *, radius_m: int, lat: float, lon: float) -> list[str]:
    """Build nwr[...] (around:...) clauses — one statement per filter instead of node+way+relation."""
    return [f"  nwr{filt}(around:{radius_m},{lat:.6f},{lon:.6f});" for filt in filters]


def build_overpass_query(kind: FacilityKind, lat: float, lon: float, *, radius_m: int) -> str:
    filters = FACILITY_SPECS[kind]["overpass_filters"]
    body = "\n".join(_nwr_clauses(filters, radius_m=radius_m, lat=lat, lon=lon))
    # Shelters use broader tag filters; give Overpass a bit more server time.
    server_timeout = 45 if kind == "shelter" else 25
    return f"""
[out:json][timeout:{server_timeout}];
(
{body}
);
out center tags;
""".strip()


def build_combined_overpass_query(
    kinds: list[FacilityKind] | tuple[FacilityKind, ...],
    lat: float,
    lon: float,
    *,
    radius_m: int,
) -> str:
    """One Overpass round-trip for multiple facility kinds (avoids concurrent slot pressure)."""
    parts: list[str] = []
    for kind in kinds:
        filters = FACILITY_SPECS[kind]["overpass_filters"]
        parts.extend(_nwr_clauses(filters, radius_m=radius_m, lat=lat, lon=lon))
    body = "\n".join(parts)
    server_timeout = 45 if "shelter" in kinds else 30
    return f"""
[out:json][timeout:{server_timeout}];
(
{body}
);
out center tags;
""".strip()


def _kinds_for_element(element: dict[str, Any]) -> list[FacilityKind]:
    """Map an OSM element to one or more facility kinds from its tags."""
    tags = element.get("tags") or {}
    amenity = tags.get("amenity")
    matched: list[FacilityKind] = []
    if amenity == "hospital" or tags.get("healthcare") == "hospital":
        matched.append("hospital")
    if amenity == "fire_station":
        matched.append("fire_station")
    if amenity == "police":
        matched.append("police")
    if (
        amenity == "shelter"
        or tags.get("emergency") == "assembly_point"
        or tags.get("social_facility") == "shelter"
        or tags.get("shelter") == "yes"
    ):
        matched.append("shelter")
    return matched


def _normalize_facility(
    kind: FacilityKind,
    element: dict[str, Any],
    *,
    origin_lat: float,
    origin_lon: float,
) -> dict[str, Any] | None:
    coords = _element_coordinates(element)
    if coords is None:
        return None
    lat, lon = coords
    tags = element.get("tags") or {}
    default_name = FACILITY_SPECS[kind]["default_name"]
    name = _pick_tag(tags, "name", "name:en") or default_name
    distance_km = haversine_km(origin_lat, origin_lon, lat, lon)
    return {
        "kind": kind,
        "name": name,
        "distance_km": round(distance_km, 2),
        "distance_mi": round(distance_km * 0.621371, 2),
        "coordinates_wgs84": [round(lon, 6), round(lat, 6)],
        "latitude": round(lat, 6),
        "longitude": round(lon, 6),
        "phone": _pick_tag(tags, "phone", "contact:phone", "contact:mobile"),
        "email": _pick_tag(tags, "email", "contact:email"),
        "website": _pick_tag(tags, "website", "contact:website", "url"),
        "operator": _pick_tag(tags, "operator", "brand", "operator:wikipedia"),
        "contact_name": _pick_tag(tags, "contact:name", "official_name"),
        "emergency": _pick_tag(tags, "emergency"),
        "beds": _pick_tag(tags, "beds"),
        "address": _format_address(tags),
        "opening_hours": _pick_tag(tags, "opening_hours"),
        "osm_type": element.get("type"),
        "osm_id": element.get("id"),
        "osm_tags": {
            key: tags[key]
            for key in ("amenity", "healthcare", "emergency", "social_facility", "shelter")
            if key in tags
        },
    }


def _parse_facility_elements(
    kind: FacilityKind,
    elements: list[dict[str, Any]],
    *,
    origin_lat: float,
    origin_lon: float,
) -> list[dict[str, Any]]:
    facilities: list[dict[str, Any]] = []
    seen: set[tuple[str, int | None]] = set()
    for element in elements:
        record = _normalize_facility(kind, element, origin_lat=origin_lat, origin_lon=origin_lon)
        if record is None:
            continue
        dedupe_key = (record["name"].casefold(), record.get("osm_id"))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        facilities.append(record)
    facilities.sort(key=lambda item: item["distance_km"])
    return facilities


def fetch_facilities_overpass(
    kind: FacilityKind,
    lat: float,
    lon: float,
    *,
    radius_km: float = DEFAULT_SEARCH_RADIUS_KM,
    timeout_sec: float | None = None,
) -> list[dict[str, Any]]:
    """Fetch one facility kind within ``radius_km`` via Overpass."""
    if timeout_sec is None:
        timeout_sec = 50.0 if kind == "shelter" else 35.0
    label = FACILITY_SPECS[kind]["label_plural"]
    radius_m = int(float(radius_km) * 1000)
    query = build_overpass_query(kind, lat, lon, radius_m=radius_m)
    payload = post_overpass(query, timeout_sec=timeout_sec, label=label)
    return _parse_facility_elements(
        kind,
        list(payload.get("elements") or []),
        origin_lat=lat,
        origin_lon=lon,
    )


def fetch_facilities_overpass_multi(
    kinds: list[FacilityKind] | tuple[FacilityKind, ...],
    lat: float,
    lon: float,
    *,
    radius_km: float = DEFAULT_SEARCH_RADIUS_KM,
    timeout_sec: float | None = None,
) -> dict[FacilityKind, list[dict[str, Any]]]:
    """One Overpass round-trip covering several facility kinds."""
    wanted = list(kinds)
    if not wanted:
        return {}
    if timeout_sec is None:
        timeout_sec = 55.0 if "shelter" in wanted else 40.0

    radius_m = int(float(radius_km) * 1000)
    query = build_combined_overpass_query(wanted, lat, lon, radius_m=radius_m)
    payload = post_overpass(query, timeout_sec=timeout_sec, label="facilities")

    buckets: dict[FacilityKind, list[dict[str, Any]]] = {kind: [] for kind in wanted}
    for element in payload.get("elements") or []:
        for kind in _kinds_for_element(element):
            if kind in buckets:
                buckets[kind].append(element)

    return {
        kind: _parse_facility_elements(
            kind,
            buckets[kind],
            origin_lat=lat,
            origin_lon=lon,
        )
        for kind in wanted
    }


def build_facilities_payload(
    kind: FacilityKind,
    *,
    centroid_wgs84: list[float],
    aoi_id: str | None = None,
    display_name: str | None = None,
    radius_km: float = DEFAULT_SEARCH_RADIUS_KM,
    facilities: list[dict[str, Any]] | None = None,
    nearest: dict[str, Any] | None = None,
    status: str = "ok",
    lookup_error: str | None = None,
) -> dict[str, Any]:
    spec = FACILITY_SPECS[kind]
    facility_list = facilities or []
    list_key = spec["list_key"]
    payload: dict[str, Any] = {
        "schema_version": "1.1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "OpenStreetMap Overpass API (https://overpass-api.de)",
        "status": status,
        "lookup_error": lookup_error,
        "facility_kind": kind,
        "disclaimer": (
            f"{spec['label_plural'].capitalize()} are sourced from OpenStreetMap community data "
            "and may be incomplete or outdated. Verify with official authorities before operational use."
        ),
        "aoi_id": aoi_id,
        "aoi_display_name": display_name,
        "aoi_centroid_wgs84": centroid_wgs84,
        "search_radius_km": radius_km,
        "facility_count": len(facility_list),
        "nearest": nearest if nearest is not None else (facility_list[0] if facility_list else None),
        list_key: facility_list,
    }
    # Hospital-compatible alias fields for existing UI/report code.
    if kind == "hospital":
        payload["hospital_count"] = len(facility_list)
        payload["hospitals"] = facility_list
    return payload


def unavailable_facilities_payload(
    kind: FacilityKind,
    *,
    centroid_wgs84: list[float] | None = None,
    aoi_id: str | None = None,
    display_name: str | None = None,
    radius_km: float = DEFAULT_SEARCH_RADIUS_KM,
    lookup_error: str,
) -> dict[str, Any]:
    centroid = centroid_wgs84 if centroid_wgs84 and len(centroid_wgs84) == 2 else [0.0, 0.0]
    return build_facilities_payload(
        kind,
        centroid_wgs84=[float(centroid[0]), float(centroid[1])],
        aoi_id=aoi_id,
        display_name=display_name,
        radius_km=radius_km,
        facilities=[],
        nearest=None,
        status="unavailable",
        lookup_error=lookup_error,
    )


def find_nearest_facilities(
    kind: FacilityKind,
    *,
    centroid_wgs84: list[float],
    aoi_id: str | None = None,
    display_name: str | None = None,
    radius_km: float = DEFAULT_SEARCH_RADIUS_KM,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    if len(centroid_wgs84) != 2:
        raise ValueError("centroid_wgs84 must be [lon, lat]")
    lon, lat = float(centroid_wgs84[0]), float(centroid_wgs84[1])
    # Store a wider inventory (named + unnamed). Display ranks Unnamed* after named.
    store_limit = max(int(limit), CACHE_STORE_LIMIT)
    facilities = fetch_facilities_overpass(kind, lat, lon, radius_km=radius_km)[:store_limit]
    ranked = rank_facilities_for_display(facilities)
    nearest = ranked[0] if ranked else None
    return build_facilities_payload(
        kind,
        centroid_wgs84=[lon, lat],
        aoi_id=aoi_id,
        display_name=display_name,
        radius_km=radius_km,
        facilities=facilities,
        nearest=nearest,
        status="ok",
    )


def find_all_nearest_facilities(
    *,
    centroid_wgs84: list[float],
    aoi_id: str | None = None,
    display_name: str | None = None,
    radius_km: float = DEFAULT_SEARCH_RADIUS_KM,
    limit_per_kind: int = 3,
    kinds: list[FacilityKind] | tuple[FacilityKind, ...] | None = None,
    aligned_dir: Any | None = None,
) -> dict[str, Any]:
    """Look up hospital / fire / police / shelter and return one combined payload.

    Multiple kinds share a single Overpass round-trip (progressive radius) so we
    stay within public-server concurrency slots instead of firing 4 parallel queries.
    Pass ``kinds`` to limit Overpass load (e.g. mission priority only needs hospital + fire).
    When ``aligned_dir`` is set, successful per-kind caches are used before any network call.
    """
    if len(centroid_wgs84) != 2:
        raise ValueError("centroid_wgs84 must be [lon, lat]")
    lon, lat = float(centroid_wgs84[0]), float(centroid_wgs84[1])
    wanted: list[FacilityKind] = list(kinds) if kinds else list(ALL_FACILITY_KINDS)
    by_kind: dict[str, Any] = {}
    errors: list[str] = []

    if aligned_dir is not None:
        shell = {
            "schema_version": "1.1",
            "facility_kind": "all",
            "by_kind": {},
            "aoi_id": aoi_id,
            "aoi_display_name": display_name,
            "aoi_centroid_wgs84": [lon, lat],
            "search_radius_km": radius_km,
        }
        merged, still_missing = merge_per_kind_caches_into_combined(shell, aligned_dir)
        by_kind = dict(merged.get("by_kind") or {})
        wanted = [kind for kind in wanted if kind in still_missing or kind not in by_kind
                  or (by_kind.get(kind) or {}).get("status") != "ok"]

    store_limit = max(int(limit_per_kind), CACHE_STORE_LIMIT)

    def _payload_from_list(kind: FacilityKind, facilities: list[dict[str, Any]]) -> dict[str, Any]:
        trimmed = facilities[:store_limit]
        ranked = rank_facilities_for_display(trimmed)
        return build_facilities_payload(
            kind,
            centroid_wgs84=[lon, lat],
            aoi_id=aoi_id,
            display_name=display_name,
            radius_km=radius_km,
            facilities=trimmed,
            nearest=ranked[0] if ranked else None,
            status="ok",
        )

    if wanted:
        try:
            fetched = fetch_facilities_overpass_multi(
                wanted,
                lat,
                lon,
                radius_km=radius_km,
            )
            for kind in wanted:
                by_kind[kind] = _payload_from_list(kind, fetched.get(kind) or [])
        except Exception:  # noqa: BLE001 — fall back to sequential single-kind (still slot-limited)
            for kind in wanted:
                try:
                    by_kind[kind] = find_nearest_facilities(
                        kind,
                        centroid_wgs84=[lon, lat],
                        aoi_id=aoi_id,
                        display_name=display_name,
                        radius_km=radius_km,
                        limit=limit_per_kind,
                    )
                except Exception as exc:  # noqa: BLE001
                    by_kind[kind] = unavailable_facilities_payload(
                        kind,
                        aoi_id=aoi_id,
                        centroid_wgs84=[lon, lat],
                        display_name=display_name,
                        radius_km=radius_km,
                        lookup_error=str(exc),
                    )

    for kind, payload in by_kind.items():
        if payload.get("status") != "ok":
            err = payload.get("lookup_error") or "unavailable"
            errors.append(f"{kind}: {err}")

    # Preserve stable key order in the combined payload.
    ordered = {kind: by_kind[kind] for kind in ALL_FACILITY_KINDS if kind in by_kind}
    ok_any = any(payload.get("status") == "ok" for payload in ordered.values())
    return {
        "schema_version": "1.1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "OpenStreetMap Overpass API (https://overpass-api.de)",
        "status": "ok" if ok_any else "unavailable",
        "lookup_error": "; ".join(errors) if errors and not ok_any else None,
        "facility_kind": "all",
        "disclaimer": (
            "Facilities are sourced from OpenStreetMap community data and may be incomplete "
            "or outdated. Verify with official authorities before operational use."
        ),
        "aoi_id": aoi_id,
        "aoi_display_name": display_name,
        "aoi_centroid_wgs84": [lon, lat],
        "search_radius_km": radius_km,
        "by_kind": ordered,
    }


def load_ok_kind_cache(aligned_dir: Any, kind: FacilityKind) -> dict[str, Any] | None:
    """Return a per-kind cache payload when it is present and status=ok."""
    import json
    from pathlib import Path

    path = Path(cache_path_for_kind(aligned_dir, kind))
    if not path.is_file() or path.stat().st_size == 0:
        return None
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        return None
    return payload


def merge_per_kind_caches_into_combined(
    payload: dict[str, Any],
    aligned_dir: Any,
) -> tuple[dict[str, Any], list[str]]:
    """Fill unavailable combined kinds from existing per-kind cache files (no network).

    Returns (updated_payload, kinds_still_missing).
    """
    by_kind = dict(payload.get("by_kind") or {})
    merged_from_cache: list[str] = []
    still_missing: list[str] = []
    for kind in ALL_FACILITY_KINDS:
        current = by_kind.get(kind) or {}
        if current.get("status") == "ok":
            continue
        cached = load_ok_kind_cache(aligned_dir, kind)
        if cached is not None:
            by_kind[kind] = cached
            merged_from_cache.append(kind)
        else:
            still_missing.append(kind)

    if not merged_from_cache:
        return payload, still_missing

    ordered = {kind: by_kind[kind] for kind in ALL_FACILITY_KINDS if kind in by_kind}
    ok_any = any((p or {}).get("status") == "ok" for p in ordered.values())
    errors = [
        f"{kind}: {(ordered.get(kind) or {}).get('lookup_error') or 'unavailable'}"
        for kind in still_missing
    ]
    updated = dict(payload)
    updated.update(
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "ok" if ok_any else "unavailable",
            "lookup_error": "; ".join(errors) if errors and not ok_any else None,
            "by_kind": ordered,
        }
    )
    return updated, still_missing


def refresh_unavailable_facility_kinds(
    payload: dict[str, Any],
    *,
    centroid_wgs84: list[float],
    aoi_id: str | None = None,
    display_name: str | None = None,
    radius_km: float | None = None,
    limit_per_kind: int = 3,
    aligned_dir: Any | None = None,
    kinds: list[FacilityKind] | None = None,
) -> dict[str, Any]:
    """Re-query kinds that failed in a previous combined lookup.

    If ``aligned_dir`` is set, successful per-kind caches are merged first so we
    do not re-hit Overpass when shelters (etc.) were already fetched alone.
    """
    if len(centroid_wgs84) != 2:
        raise ValueError("centroid_wgs84 must be [lon, lat]")
    lon, lat = float(centroid_wgs84[0]), float(centroid_wgs84[1])
    radius = float(
        radius_km if radius_km is not None else payload.get("search_radius_km") or DEFAULT_SEARCH_RADIUS_KM
    )

    working = dict(payload)
    if aligned_dir is not None:
        working, still_missing = merge_per_kind_caches_into_combined(working, aligned_dir)
    else:
        by_kind = working.get("by_kind") or {}
        still_missing = [
            kind
            for kind in ALL_FACILITY_KINDS
            if (by_kind.get(kind) or {}).get("status") != "ok"
        ]

    if kinds is not None:
        still_missing = [kind for kind in still_missing if kind in kinds]

    if not still_missing:
        return working

    by_kind = dict(working.get("by_kind") or {})
    store_limit = max(int(limit_per_kind), CACHE_STORE_LIMIT)
    try:
        fetched = fetch_facilities_overpass_multi(
            still_missing,  # type: ignore[arg-type]
            lat,
            lon,
            radius_km=radius,
        )
        for kind in still_missing:
            facilities = (fetched.get(kind) or [])[:store_limit]  # type: ignore[arg-type]
            ranked = rank_facilities_for_display(facilities)
            by_kind[kind] = build_facilities_payload(
                kind,  # type: ignore[arg-type]
                centroid_wgs84=[lon, lat],
                aoi_id=aoi_id,
                display_name=display_name,
                radius_km=radius,
                facilities=facilities,
                nearest=ranked[0] if ranked else None,
                status="ok",
            )
    except Exception as exc:  # noqa: BLE001
        for kind in still_missing:
            by_kind[kind] = unavailable_facilities_payload(
                kind,  # type: ignore[arg-type]
                aoi_id=aoi_id,
                centroid_wgs84=[lon, lat],
                display_name=display_name,
                radius_km=radius,
                lookup_error=str(exc),
            )

    ordered = {kind: by_kind.get(kind) for kind in ALL_FACILITY_KINDS if kind in by_kind}
    ok_any = any((p or {}).get("status") == "ok" for p in ordered.values())
    errors = [
        f"{kind}: {(ordered.get(kind) or {}).get('lookup_error') or 'unavailable'}"
        for kind in ALL_FACILITY_KINDS
        if (ordered.get(kind) or {}).get("status") != "ok"
    ]
    updated = dict(working)
    updated.update(
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "ok" if ok_any else "unavailable",
            "lookup_error": "; ".join(errors) if errors and not ok_any else None,
            "by_kind": ordered,
            "aoi_centroid_wgs84": [lon, lat],
            "search_radius_km": radius,
        }
    )
    if aoi_id is not None:
        updated["aoi_id"] = aoi_id
    if display_name is not None:
        updated["aoi_display_name"] = display_name
    return updated


def combined_payload_has_unavailable_kind(payload: dict[str, Any] | None) -> bool:
    if not payload:
        return True
    by_kind = payload.get("by_kind") or {}
    for kind in ALL_FACILITY_KINDS:
        if (by_kind.get(kind) or {}).get("status") != "ok":
            return True
    return False


def combined_payload_needs_network_refresh(
    payload: dict[str, Any] | None,
    aligned_dir: Any,
) -> bool:
    """True only when some kind is still missing after consulting per-kind caches."""
    if not payload:
        return True
    _merged, still_missing = merge_per_kind_caches_into_combined(dict(payload), aligned_dir)
    return bool(still_missing)


def load_location_centroid(location_json: dict[str, Any]) -> tuple[list[float], str | None]:
    centroid = location_json.get("centroid_wgs84")
    if not centroid or len(centroid) != 2:
        bounds = location_json.get("bounds_wgs84")
        if not bounds or len(bounds) != 4:
            raise ValueError("location.json missing centroid_wgs84 and bounds_wgs84")
        west, south, east, north = bounds
        centroid = [(west + east) / 2.0, (south + north) / 2.0]
    return [float(centroid[0]), float(centroid[1])], location_json.get("display_name")


def cache_path_for_kind(aligned_dir: Any, kind: FacilityKind) -> Any:
    from pathlib import Path

    name = FACILITY_SPECS[kind]["cache_name"]
    return Path(aligned_dir) / "aoi_out" / name


def _list_items_from_kind_payload(
    kind: FacilityKind,
    kind_payload: dict[str, Any],
    *,
    prefer_named: bool = False,
) -> list[dict[str, Any]]:
    spec = FACILITY_SPECS[kind]
    list_key = spec["list_key"]
    items = (
        kind_payload.get(list_key)
        or kind_payload.get("facilities")
        or kind_payload.get("hospitals")
        or []
    )
    out = [item for item in items if isinstance(item, dict)]
    if prefer_named:
        out = rank_facilities_for_display(out)
    return out


def facilities_payload_for_display(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Shallow-copy a cache payload with Unnamed* rows ranked after named ones."""
    if not payload or not isinstance(payload, dict):
        return payload
    out = dict(payload)
    by_kind = out.get("by_kind")
    if isinstance(by_kind, dict) and by_kind:
        cleaned: dict[str, Any] = {}
        for kind in ALL_FACILITY_KINDS:
            kind_payload = by_kind.get(kind)
            if isinstance(kind_payload, dict):
                cleaned[kind] = facilities_payload_for_display(kind_payload) or kind_payload
            elif kind_payload is not None:
                cleaned[kind] = kind_payload
        out["by_kind"] = cleaned
        return out

    kind_raw = str(out.get("facility_kind") or "hospital")
    kind: FacilityKind = kind_raw if kind_raw in FACILITY_SPECS else "hospital"  # type: ignore[assignment]
    ranked = _list_items_from_kind_payload(kind, out, prefer_named=True)
    list_key = FACILITY_SPECS[kind]["list_key"]
    out[list_key] = ranked
    out["facility_count"] = len(ranked)
    out["nearest"] = ranked[0] if ranked else None
    if kind == "hospital":
        out["hospitals"] = ranked
        out["hospital_count"] = len(ranked)
    return out


def flatten_facilities_payload(
    payload: dict[str, Any] | None,
    *,
    prefer_named: bool = True,
) -> list[dict[str, Any]]:
    """Flatten combined or single-kind facility JSON into map marker records."""
    if not payload or not isinstance(payload, dict):
        return []
    out: list[dict[str, Any]] = []
    by_kind = payload.get("by_kind")
    if isinstance(by_kind, dict) and by_kind:
        for kind in ALL_FACILITY_KINDS:
            kind_payload = by_kind.get(kind) or {}
            if not isinstance(kind_payload, dict) or kind_payload.get("status") == "unavailable":
                continue
            for item in _list_items_from_kind_payload(kind, kind_payload, prefer_named=prefer_named):
                row = dict(item)
                row.setdefault("kind", kind)
                out.append(row)
        return out

    kind_raw = str(payload.get("facility_kind") or "hospital")
    kind: FacilityKind = kind_raw if kind_raw in FACILITY_SPECS else "hospital"  # type: ignore[assignment]
    if payload.get("status") == "unavailable":
        return []
    for item in _list_items_from_kind_payload(kind, payload, prefer_named=prefer_named):
        row = dict(item)
        row.setdefault("kind", kind)
        out.append(row)
    return out


def load_facilities_for_map(aligned_dir: Any) -> list[dict[str, Any]]:
    """Load hospital / fire / police / shelter records for AOI map markers."""
    import json
    from pathlib import Path

    root = Path(aligned_dir) / "aoi_out"
    combined = root / "nearest_facilities_all.json"
    payload: dict[str, Any] = {"facility_kind": "all", "by_kind": {}}
    if combined.is_file() and combined.stat().st_size > 0:
        try:
            loaded = json.loads(combined.read_text())
            if isinstance(loaded, dict):
                payload = loaded
        except json.JSONDecodeError:
            pass
    payload, _missing = merge_per_kind_caches_into_combined(payload, aligned_dir)
    # Map markers: named facilities only (Unnamed* OSM placeholders stay in cache/chat inventory).
    return filter_named_facilities(flatten_facilities_payload(payload, prefer_named=True))