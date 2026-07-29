"""AOI Environmental Situation Layer: road closures / incidents (Caltrans LCS + OSM fallback)."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Literal

from geoagent.tools.overpass_client import post_overpass
from geoagent.tools.situation_weather import resolve_aoi_bounds
from geoagent.tools.location_lookup import USER_AGENT

DISCLAIMER = (
    "Advisory road conditions for the Environmental Situation Layer only. "
    "Verify with Caltrans QuickMap / 511 before routing; not part of damage assessment statistics."
)

CACHE_TTL_SEC = 10 * 60
DISTRICT_CACHE_TTL_SEC = 10 * 60
MAX_FEATURES = 80
BOUNDS_PAD_DEG = 0.03
UPCOMING_HOURS = 12

RoadKind = Literal["closure", "lane_closure", "construction", "restriction", "incident"]
RoadSeverity = Literal["closed", "major", "minor"]
RoadStatus = Literal["active", "scheduled"]

LCS_URL_TEMPLATE = "https://cwwp2.dot.ca.gov/data/d{district}/lcs/lcsStatusD{district:02d}.json"
CHP_SA_URL = "https://media.chp.ca.gov/sa_xml/sa.xml"
CHP_CACHE_TTL_SEC = 5 * 60

ROAD_CHAT_KEYWORDS = (
    "road closure",
    "road closures",
    "lane closure",
    "lane closures",
    "road conditions",
    "road condition",
    "traffic incident",
    "traffic incidents",
    "chp",
    "any closures",
    "any road",
    "closures near",
    "closure near",
    "closed roads",
    "roads closed",
    "封路",
    "道路封闭",
    "路况",
    "交通事故",
)

# Approximate Caltrans district footprints (west, south, east, north) for feed selection.
CA_DISTRICT_BOUNDS: dict[int, tuple[float, float, float, float]] = {
    1: (-124.5, 38.7, -122.3, 42.1),
    2: (-122.8, 39.5, -119.8, 42.1),
    3: (-122.5, 38.0, -119.5, 40.5),
    4: (-123.2, 36.9, -121.2, 38.9),
    5: (-122.2, 34.4, -119.0, 37.2),
    6: (-121.0, 34.8, -117.8, 37.6),
    7: (-119.4, 33.3, -117.5, 34.9),
    8: (-118.0, 33.4, -114.0, 35.8),
    9: (-120.2, 35.5, -117.5, 38.2),
    10: (-122.0, 36.8, -119.0, 39.0),
    11: (-117.6, 32.5, -114.5, 33.6),
    12: (-118.2, 33.4, -117.4, 34.0),
}

CA_BOUNDS = (-124.6, 32.4, -114.0, 42.2)

_aoi_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_district_cache: dict[int, tuple[float, list[dict[str, Any]]]] = {}
_chp_cache: tuple[float, list[dict[str, Any]]] | None = None


def _now_epoch() -> int:
    return int(time.time())


def _http_json(url: str, *, timeout_sec: float = 45.0) -> Any | None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        print(f"  Situation roads HTTP failed: {exc}", flush=True)
        return None


def _http_text(url: str, *, timeout_sec: float = 45.0) -> str | None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            return response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        print(f"  Situation roads HTTP text failed: {exc}", flush=True)
        return None


def _strip_quotes(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1].strip()
    return text


def wants_road_conditions(question: str) -> bool:
    lowered = (question or "").strip().casefold()
    if not lowered:
        return False
    if any(k in lowered for k in ROAD_CHAT_KEYWORDS):
        return True
    if "closure" in lowered and any(t in lowered for t in ("road", "lane", "near", "aoi", "this")):
        return True
    if "incident" in lowered and any(t in lowered for t in ("road", "traffic", "chp", "near", "aoi")):
        return True
    return False


def parse_chp_latlon(raw: str | None) -> tuple[float, float] | None:
    """Parse CHP LATLON like ``39323018:120210950`` → (lat, lon) WGS84."""
    text = _strip_quotes(raw)
    if not text or ":" not in text:
        return None
    left, right = text.split(":", 1)
    try:
        lat_i = int(left)
        lon_i = int(right)
    except ValueError:
        return None
    lat = lat_i / 1_000_000.0
    lon = -abs(lon_i / 1_000_000.0)
    if not (32.0 <= lat <= 42.5 and -125.0 <= lon <= -114.0):
        return None
    return lat, lon


def classify_chp_logtype(log_type: str) -> tuple[RoadKind, RoadSeverity]:
    t = (log_type or "").casefold()
    if "closure" in t:
        return "closure", "closed"
    if any(
        token in t
        for token in (
            "1179",
            "1181",
            "1182",
            "1183",
            "20001",
            "20002",
            "collision",
            "hit and run",
            "cfire",
            "car fire",
            "wrong way",
        )
    ):
        return "incident", "major"
    if "fire" in t:
        return "incident", "major"
    return "incident", "minor"


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def expand_bounds(
    bounds_wgs84: list[float] | tuple[float, float, float, float],
    *,
    pad_deg: float = BOUNDS_PAD_DEG,
) -> list[float]:
    west, south, east, north = [float(v) for v in bounds_wgs84]
    return [west - pad_deg, south - pad_deg, east + pad_deg, north + pad_deg]


def bounds_intersect(
    a: list[float] | tuple[float, float, float, float],
    b: list[float] | tuple[float, float, float, float],
) -> bool:
    aw, as_, ae, an = [float(v) for v in a]
    bw, bs, be, bn = [float(v) for v in b]
    return not (ae < bw or be < aw or an < bs or bn < as_)


def point_in_bounds(
    lon: float,
    lat: float,
    bounds: list[float] | tuple[float, float, float, float],
) -> bool:
    west, south, east, north = [float(v) for v in bounds]
    return west <= lon <= east and south <= lat <= north


def segment_hits_bounds(
    lon1: float,
    lat1: float,
    lon2: float | None,
    lat2: float | None,
    bounds: list[float] | tuple[float, float, float, float],
) -> bool:
    if point_in_bounds(lon1, lat1, bounds):
        return True
    if lon2 is not None and lat2 is not None and point_in_bounds(lon2, lat2, bounds):
        return True
    if lon2 is None or lat2 is None:
        return False
    # Coarse AABB overlap for the segment.
    seg = (
        min(lon1, lon2),
        min(lat1, lat2),
        max(lon1, lon2),
        max(lat1, lat2),
    )
    return bounds_intersect(seg, bounds)


def districts_for_bounds(
    bounds_wgs84: list[float] | tuple[float, float, float, float],
) -> list[int]:
    hits = [
        district
        for district, box in CA_DISTRICT_BOUNDS.items()
        if bounds_intersect(bounds_wgs84, box)
    ]
    return hits or ([7] if bounds_intersect(bounds_wgs84, CA_BOUNDS) else [])


def in_california(bounds_wgs84: list[float] | tuple[float, float, float, float]) -> bool:
    return bounds_intersect(bounds_wgs84, CA_BOUNDS)


def classify_lcs_closure(closure: dict[str, Any]) -> tuple[RoadKind, RoadSeverity]:
    raw = str(closure.get("typeOfClosure") or "").strip().lower()
    work = str(closure.get("typeOfWork") or "").strip().lower()
    if raw in {"full", "road"}:
        return "closure", "closed"
    if "construction" in work or "paving" in work:
        kind: RoadKind = "construction"
    elif raw in {"lane", "one-way traffic", "moving", "traffic break"}:
        kind = "lane_closure"
    else:
        kind = "restriction"
    if raw == "lane":
        lanes = str(closure.get("lanesClosed") or "")
        total = _num(closure.get("totalExistingLanes"))
        closed_n = len([p for p in lanes.replace(" ", "").split(",") if p])
        if total and closed_n >= max(2, int(total) // 2):
            return kind, "major"
        return kind, "minor"
    if raw in {"one-way traffic", "moving", "traffic break"}:
        return kind, "major"
    return kind, "minor"


def _iso_from_epoch(epoch: Any) -> str | None:
    value = _num(epoch)
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _lcs_title(route: str, kind: RoadKind, severity: RoadSeverity, direction: str) -> str:
    label = {
        "closure": "Full closure",
        "lane_closure": "Lane closure",
        "construction": "Construction",
        "restriction": "Restriction",
    }[kind]
    if severity == "closed":
        label = "Full closure"
    parts = [route or "State route", label]
    if direction:
        parts.append(direction)
    return " · ".join(parts)


def normalize_lcs_record(
    item: dict[str, Any],
    *,
    now_epoch: int | None = None,
) -> dict[str, Any] | None:
    """Normalize one Caltrans LCS record into a compact situation feature candidate."""
    lcs = item.get("lcs") if isinstance(item, dict) else None
    if not isinstance(lcs, dict):
        return None
    location = lcs.get("location") or {}
    begin = location.get("begin") or {}
    end = location.get("end") or {}
    closure = lcs.get("closure") or {}
    lon1 = _num(begin.get("beginLongitude"))
    lat1 = _num(begin.get("beginLatitude"))
    if lon1 is None or lat1 is None:
        return None
    lon2 = _num(end.get("endLongitude"))
    lat2 = _num(end.get("endLatitude"))
    kind, severity = classify_lcs_closure(closure)
    ts = closure.get("closureTimestamp") or {}
    start_epoch = _num(ts.get("closureStartEpoch"))
    end_epoch = _num(ts.get("closureEndEpoch"))
    indefinite = _truthy(ts.get("isClosureEndIndefinite"))
    code_1097 = _truthy((closure.get("code1097") or {}).get("isCode1097"))
    now = now_epoch if now_epoch is not None else _now_epoch()
    in_window = False
    if start_epoch is not None:
        if indefinite and now >= start_epoch:
            in_window = True
        elif end_epoch is not None and start_epoch <= now <= end_epoch:
            in_window = True
    upcoming = False
    if start_epoch is not None and start_epoch > now:
        upcoming = start_epoch <= now + UPCOMING_HOURS * 3600
    if not (code_1097 or in_window or upcoming):
        return None
    status: RoadStatus = "active" if (code_1097 or in_window) else "scheduled"
    route = str(begin.get("beginRoute") or end.get("endRoute") or "").strip()
    direction = str(location.get("travelFlowDirection") or "").strip()
    begin_name = str(begin.get("beginLocationName") or "").strip()
    end_name = str(end.get("endLocationName") or "").strip()
    place = str(begin.get("beginNearbyPlace") or "").strip()
    work = str(closure.get("typeOfWork") or "").strip()
    lanes = str(closure.get("lanesClosed") or "").strip()
    facility = str(closure.get("facility") or "").strip()
    desc_parts = []
    if begin_name and end_name:
        desc_parts.append(f"{begin_name} → {end_name}")
    elif begin_name:
        desc_parts.append(begin_name)
    if place:
        desc_parts.append(place)
    if work:
        desc_parts.append(work)
    if lanes:
        desc_parts.append(f"lanes {lanes}")
    if facility:
        desc_parts.append(facility)
    closure_id = str(closure.get("closureID") or lcs.get("index") or "lcs")
    log_number = str(closure.get("logNumber") or "")
    feature_id = f"lcs-{closure_id}-{log_number or '0'}"
    same_point = (
        lon2 is None
        or lat2 is None
        or (abs(lon1 - lon2) < 1e-5 and abs(lat1 - lat2) < 1e-5)
    )
    if same_point:
        geometry: dict[str, Any] = {
            "type": "Point",
            "coordinates": [round(lon1, 6), round(lat1, 6)],
        }
    else:
        geometry = {
            "type": "LineString",
            "coordinates": [
                [round(lon1, 6), round(lat1, 6)],
                [round(lon2, 6), round(lat2, 6)],  # type: ignore[arg-type]
            ],
        }
    return {
        "id": feature_id,
        "kind": kind,
        "severity": severity,
        "status": status,
        "title": _lcs_title(route, kind, severity, direction),
        "description": " · ".join(desc_parts) if desc_parts else None,
        "route": route or None,
        "direction": direction or None,
        "lanes_closed": lanes or None,
        "type_of_work": work or None,
        "facility": facility or None,
        "updated_at": _iso_from_epoch((lcs.get("recordTimestamp") or {}).get("recordEpoch")),
        "starts_at": _iso_from_epoch(start_epoch),
        "ends_at": None if indefinite else _iso_from_epoch(end_epoch),
        "source": "Caltrans LCS",
        "district": str(begin.get("beginDistrict") or ""),
        "geometry": geometry,
        "_lon1": lon1,
        "_lat1": lat1,
        "_lon2": lon2,
        "_lat2": lat2,
        "_dedupe": (
            closure_id,
            round(lon1, 4),
            round(lat1, 4),
            round(lon2 or lon1, 4),
            round(lat2 or lat1, 4),
            kind,
            status,
        ),
        "_rank": (
            0 if status == "active" else 1,
            {"closed": 0, "major": 1, "minor": 2}[severity],
            start_epoch or 0,
        ),
    }


def filter_features_to_bounds(
    candidates: list[dict[str, Any]],
    bounds: list[float] | tuple[float, float, float, float],
    *,
    limit: int = MAX_FEATURES,
) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for item in sorted(candidates, key=lambda f: f.get("_rank", (9, 9, 0))):
        lon1 = item.get("_lon1")
        lat1 = item.get("_lat1")
        if lon1 is None or lat1 is None:
            continue
        if not segment_hits_bounds(lon1, lat1, item.get("_lon2"), item.get("_lat2"), bounds):
            continue
        key = item.get("_dedupe")
        if key in seen:
            continue
        seen.add(key)
        clean = {k: v for k, v in item.items() if not str(k).startswith("_")}
        hits.append(clean)
        if len(hits) >= limit:
            break
    return hits


def parse_lcs_payload(
    payload: Any,
    *,
    now_epoch: int | None = None,
) -> list[dict[str, Any]]:
    data = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for item in data:
        feature = normalize_lcs_record(item, now_epoch=now_epoch)
        if feature is not None:
            out.append(feature)
    return out


def fetch_lcs_district_candidates(
    district: int,
    *,
    fetch_fn: Callable[[str], Any | None] | None = None,
    now_epoch: int | None = None,
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    now = time.time()
    if use_cache and district in _district_cache:
        cached_at, cached = _district_cache[district]
        if now - cached_at < DISTRICT_CACHE_TTL_SEC:
            return cached
    fetcher = fetch_fn or _http_json
    url = LCS_URL_TEMPLATE.format(district=district)
    payload = fetcher(url)
    if payload is None:
        raise RuntimeError(f"Caltrans LCS district {district} request failed")
    candidates = parse_lcs_payload(payload, now_epoch=now_epoch)
    if use_cache:
        _district_cache[district] = (now, candidates)
    return candidates


def _overpass_closure_query(bounds: list[float]) -> str:
    west, south, east, north = bounds
    bbox = f"{south},{west},{north},{east}"
    # Avoid bare way["construction"] (full-table-ish scan). Limit highway classes
    # and use out geom only for the restricted set needed for map geometry.
    return f"""
[out:json][timeout:25];
(
  way["highway"]["access"="no"]({bbox});
  way["highway"~"^(motorway|trunk|primary|secondary|tertiary|residential|unclassified|service)$"]["construction"]({bbox});
  way["highway"]["barrier"]({bbox});
  node["highway"="roadworks"]({bbox});
  node["highway"="construction"]({bbox});
);
out geom;
""".strip()


def normalize_osm_element(element: dict[str, Any]) -> dict[str, Any] | None:
    tags = element.get("tags") or {}
    etype = element.get("type")
    eid = element.get("id")
    if eid is None:
        return None
    name = str(tags.get("name") or tags.get("ref") or "OSM road restriction").strip()
    access = str(tags.get("access") or "").lower()
    construction = tags.get("construction") or tags.get("construction:highway")
    if access == "no":
        kind: RoadKind = "closure"
        severity: RoadSeverity = "closed"
    elif construction:
        kind = "construction"
        severity = "major"
    else:
        kind = "restriction"
        severity = "minor"
    geometry: dict[str, Any] | None = None
    lon1 = lat1 = lon2 = lat2 = None
    if etype == "node":
        lon1 = _num(element.get("lon"))
        lat1 = _num(element.get("lat"))
        if lon1 is None or lat1 is None:
            return None
        geometry = {"type": "Point", "coordinates": [round(lon1, 6), round(lat1, 6)]}
    elif etype == "way":
        coords = []
        for pt in element.get("geometry") or []:
            lon = _num(pt.get("lon"))
            lat = _num(pt.get("lat"))
            if lon is None or lat is None:
                continue
            coords.append([round(lon, 6), round(lat, 6)])
        if len(coords) < 2:
            return None
        lon1, lat1 = coords[0][0], coords[0][1]
        lon2, lat2 = coords[-1][0], coords[-1][1]
        geometry = {"type": "LineString", "coordinates": coords}
    else:
        return None
    return {
        "id": f"osm-{etype}-{eid}",
        "kind": kind,
        "severity": severity,
        "status": "active",
        "title": name if name else "OSM restriction",
        "description": " · ".join(
            p
            for p in (
                str(tags.get("highway") or ""),
                "access=no" if access == "no" else "",
                f"construction={construction}" if construction else "",
            )
            if p
        )
        or None,
        "route": tags.get("ref"),
        "direction": None,
        "lanes_closed": None,
        "type_of_work": str(construction) if construction else None,
        "facility": tags.get("highway"),
        "updated_at": None,
        "starts_at": None,
        "ends_at": None,
        "source": "OpenStreetMap",
        "district": None,
        "geometry": geometry,
        "_lon1": lon1,
        "_lat1": lat1,
        "_lon2": lon2,
        "_lat2": lat2,
        "_dedupe": ("osm", etype, eid),
        "_rank": (0, {"closed": 0, "major": 1, "minor": 2}[severity], 0),
    }


def fetch_osm_road_candidates(
    bounds_wgs84: list[float],
    *,
    fetch_fn: Callable[[str, bytes], Any | None] | None = None,
    timeout_sec: float = 30.0,
) -> list[dict[str, Any]]:
    query = _overpass_closure_query(bounds_wgs84)

    if fetch_fn is not None:
        # Test hook: old (endpoint, body) signature.
        body = urllib.parse.urlencode({"data": query}).encode("utf-8")
        payload = None
        from geoagent.tools.overpass_client import OVERPASS_ENDPOINTS

        for endpoint in OVERPASS_ENDPOINTS:
            payload = fetch_fn(endpoint, body)
            if payload is not None:
                break
        if payload is None:
            raise RuntimeError("OSM Overpass road-conditions request failed")
    else:
        try:
            payload = post_overpass(query, timeout_sec=timeout_sec, label="road-conditions")
        except RuntimeError as exc:
            raise RuntimeError("OSM Overpass road-conditions request failed") from exc

    out: list[dict[str, Any]] = []
    for element in payload.get("elements") or []:
        feature = normalize_osm_element(element)
        if feature is not None:
            out.append(feature)
    return out


def normalize_chp_log(log_el: Any) -> dict[str, Any] | None:
    """Normalize one CHP ``<Log>`` element into a situation feature candidate."""
    import xml.etree.ElementTree as ET

    if not isinstance(log_el, ET.Element):
        return None
    log_id = str(log_el.attrib.get("ID") or "").strip()
    log_type = _strip_quotes(log_el.findtext("LogType"))
    location = _strip_quotes(log_el.findtext("Location"))
    location_desc = _strip_quotes(log_el.findtext("LocationDesc"))
    area = _strip_quotes(log_el.findtext("Area"))
    log_time = _strip_quotes(log_el.findtext("LogTime"))
    coords = parse_chp_latlon(log_el.findtext("LATLON"))
    if coords is None:
        return None
    lat, lon = coords
    kind, severity = classify_chp_logtype(log_type)
    details: list[str] = []
    for detail in log_el.findall(".//IncidentDetail"):
        text = _strip_quotes(detail.text)
        if text:
            details.append(text)
    details = details[:3]
    desc_parts = [p for p in (location_desc, area, *details) if p]
    title = log_type or "CHP incident"
    if location:
        title = f"{log_type} · {location}" if log_type else location
    return {
        "id": f"chp-{log_id or f'{lat:.4f}-{lon:.4f}'}",
        "kind": kind,
        "severity": severity,
        "status": "active",
        "title": title,
        "description": " · ".join(desc_parts) if desc_parts else None,
        "route": None,
        "direction": None,
        "lanes_closed": None,
        "type_of_work": log_type or None,
        "facility": None,
        "updated_at": None,
        "starts_at": None,
        "ends_at": None,
        "reported_at": log_time or None,
        "source": "CHP",
        "district": None,
        "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
        "_lon1": lon,
        "_lat1": lat,
        "_lon2": None,
        "_lat2": None,
        "_dedupe": ("chp", log_id or f"{lon:.4f}:{lat:.4f}"),
        "_rank": (
            0,
            {"closed": 0, "major": 1, "minor": 2}[severity],
            0 if kind == "closure" else 1,
        ),
    }


def parse_chp_xml(xml_text: str) -> list[dict[str, Any]]:
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise RuntimeError(f"CHP XML parse failed: {exc}") from exc
    out: list[dict[str, Any]] = []
    for log in root.iter("Log"):
        feature = normalize_chp_log(log)
        if feature is not None:
            out.append(feature)
    return out


def fetch_chp_candidates(
    *,
    fetch_fn: Callable[[str], str | None] | None = None,
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    global _chp_cache
    now = time.time()
    if use_cache and _chp_cache is not None:
        cached_at, cached = _chp_cache
        if now - cached_at < CHP_CACHE_TTL_SEC:
            return cached
    fetcher = fetch_fn or _http_text
    xml_text = fetcher(CHP_SA_URL)
    if not xml_text:
        raise RuntimeError("CHP statewide incident feed request failed")
    candidates = parse_chp_xml(xml_text)
    if use_cache:
        _chp_cache = (now, candidates)
    return candidates


def summarize_features(features: list[dict[str, Any]]) -> dict[str, int]:
    closure_count = sum(1 for f in features if f.get("kind") == "closure" or f.get("severity") == "closed")
    lane_count = sum(1 for f in features if f.get("kind") == "lane_closure")
    construction_count = sum(1 for f in features if f.get("kind") == "construction")
    incident_count = sum(1 for f in features if f.get("kind") == "incident")
    active_count = sum(1 for f in features if f.get("status") == "active")
    return {
        "feature_count": len(features),
        "closure_count": closure_count,
        "lane_closure_count": lane_count,
        "construction_count": construction_count,
        "incident_count": incident_count,
        "active_count": active_count,
        "scheduled_count": len(features) - active_count,
    }


def _compose_source(parts: list[str]) -> str:
    clean = [p for p in parts if p]
    if not clean:
        return "unavailable"
    return " + ".join(clean)


def build_situation_roads(
    aoi_id: str,
    *,
    bounds_wgs84: list[float] | None = None,
    centroid_wgs84: list[float] | None = None,
    lcs_fetch_fn: Callable[[str], Any | None] | None = None,
    osm_fetch_fn: Callable[[str, bytes], Any | None] | None = None,
    chp_fetch_fn: Callable[[str], str | None] | None = None,
    now_epoch: int | None = None,
    use_district_cache: bool = True,
    use_chp_cache: bool = True,
) -> dict[str, Any]:
    """Build Road Conditions snapshot for an AOI (Caltrans LCS + CHP, OSM fallback)."""
    if bounds_wgs84 is not None:
        bounds = [float(v) for v in bounds_wgs84]
        centroid = centroid_wgs84
        if not centroid or len(centroid) != 2:
            west, south, east, north = bounds
            centroid = [(west + east) / 2.0, (south + north) / 2.0]
        display_name = aoi_id
    else:
        meta = resolve_aoi_bounds(aoi_id)
        bounds = meta["bounds_wgs84"]
        centroid = meta.get("centroid_wgs84")
        display_name = meta.get("display_name") or aoi_id

    query_bounds = expand_bounds(bounds)
    candidates: list[dict[str, Any]] = []
    source_parts: list[str] = []
    notes: list[str] = []
    errors: list[str] = []

    if in_california(query_bounds):
        districts = districts_for_bounds(query_bounds)
        for district in districts:
            try:
                candidates.extend(
                    fetch_lcs_district_candidates(
                        district,
                        fetch_fn=lcs_fetch_fn,
                        now_epoch=now_epoch,
                        use_cache=use_district_cache and lcs_fetch_fn is None,
                    )
                )
            except RuntimeError as exc:
                errors.append(str(exc))
        try:
            candidates.extend(
                fetch_chp_candidates(
                    fetch_fn=chp_fetch_fn,
                    use_cache=use_chp_cache and chp_fetch_fn is None,
                )
            )
        except RuntimeError as exc:
            errors.append(str(exc))
            notes.append("CHP incident feed unavailable")

    features = filter_features_to_bounds(candidates, query_bounds)
    if any(f.get("source") == "Caltrans LCS" for f in features):
        source_parts.append("Caltrans LCS")
    if any(f.get("source") == "CHP" for f in features):
        source_parts.append("CHP")

    if not features:
        if in_california(query_bounds) and not errors:
            notes.append("No Caltrans/CHP events in AOI pad; trying OSM fallback")
        try:
            osm_candidates = fetch_osm_road_candidates(
                query_bounds,
                fetch_fn=osm_fetch_fn,
            )
            features = filter_features_to_bounds(osm_candidates, query_bounds)
            if features:
                source_parts = ["OpenStreetMap"]
            else:
                notes.append("No OSM access=no / construction features in AOI pad")
                if not source_parts:
                    source_parts = ["OpenStreetMap"]
        except RuntimeError as exc:
            errors.append(str(exc))

    source = _compose_source(source_parts)
    if not features and errors and source == "unavailable":
        raise RuntimeError("; ".join(errors))

    return {
        "schema_version": "1.0",
        "aoi_id": aoi_id,
        "display_name": display_name,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "disclaimer": DISCLAIMER,
        "bounds_wgs84": bounds,
        "centroid_wgs84": [float(centroid[0]), float(centroid[1])] if centroid else None,
        "features": features,
        "summary": summarize_features(features),
        "notes": notes,
    }


def feature_anchor_wgs84(feature: dict[str, Any]) -> tuple[float, float] | None:
    """Return (lon, lat) for a road feature Point or LineString midpoint."""
    geometry = feature.get("geometry") or {}
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if gtype == "Point" and isinstance(coords, (list, tuple)) and len(coords) >= 2:
        return float(coords[0]), float(coords[1])
    if gtype == "LineString" and isinstance(coords, list) and len(coords) >= 1:
        mid = coords[len(coords) // 2]
        if isinstance(mid, (list, tuple)) and len(mid) >= 2:
            return float(mid[0]), float(mid[1])
    lon1 = feature.get("_lon1")
    lat1 = feature.get("_lat1")
    if lon1 is not None and lat1 is not None:
        return float(lon1), float(lat1)
    return None


def road_map_href(feature: dict[str, Any]) -> str | None:
    """In-app chat deep link so road titles open the map RD layer."""
    from urllib.parse import urlencode

    anchor = feature_anchor_wgs84(feature)
    if anchor is None:
        return None
    lon, lat = anchor
    params = {
        "lon": f"{lon:.6f}",
        "lat": f"{lat:.6f}",
        "name": str(feature.get("title") or feature.get("id") or "Road event"),
        "id": str(feature.get("id") or ""),
        "kind": str(feature.get("kind") or "restriction"),
        "severity": str(feature.get("severity") or ""),
    }
    return f"#map-road?{urlencode(params)}"


def road_title_md(feature: dict[str, Any]) -> str:
    title = str(feature.get("title") or feature.get("id") or "Road event")
    href = road_map_href(feature)
    if href:
        return f"[{title}]({href})"
    return title


def format_situation_roads_markdown(payload: dict[str, Any], *, question: str | None = None) -> str:
    """Deterministic markdown brief for chat (map-aligned Road Conditions)."""
    _ = question
    summary = payload.get("summary") or {}
    features = list(payload.get("features") or [])
    display = payload.get("display_name") or payload.get("aoi_id") or "AOI"
    source = payload.get("source") or "unavailable"
    lines = [
        f"### Road conditions · {display}",
        "",
        (
            f"**{summary.get('feature_count', 0)}** nearby events"
            f" · closures **{summary.get('closure_count', 0)}**"
            f" · lane **{summary.get('lane_closure_count', 0)}**"
            f" · incidents **{summary.get('incident_count', 0)}**"
            f" · source `{source}`"
        ),
        "",
    ]
    if not features:
        lines.append("No active Caltrans closures / CHP incidents found in the AOI pad.")
        lines.append("")
        lines.append(f"_{DISCLAIMER}_")
        return "\n".join(lines)

    # Prefer closures / closed, then major incidents, then the rest.
    ranked = sorted(
        features,
        key=lambda f: (
            0 if f.get("severity") == "closed" or f.get("kind") == "closure" else 1,
            0 if f.get("kind") == "incident" and f.get("severity") == "major" else 1,
            0 if f.get("status") == "active" else 1,
            str(f.get("title") or ""),
        ),
    )
    lines.append("**Nearest / highest impact** *(click a name to show on map)*")
    for feat in ranked[:8]:
        meta = " · ".join(
            p
            for p in (
                str(feat.get("severity") or ""),
                str(feat.get("status") or ""),
                str(feat.get("source") or ""),
            )
            if p
        )
        desc = feat.get("description")
        bullet = f"- **{road_title_md(feat)}** ({meta})"
        if desc:
            bullet += f" — {desc}"
        lines.append(bullet)
    if len(features) > 8:
        lines.append(f"- …and {len(features) - 8} more on the map RD layer")
    lines.append("")
    lines.append(f"_{DISCLAIMER}_")
    return "\n".join(lines)


def ensure_road_map_links(answer_markdown: str, payload: dict[str, Any]) -> str:
    """Re-attach clickable map links if the LLM stripped them."""
    text = (answer_markdown or "").rstrip()
    if "#map-road" in text:
        return text
    features = list(payload.get("features") or [])
    if not features:
        return text
    ranked = sorted(
        features,
        key=lambda f: (
            0 if f.get("severity") == "closed" or f.get("kind") == "closure" else 1,
            0 if f.get("kind") == "incident" and f.get("severity") == "major" else 1,
            str(f.get("title") or ""),
        ),
    )
    link_lines = []
    for feat in ranked[:8]:
        md = road_title_md(feat)
        if "#map-road" in md:
            link_lines.append(f"- {md}")
    if not link_lines:
        return text
    return (
        f"{text}\n\n**Show on map:**\n" + "\n".join(link_lines)
    )


def get_situation_roads_cached(aoi_id: str) -> dict[str, Any]:
    now = time.time()
    cached = _aoi_cache.get(aoi_id)
    if cached and now - cached[0] < CACHE_TTL_SEC:
        return cached[1]
    payload = build_situation_roads(aoi_id)
    _aoi_cache[aoi_id] = (now, payload)
    return payload


def clear_situation_roads_cache() -> None:
    global _chp_cache
    _aoi_cache.clear()
    _district_cache.clear()
    _chp_cache = None
