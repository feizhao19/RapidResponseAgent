"""Registered tools for the RapidResponseAgent runtime."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from geoagent.agents.facilities_agent import run_facilities
from geoagent.agents.location_agent import run_location
from geoagent.agents.report_agent import format_structured_chat_report, generate_chat_report_summary
from geoagent.agents.report_pipeline_agent import run_report
from geoagent.agents.stats_agent import run_stats
from geoagent.agents.weather_agent import run_weather_context
from geoagent.agents.roads_agent import run_situation_roads
from geoagent.graph.state import PipelineState
from geoagent.runtime.dependencies import (
    build_pipeline_state,
    missing_steps_for_tool,
    prerequisite_chain,
)
from geoagent.runtime.memory import SessionStore
from geoagent.tools.assessment_session import infer_session_aoi_from_history
from geoagent.tools.chat_context import history_for_llm, normalize_history
from geoagent.tools.historical_index import DEFAULT_INDEX_PATH
from geoagent.tools.historical_rag_answer import answer_with_rag
from geoagent.tools.historical_query import execute_query, parse_natural_language, render_answer
from geoagent.tools.intent_router import IntentResult
from geoagent.tools.llm_client import DEFAULT_HF_MODEL, chat

STEP_RUNNERS: dict[str, Callable[[dict[str, Any]], dict]] = {
    "location": run_location,
    "stats": run_stats,
    "facilities": run_facilities,
    "report": run_report,
}


@dataclass
class ToolResult:
    tool: str
    success: bool
    answer_markdown: str = ""
    artifacts_used: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    steps_run: list[str] = field(default_factory=list)


@dataclass
class ToolContext:
    question: str
    session_store: SessionStore
    session_id: str
    active_aoi_id: str | None
    chat_history: list[dict[str, str]]
    intent: IntentResult
    use_llm: bool = True
    retrieve_only: bool = False
    model: str | None = None
    assessment_index: str | None = None
    on_token: Callable[[str], None] | None = None
    on_status: Callable[[dict[str, Any]], None] | None = None


def _resolve_aoi_id(ctx: ToolContext) -> str | None:
    from geoagent.tools.assessment_session import normalize_slot_aoi_id

    slots = ctx.intent.slots or {}
    slot_aoi = normalize_slot_aoi_id(slots.get("aoi_id"))
    # Prefer UI/session selection; allow an explicit AOI id typed in the question.
    if ctx.active_aoi_id:
        if slot_aoi and slot_aoi != ctx.active_aoi_id and slot_aoi in (ctx.question or ""):
            return slot_aoi
        return ctx.active_aoi_id
    if slot_aoi:
        return slot_aoi
    return infer_session_aoi_from_history(ctx.chat_history)


def _run_pipeline_steps(state: dict[str, Any], steps: list[str]) -> tuple[dict[str, Any], list[str]]:
    merged = dict(state)
    ran: list[str] = []
    for step in steps:
        runner = STEP_RUNNERS.get(step)
        if runner is None:
            continue
        updates = runner(merged)  # type: ignore[arg-type]
        merged.update(updates)
        ran.append(step)
    return merged, ran


STATS_CHAT_SYSTEM = """You summarize verified building damage statistics for disaster analysts.
Use ONLY the provided facts. Report the four classes only: No damage, Minor damage, Major damage, Destroyed.
Do not invent or mention aggregate labels like "damaged" or "severe" except when quoting spatial_grid_3x3.damaged_count.
Do not invent FEMA policy definitions; those come from the guidance tool, not from these facts.
When spatial_grid_3x3 is present and the question asks which areas / where / directions are most affected,
lead with the most_affected directions (NW/N/NE/W/Center/E/SW/S/SE) and briefly mention the 3×3 layout.
Keep the answer concise (short bullets). Output markdown only.
"""


def _wants_spatial_areas(question: str) -> bool:
    lowered = (question or "").casefold()
    tokens = (
        "area",
        "areas",
        "where",
        "which part",
        "which side",
        "which area",
        "which areas",
        "handled first",
        "handle first",
        "respond first",
        "priority",
        "prioritize",
        "most urgent",
        "direction",
        "north",
        "south",
        "east",
        "west",
        "northwest",
        "northeast",
        "southwest",
        "southeast",
        "affected most",
        "damaged most",
        "most affected",
        "most damaged",
        "方位",
        "哪里",
        "哪块",
        "哪区",
        "哪个区域",
        "先处理",
        "优先处理",
        "优先处置",
        "东南西北",
        "东西南北",
    )
    return any(token in lowered for token in tokens)

HOSPITALS_CHAT_SYSTEM = """You summarize nearest-hospital lookup results for disaster analysts.
Use ONLY the provided facts. Preserve any markdown map links exactly as given — never truncate a URL or `#map-…` link.
Write a short intro (1 sentence), then markdown headings with bullet lists:
### Nearest hospital
- copy `nearest.name_markdown` exactly, then distance_mi
### Other nearby hospitals
- one bullet per `other_nearby` entry; copy each `name_markdown` exactly and include distance
Keep the answer concise. Output markdown only.
"""

FACILITIES_CHAT_SYSTEM = """You summarize nearest critical-facility lookup results for disaster analysts.
Use ONLY the provided facts (hospitals, fire stations, police, and/or shelters from OpenStreetMap).
Only include facility kinds that appear under facts.by_kind / requested_kinds — if hospitals were excluded, do not mention hospitals.
Write a short natural prose intro (1-2 sentences) for responders, then list facilities under clear markdown headings
(### Hospitals, ### Fire stations, ### Police stations, ### Shelters) — omit headings for kinds not in the facts.
CRITICAL formatting rules:
- Under each heading, use a markdown bullet list (`- ` at the start of every facility line).
- One facility per bullet — never put two facilities on the same line or in a run-on paragraph.
- For each bullet, copy that facility's `line` field exactly (map link + distance), then append phone / website / operator / address
  when those fields are present in the facts — do not invent contacts.
Do not invent facilities. Preserve order within each kind. Never invent padding like "[No other … found]" or
"No other nearby facilities found" when other kinds have results in the facts.
If a kind has fewer results than requested_per_kind, say so briefly.
Keep the answer concise. Output markdown only. Mention the OSM disclaimer briefly at the end.
"""


def _facilities_answer_has_distances(answer: str) -> bool:
    """True when the chat answer still includes mile distances from the lookup."""
    import re

    return bool(re.search(r"\d+(?:\.\d+)?\s*mi\b", answer or "", flags=re.IGNORECASE))


def _facility_contact_bits(item: dict[str, Any]) -> list[str]:
    """Short contact fragments for chat lines (phone / website / operator / address)."""
    bits: list[str] = []
    if item.get("contact_name"):
        bits.append(f"Contact: {item['contact_name']}")
    if item.get("phone"):
        bits.append(f"Phone: {item['phone']}")
    if item.get("email"):
        bits.append(f"Email: {item['email']}")
    if item.get("website"):
        bits.append(f"Website: {item['website']}")
    if item.get("operator"):
        bits.append(f"Operator: {item['operator']}")
    if item.get("address"):
        bits.append(f"Address: {item['address']}")
    if item.get("emergency"):
        bits.append(f"Emergency: {item['emergency']}")
    if item.get("beds"):
        bits.append(f"Beds: {item['beds']}")
    return bits


_FACILITY_LINK_FIELDS = (
    "phone",
    "email",
    "website",
    "operator",
    "contact_name",
    "emergency",
    "beds",
    "opening_hours",
    "address",
    "osm_type",
    "osm_id",
)


def _facility_link_params(item: dict[str, Any]) -> dict[str, str]:
    params: dict[str, str] = {}
    for key in _FACILITY_LINK_FIELDS:
        value = item.get(key)
        if value is not None and value != "":
            params[key] = str(value)
    return params


def _facility_map_href(
    facility: dict[str, Any],
    *,
    kind: str,
    compact: bool = True,
) -> str | None:
    """Build an in-app map deep link. Compact links omit contact query params (map cache fills popup)."""
    from urllib.parse import urlencode

    coords = facility.get("coordinates_wgs84")
    if coords and len(coords) == 2:
        lon, lat = float(coords[0]), float(coords[1])
    elif facility.get("longitude") is not None and facility.get("latitude") is not None:
        lon, lat = float(facility["longitude"]), float(facility["latitude"])
    else:
        return None
    params = {
        "lon": f"{lon:.6f}",
        "lat": f"{lat:.6f}",
        "name": str(facility.get("name") or kind),
        "kind": kind,
    }
    if facility.get("distance_mi") is not None:
        params["distance_mi"] = str(facility["distance_mi"])
    if not compact:
        params.update(_facility_link_params(facility))
    return f"#map-facility?{urlencode(params)}"


def _facility_name_md(
    facility: dict[str, Any],
    *,
    kind: str,
    compact: bool = True,
) -> str:
    name = str(facility.get("name") or "Unknown")
    href = _facility_map_href(facility, kind=kind, compact=compact)
    if href:
        return f"[{name}]({href})"
    return name


def _facility_line(
    item: dict[str, Any],
    *,
    kind: str,
    include_contacts: bool = False,
    compact: bool = True,
) -> str:
    """Map-linked name + distance; optionally append known contacts for fallback markdown."""
    name_md = _facility_name_md(item, kind=kind, compact=compact)
    distance_mi = item.get("distance_mi")
    distance_km = item.get("distance_km")
    if distance_mi is not None:
        line = f"{name_md} — {distance_mi} mi"
    elif distance_km is not None:
        line = f"{name_md} — {distance_km} km"
    else:
        line = name_md
    if include_contacts:
        contacts = _facility_contact_bits(item)
        if contacts:
            line = f"{line} · " + " · ".join(contacts)
    return line


def _facility_catalog_from_payload(
    payload: dict[str, Any],
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Flatten facilities in payload into name / link / distance / contact records."""
    from geoagent.tools.nearest_facilities import ALL_FACILITY_KINDS

    catalog: list[dict[str, Any]] = []
    by_kind = payload.get("by_kind")
    if isinstance(by_kind, dict) and by_kind:
        kinds = list(ALL_FACILITY_KINDS)
    else:
        kinds = [str(payload.get("facility_kind") or "hospital")]
        by_kind = {kinds[0]: payload}

    for kind in kinds:
        kind_payload = by_kind.get(kind) or {}
        if not isinstance(kind_payload, dict):
            continue
        for item in _facility_list_items(kind_payload, kind)[:limit]:
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            name_md = _facility_name_md(item, kind=kind, compact=True)
            distance_mi = item.get("distance_mi")
            catalog.append(
                {
                    "kind": kind,
                    "name": name,
                    "name_markdown": name_md,
                    "distance_mi": distance_mi,
                    "phone": item.get("phone"),
                    "website": item.get("website"),
                    "operator": item.get("operator"),
                    "address": item.get("address"),
                    "line": _facility_line(item, kind=kind, include_contacts=False, compact=True),
                }
            )
    return catalog


def ensure_facility_answer(
    answer_markdown: str,
    payload: dict[str, Any],
    *,
    limit: int = 3,
) -> str:
    """Keep LLM prose, but reinject clickable names + distances when the model strips them.

    Also rebuilds collapsed run-on facility paragraphs into markdown bullet lists.
    """
    import re

    text = (answer_markdown or "").rstrip()
    if not text:
        return text
    catalog = _facility_catalog_from_payload(payload, limit=limit)
    if not catalog:
        return text

    # Longer names first so substrings do not steal replacements.
    for entry in sorted(catalog, key=lambda item: len(str(item["name"])), reverse=True):
        name = str(entry["name"])
        linked = str(entry["name_markdown"])
        distance_mi = entry.get("distance_mi")
        if "#map-" not in linked:
            continue

        # Already a markdown link for this facility — optionally attach missing distance.
        linked_pat = re.compile(
            rf"\[{re.escape(name)}\]\(#map-(?:hospital|facility)\?[^\)]*\)"
            rf"(?:\s*[—\-–]\s*\d+(?:\.\d+)?\s*mi)?",
            re.IGNORECASE,
        )

        def _keep_or_add_distance(match: re.Match[str]) -> str:
            chunk = match.group(0)
            if distance_mi is None:
                return chunk
            if re.search(r"\d+(?:\.\d+)?\s*mi\b", chunk, flags=re.IGNORECASE):
                return chunk
            return f"{linked} — {distance_mi} mi"

        text, linked_hits = linked_pat.subn(_keep_or_add_distance, text)
        if linked_hits:
            continue

        # Plain name → clickable link (+ distance when known).
        plain_pat = re.compile(rf"(?<!\[){re.escape(name)}(?!\]\()")
        replacement = (
            f"{linked} — {distance_mi} mi" if distance_mi is not None else linked
        )
        text = plain_pat.sub(replacement, text)

    if not _facilities_answer_has_bullets(text, catalog):
        text = _rebuild_facilities_answer_with_bullets(text, payload, limit=limit)
    return text


def _has_incomplete_markdown_link(text: str) -> bool:
    """True when a markdown link was cut off mid-write (common when max_new_tokens is hit)."""
    import re

    s = text or ""
    # Unclosed [...]( ...  or bare ](# with no closing )
    if re.search(r"\[[^\]]*$", s):
        return True
    if re.search(r"\]\([^)]*$", s):
        return True
    if s.count("[") != s.count("]"):
        return True
    if s.count("(") != s.count(")"):
        # Map links add many balanced parens; only flag when a ]( opener is unfinished.
        if re.search(r"\]\([^)\n]*$", s):
            return True
    return False


def _facilities_answer_has_bullets(answer: str, catalog: list[dict[str, Any]]) -> bool:
    """True when most catalog facilities already sit on markdown list lines."""
    import re

    if not catalog:
        return True
    if _has_incomplete_markdown_link(answer or ""):
        return False
    list_line = re.compile(r"(?m)^\s*(?:[-*+]|\d+\.)\s+")
    if len(catalog) >= 2 and not list_line.search(answer or ""):
        return False
    listed = 0
    for entry in catalog:
        name = str(entry.get("name") or "")
        if not name:
            continue
        # Match either a list line containing the plain name or the linked form.
        pat = re.compile(
            rf"(?m)^\s*(?:[-*+]|\d+\.)\s+.*{re.escape(name)}",
            re.IGNORECASE,
        )
        if pat.search(answer or ""):
            listed += 1
    if len(catalog) == 1:
        return listed >= 1 or bool(list_line.search(answer or ""))
    return listed >= max(1, (len(catalog) + 1) // 2)


def _rebuild_facilities_answer_with_bullets(
    answer_markdown: str,
    payload: dict[str, Any],
    *,
    limit: int,
) -> str:
    """Preserve a short LLM intro, then emit structured bullet sections from facts."""
    import re

    text = (answer_markdown or "").strip()
    # Cut intro before the first section heading or first known facility name.
    cut_pat = re.compile(
        r"(?im)^(?:#{1,6}\s*)?(?:\*\*)?(?:nearby\s+)?(?:critical\s+)?"
        r"(?:facilities|hospitals?|fire\s+stations?|police(?:\s+stations?)?|shelters?)\b"
    )
    intro = text
    match = cut_pat.search(text)
    if match and match.start() > 0:
        intro = text[: match.start()].strip()
    else:
        # No heading — keep only leading sentences that do not name a facility.
        catalog = _facility_catalog_from_payload(payload, limit=limit)
        first_name_at = None
        for entry in catalog:
            name = str(entry.get("name") or "")
            if not name:
                continue
            found = text.casefold().find(name.casefold())
            if found >= 0 and (first_name_at is None or found < first_name_at):
                first_name_at = found
        if first_name_at is not None and first_name_at > 0:
            intro = text[:first_name_at].strip().rstrip(":").strip()
        else:
            intro = ""

    # Drop leftover heading-only intros like "Nearby Facilities".
    if intro and re.fullmatch(
        r"(?i)(?:nearby\s+)?(?:critical\s+)?facilities\.?",
        intro.strip(" #\t"),
    ):
        intro = ""

    aoi_id = str(payload.get("aoi_id") or "AOI")
    body = _format_facilities_markdown(aoi_id, payload, limit=limit).strip()
    # Prefer a plain "Nearby facilities" title when rebuilding after LLM prose.
    body = re.sub(
        r"^### Nearby critical facilities — `[^`]+`\s*",
        "### Nearby facilities\n\n",
        body,
        count=1,
    )
    if intro:
        # Avoid duplicating an almost-identical title line.
        if re.fullmatch(r"(?i)#*\s*nearby facilities\.?", intro.strip()):
            return body + "\n"
        return f"{intro}\n\n{body}\n"
    return body + "\n"


def _format_stats_markdown(aoi_id: str, stats: dict[str, Any]) -> str:
    from geoagent.tools.damage_levels import format_levels_markdown

    return format_levels_markdown(aoi_id, stats)


def _llm_chat_answer(
    *,
    ctx: ToolContext,
    system: str,
    facts: dict[str, Any],
    fallback: str,
    max_new_tokens: int = 512,
    stream: bool = True,
) -> str:
    from geoagent.runtime.activity_status import emit_answering

    emit_answering(ctx.on_status)
    if not ctx.use_llm:
        return fallback
    history = normalize_history(ctx.chat_history)
    user = (
        f"Question: {ctx.question}\n\n"
        f"Retrieved facts (JSON):\n{json.dumps(facts, indent=2)}\n\n"
        "Write a concise answer grounded only in these facts."
    )
    on_token = ctx.on_token if stream else None
    try:
        text = chat(
            system=system,
            user=user,
            history=history_for_llm(history, max_turns=2),
            model=ctx.model or DEFAULT_HF_MODEL,
            temperature=0.2,
            max_new_tokens=min(max_new_tokens, 2046),
            stream=on_token is not None,
            on_token=on_token,
            echo=False,
        ).strip()
        if text:
            return text
        if on_token is not None and fallback:
            on_token(fallback)
        return fallback
    except Exception as exc:  # noqa: BLE001
        print(f"  Tool LLM skipped ({exc}); using structured answer.", flush=True)
        if on_token is not None and fallback:
            on_token(fallback)
        return fallback


def _emit_answer_once(ctx: ToolContext, answer: str) -> None:
    """Emit a polished answer as one stream chunk (after post-processing)."""
    if ctx.on_token is not None and answer:
        ctx.on_token(answer)


def _hospital_map_href(hospital: dict[str, Any], *, compact: bool = True) -> str | None:
    """Build an in-app map deep link for chat markdown (hash URL, not http)."""
    return _facility_map_href(hospital, kind="hospital", compact=compact)


def _hospital_name_md(hospital: dict[str, Any], *, compact: bool = True) -> str:
    name = str(hospital.get("name") or "Unknown")
    href = _hospital_map_href(hospital, compact=compact)
    if not href:
        return name
    return f"[{name}]({href})"


def _format_hospitals_markdown(aoi_id: str, payload: dict[str, Any]) -> str:
    from geoagent.tools.nearest_facilities import is_named_facility, rank_facilities_for_display

    hospitals = rank_facilities_for_display(payload.get("hospitals") or [])
    nearest = payload.get("nearest") if is_named_facility(payload.get("nearest")) else None
    if nearest is None and hospitals:
        nearest = hospitals[0]
    lines = [f"### Nearest hospitals — `{aoi_id}`", ""]
    if not nearest:
        status = payload.get("status") or "unknown"
        lookup_error = payload.get("lookup_error")
        if status == "unavailable":
            lines.append("Hospital lookup is temporarily unavailable.")
            if lookup_error:
                lines.append(f"- **Reason:** {lookup_error}")
            lines.append("- Ask again in a moment to retry the live OpenStreetMap lookup.")
        else:
            lines.append(f"No hospital results available ({status}).")
        return "\n".join(lines)
    lines.extend(
        [
            f"- **Nearest:** {_hospital_name_md(nearest)}",
            f"- **Distance:** {nearest.get('distance_km', 'n/a')} km ({nearest.get('distance_mi', 'n/a')} mi)",
        ]
    )
    if nearest.get("phone"):
        lines.append(f"- **Phone:** {nearest['phone']}")
    if nearest.get("website"):
        lines.append(f"- **Website:** {nearest['website']}")
    if len(hospitals) > 1:
        lines.append("")
        lines.append("**Other nearby hospitals:**")
        for item in hospitals[1:4]:
            lines.append(
                f"- {_hospital_name_md(item)} — {item.get('distance_km', 'n/a')} km"
            )
    return "\n".join(lines)


def tool_query_historical(ctx: ToolContext) -> ToolResult:
    index_path = Path(ctx.assessment_index or DEFAULT_INDEX_PATH)
    rag_result = answer_with_rag(
        ctx.question,
        index_path=index_path,
        top_k=5,
        use_llm=ctx.use_llm and not ctx.retrieve_only,
        retrieve_only=ctx.retrieve_only,
        chat_history=ctx.chat_history,
        session_aoi_id=ctx.active_aoi_id or _resolve_aoi_id(ctx),
        model=ctx.model or DEFAULT_HF_MODEL,
        verify=ctx.use_llm and not ctx.retrieve_only,
        stream=ctx.on_token is not None,
        on_token=ctx.on_token,
    )
    artifacts = [fact.citation for fact in rag_result.structured_result.facts if fact.citation]
    return ToolResult(
        tool="query_historical",
        success=True,
        answer_markdown=rag_result.answer_markdown,
        artifacts_used=artifacts,
        payload=rag_result.to_dict(),
    )


def tool_get_damage_stats(ctx: ToolContext) -> ToolResult:
    aoi_id = _resolve_aoi_id(ctx)
    if not aoi_id:
        query = parse_natural_language(ctx.question)
        result = execute_query(query, index_path=Path(ctx.assessment_index or DEFAULT_INDEX_PATH))
        return ToolResult(
            tool="get_damage_stats",
            success=True,
            answer_markdown=render_answer(result),
            payload={"matched_aoi_ids": result.matched_aoi_ids},
        )

    aligned_dir = ctx.session_store.aligned_dir_for_aoi(aoi_id)
    if aligned_dir is None:
        return ToolResult(
            tool="get_damage_stats",
            success=False,
            errors=[f"AOI not found in index: {aoi_id}"],
            answer_markdown=f"I could not find indexed artifacts for `{aoi_id}`.",
        )

    missing = missing_steps_for_tool("get_damage_stats", aligned_dir)
    state = build_pipeline_state(aligned_dir, aoi_id, use_llm=False)
    steps_run: list[str] = []
    if missing:
        chain = prerequisite_chain("stats")
        to_run = [step for step in chain if step in ("stats",) or step in missing]
        state, steps_run = _run_pipeline_steps(state, to_run)

    stats_path = Path(state.get("aoi_stats_json") or aligned_dir / "aoi_out" / "aoi_stats.json")
    if not stats_path.is_file():
        return ToolResult(
            tool="get_damage_stats",
            success=False,
            errors=["aoi_stats.json not available"],
            steps_run=steps_run,
        )

    stats = json.loads(stats_path.read_text())
    from geoagent.tools.aoi_stats import ensure_spatial_grid_3x3

    stats = ensure_spatial_grid_3x3(stats, aligned_dir)
    fallback = _format_stats_markdown(aoi_id, stats)
    from geoagent.tools.damage_levels import format_spatial_grid_markdown, levels_facts_payload

    if _wants_spatial_areas(ctx.question):
        spatial_md = format_spatial_grid_markdown(stats)
        if spatial_md:
            fallback = spatial_md + "\n\n" + fallback

    answer = _llm_chat_answer(
        ctx=ctx,
        system=STATS_CHAT_SYSTEM,
        facts={
            "aoi_id": aoi_id,
            "event": stats.get("event"),
            "location": stats.get("location"),
            "question_asks_areas": _wants_spatial_areas(ctx.question),
            **levels_facts_payload(stats),
        },
        fallback=fallback,
        max_new_tokens=768 if _wants_spatial_areas(ctx.question) else 512,
    )
    return ToolResult(
        tool="get_damage_stats",
        success=True,
        answer_markdown=answer,
        artifacts_used=[str(stats_path)],
        payload={"aoi_id": aoi_id, "stats": stats},
        steps_run=steps_run,
    )


def _hospitals_need_refresh(aligned_dir: Path, hospitals_path: Path) -> bool:
    if not hospitals_path.is_file() or hospitals_path.stat().st_size == 0:
        return True
    try:
        payload = json.loads(hospitals_path.read_text())
    except json.JSONDecodeError:
        return True
    # Retry any unavailable cache (Overpass timeouts, missing location, etc.).
    return payload.get("status") == "unavailable"


def tool_find_nearest_hospitals(ctx: ToolContext) -> ToolResult:
    aoi_id = _resolve_aoi_id(ctx)
    if not aoi_id:
        return ToolResult(
            tool="find_nearest_hospitals",
            success=False,
            errors=["No AOI context for hospital lookup"],
            answer_markdown=(
                "Please specify which assessment AOI you mean, or complete an assessment first."
            ),
        )

    aligned_dir = ctx.session_store.aligned_dir_for_aoi(aoi_id)
    if aligned_dir is None:
        return ToolResult(
            tool="find_nearest_hospitals",
            success=False,
            errors=[f"AOI not found: {aoi_id}"],
            answer_markdown=(
                f"I could not find assessment data for `{aoi_id}`. "
                "It may have been deleted from Past assessments."
            ),
        )

    hospitals_path = aligned_dir / "aoi_out" / "nearest_hospitals.json"
    steps_run: list[str] = []
    needs_refresh = _hospitals_need_refresh(aligned_dir, hospitals_path)
    _emit_lookup_progress(ctx, "find_nearest_hospitals", cached=not needs_refresh)
    if needs_refresh:
        # Force a live facilities run; do not resume from an unavailable cache.
        state = build_pipeline_state(aligned_dir, aoi_id, use_llm=False, resume=False)
        to_run: list[str] = []
        if not (aligned_dir / "aoi_out" / "location.json").is_file():
            to_run.append("location")
        to_run.append("facilities")
        state, steps_run = _run_pipeline_steps(state, to_run)
        hospitals_path = Path(state.get("nearest_hospitals_json") or hospitals_path)
        from geoagent.runtime.activity_status import emit_tool_response_received

        emit_tool_response_received(ctx.on_status, "find_nearest_hospitals")

    if not hospitals_path.is_file():
        return ToolResult(
            tool="find_nearest_hospitals",
            success=False,
            errors=["nearest_hospitals.json not available"],
            answer_markdown=(
                f"Hospital lookup data is not available yet for `{aoi_id}`. "
                "Try again in a moment or rerun the facilities step."
            ),
            steps_run=steps_run,
        )

    payload = json.loads(hospitals_path.read_text())
    fallback = _format_hospitals_markdown(aoi_id, payload)
    named = _facility_list_items(payload, "hospital")
    nearest = named[0] if named else {}
    facts: dict[str, Any] = {
        "aoi_id": aoi_id,
        "status": payload.get("status"),
        "nearest": {
            "name_markdown": _hospital_name_md(nearest) if nearest else None,
            "distance_km": nearest.get("distance_km"),
            "distance_mi": nearest.get("distance_mi"),
            "phone": nearest.get("phone"),
            "website": nearest.get("website"),
        }
        if nearest
        else None,
        "other_nearby": [
            {
                "name_markdown": _hospital_name_md(item),
                "distance_km": item.get("distance_km"),
            }
            for item in named[1:4]
        ],
    }
    answer = _llm_chat_answer(
        ctx=ctx,
        system=HOSPITALS_CHAT_SYSTEM,
        facts=facts,
        fallback=fallback,
        # Long #map-hospital?… links for 4 hospitals easily exceed the default 512
        # and get cut mid-URL (e.g. `[Name](#`).
        max_new_tokens=1536,
        stream=True,
    )
    polished = ensure_facility_answer(answer or "", payload, limit=4)
    if (
        not polished
        or _has_incomplete_markdown_link(polished)
        or "[no other" in polished.casefold()
    ):
        answer = fallback
        _emit_answer_once(ctx, answer)
    else:
        answer = polished
    return ToolResult(
        tool="find_nearest_hospitals",
        success=True,
        answer_markdown=answer,
        artifacts_used=[str(hospitals_path)],
        payload=payload,
        steps_run=steps_run,
    )


def _facility_list_items(
    kind_payload: dict[str, Any],
    kind: str,
    *,
    prefer_named: bool = True,
) -> list[dict[str, Any]]:
    from geoagent.tools.nearest_facilities import FACILITY_SPECS, rank_facilities_for_display

    spec = FACILITY_SPECS.get(kind) or FACILITY_SPECS["hospital"]  # type: ignore[arg-type]
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


def _requested_facility_count(question: str, *, default: int = 3) -> int:
    """Honor asks like 'give me three options' while capping Overpass load."""
    import re

    lowered = (question or "").casefold()
    word_map = {
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
    }
    for word, count in word_map.items():
        if word in lowered:
            return count
    match = re.search(r"\bat least\s+(\d+)\b", lowered) or re.search(
        r"\b(\d+)\s+(?:options?|results?|facilit)",
        lowered,
    )
    if match:
        return max(1, min(int(match.group(1)), 8))
    return default


def _format_facilities_markdown(
    aoi_id: str,
    payload: dict[str, Any],
    *,
    limit: int = 3,
) -> str:
    from geoagent.tools.nearest_facilities import ALL_FACILITY_KINDS, FACILITY_SPECS

    if payload.get("facility_kind") == "all" or payload.get("by_kind"):
        lines = [f"### Nearby critical facilities — `{aoi_id}`", ""]
        by_kind = payload.get("by_kind") or {}
        # Honor a filtered by_kind (e.g. "other than hospitals") — do not invent missing kinds.
        kinds_order = [k for k in ALL_FACILITY_KINDS if k in by_kind] or list(ALL_FACILITY_KINDS)
        for kind in kinds_order:
            kind_payload = by_kind.get(kind) or {}
            spec = FACILITY_SPECS[kind]
            label = spec["label_plural"]
            lines.append(f"**{label.capitalize()}**")
            if kind_payload.get("status") == "unavailable":
                err = kind_payload.get("lookup_error") or "lookup unavailable"
                lines.append(f"- No {label} results ({err})")
                lines.append("")
                continue
            items = _facility_list_items(kind_payload, kind)[:limit]
            if not items:
                lines.append(f"- None found within the search radius")
            else:
                for item in items:
                    lines.append(
                        f"- {_facility_line(item, kind=kind, include_contacts=True, compact=True)}"
                    )
                if len(items) < limit:
                    lines.append(
                        f"_Only {len(items)} {label} found in OpenStreetMap within the search radius._"
                    )
            lines.append("")
        if payload.get("disclaimer"):
            lines.append(f"_{payload['disclaimer']}_")
        return "\n".join(lines).rstrip() + "\n"

    kind = str(payload.get("facility_kind") or "hospital")
    spec = FACILITY_SPECS.get(kind) or FACILITY_SPECS["hospital"]  # type: ignore[arg-type]
    label = spec["label_plural"]
    lines = [f"### Nearest {label} — `{aoi_id}`", ""]
    status = payload.get("status")
    if status == "unavailable":
        err = payload.get("lookup_error") or "lookup unavailable"
        lines.append(f"No {label} results available ({err}).")
        return "\n".join(lines)

    items = _facility_list_items(payload, kind)[:limit]
    if not items:
        lines.append(f"No {label} found within the search radius.")
    else:
        for item in items:
            lines.append(
                f"- {_facility_line(item, kind=kind, include_contacts=True, compact=True)}"
            )
        if len(items) < limit:
            lines.append(
                f"_Only {len(items)} {label} found in OpenStreetMap within the search radius._"
            )
    if payload.get("disclaimer"):
        lines.extend(["", f"_{payload['disclaimer']}_"])
    return "\n".join(lines)


def _facilities_need_refresh(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size == 0:
        return True
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError:
        return True
    return payload.get("status") == "unavailable"


def _all_payload_min_count(payload: dict[str, Any]) -> int:
    by_kind = payload.get("by_kind") or {}
    if not by_kind:
        return 0
    counts = []
    for kind, kind_payload in by_kind.items():
        if not isinstance(kind_payload, dict):
            continue
        if kind_payload.get("status") == "unavailable":
            continue
        counts.append(len(_facility_list_items(kind_payload, str(kind))))
    return min(counts) if counts else 0


def _facility_facts_for_kind(kind_payload: dict[str, Any], kind: str, *, limit: int) -> dict[str, Any]:
    items = _facility_list_items(kind_payload, kind)[:limit]
    nearby: list[dict[str, Any]] = []
    for item in items:
        nearby.append(
            {
                "name_markdown": _facility_name_md(item, kind=kind, compact=True),
                "distance_mi": item.get("distance_mi"),
                "distance_km": item.get("distance_km"),
                # Compact line for the LLM — contacts stay as separate fields for prose.
                "line": _facility_line(item, kind=kind, include_contacts=False, compact=True),
                "phone": item.get("phone"),
                "email": item.get("email"),
                "website": item.get("website"),
                "operator": item.get("operator"),
                "address": item.get("address"),
                "emergency": item.get("emergency"),
                "beds": item.get("beds"),
            }
        )
    return {
        "status": kind_payload.get("status"),
        "found_count": len(_facility_list_items(kind_payload, kind)),
        "nearby": nearby,
    }


def _emit_lookup_progress(ctx: ToolContext, tool_name: str, *, cached: bool) -> None:
    from geoagent.runtime.activity_status import (
        emit_status,
        emit_tool_request,
        emit_tool_response_received,
        emit_tool_waiting,
        make_status,
        tool_phase,
    )

    if cached:
        emit_status(
            ctx.on_status,
            make_status(
                phase=tool_phase(tool_name),
                label="Using cached results…",
                tool=tool_name,
                step="await_response",
                status="running",
            ),
        )
        emit_tool_response_received(ctx.on_status, tool_name)
        return
    emit_tool_request(ctx.on_status, tool_name)
    emit_tool_waiting(ctx.on_status, tool_name)


def _sync_per_kind_facility_caches(aligned_dir: Path, payload: dict[str, Any]) -> None:
    """Write successful per-kind caches from a combined facilities payload."""
    from geoagent.tools.nearest_facilities import ALL_FACILITY_KINDS, cache_path_for_kind

    by_kind = payload.get("by_kind") or {}
    for kind in ALL_FACILITY_KINDS:
        kind_payload = by_kind.get(kind)
        if not isinstance(kind_payload, dict) or kind_payload.get("status") != "ok":
            continue
        path = cache_path_for_kind(aligned_dir, kind)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(kind_payload, indent=2) + "\n")
        except OSError as exc:
            print(f"  Could not sync {kind} facility cache: {exc}", flush=True)


def _resolve_facility_kinds(ctx: ToolContext) -> list[str]:
    """Which facility kinds to fetch for this turn (may exclude hospitals)."""
    from geoagent.tools.nearest_facilities import resolve_facility_kinds

    slots = ctx.intent.slots if ctx.intent is not None else None
    return list(resolve_facility_kinds(ctx.question, slots=slots if isinstance(slots, dict) else None))


def _resolve_facility_kind(ctx: ToolContext) -> str | None:
    """Legacy single-kind resolver; returns 'all' when multiple kinds are requested."""
    kinds = _resolve_facility_kinds(ctx)
    if len(kinds) == 1:
        return kinds[0]
    return "all"


def tool_find_nearest_facilities(ctx: ToolContext) -> ToolResult:
    """Live OSM Overpass lookup for fire / police / shelter / hospital (or all)."""
    from geoagent.tools.nearest_facilities import (
        ALL_FACILITY_KINDS,
        FACILITY_SPECS,
        cache_path_for_kind,
        find_all_nearest_facilities,
        find_nearest_facilities,
        load_location_centroid,
        unavailable_facilities_payload,
    )

    kind = _resolve_facility_kind(ctx)
    wanted_kinds = _resolve_facility_kinds(ctx)

    aoi_id = _resolve_aoi_id(ctx)
    if not aoi_id:
        return ToolResult(
            tool="find_nearest_facilities",
            success=False,
            errors=["No AOI context for facility lookup"],
            answer_markdown=(
                "Please specify which assessment AOI you mean, or complete an assessment first."
            ),
        )

    aligned_dir = ctx.session_store.aligned_dir_for_aoi(aoi_id)
    if aligned_dir is None:
        return ToolResult(
            tool="find_nearest_facilities",
            success=False,
            errors=[f"AOI not found: {aoi_id}"],
            answer_markdown=(
                f"I could not find assessment data for `{aoi_id}`. "
                "It may have been deleted from Past assessments."
            ),
        )

    steps_run: list[str] = []
    location_path = aligned_dir / "aoi_out" / "location.json"
    if not location_path.is_file():
        state = build_pipeline_state(aligned_dir, aoi_id, use_llm=False, resume=False)
        state, steps_run = _run_pipeline_steps(state, ["location"])

    if kind == "all" or len(wanted_kinds) > 1:
        requested = _requested_facility_count(ctx.question, default=3)
        cache_path = aligned_dir / "aoi_out" / "nearest_facilities_all.json"
        payload: dict[str, Any]
        cached_payload: dict[str, Any] | None = None
        if cache_path.is_file() and cache_path.stat().st_size > 0:
            try:
                cached_payload = json.loads(cache_path.read_text())
            except json.JSONDecodeError:
                cached_payload = None
        from geoagent.tools.nearest_facilities import (
            merge_per_kind_caches_into_combined,
            refresh_unavailable_facility_kinds,
        )

        def _wanted_missing(combined: dict[str, Any] | None) -> list[str]:
            by_kind_local = (combined or {}).get("by_kind") or {}
            return [
                k
                for k in wanted_kinds
                if (by_kind_local.get(k) or {}).get("status") != "ok"
            ]

        wanted_ok_counts = []
        if cached_payload is not None:
            for k in wanted_kinds:
                by = ((cached_payload.get("by_kind") or {}).get(k) or {})
                if isinstance(by, dict) and by.get("status") == "ok":
                    wanted_ok_counts.append(len(_facility_list_items(by, str(k))))
        needs_full_refresh = _facilities_need_refresh(cache_path) or (
            bool(wanted_ok_counts) and min(wanted_ok_counts) < requested
        )
        # Prefer per-kind caches (e.g. nearest_shelters.json) before any Overpass retry.
        merged_payload = cached_payload
        still_needs_network = False
        if not needs_full_refresh and cached_payload is not None:
            before_missing = _wanted_missing(cached_payload)
            merged_payload, _still_all = merge_per_kind_caches_into_combined(
                cached_payload, aligned_dir
            )
            still_missing = _wanted_missing(merged_payload)
            still_needs_network = bool(still_missing)
            if len(still_missing) < len(before_missing):
                # Filled holes from disk cache — persist combined snapshot.
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps(merged_payload, indent=2) + "\n")

        _emit_lookup_progress(
            ctx,
            "find_nearest_facilities",
            cached=not (needs_full_refresh or still_needs_network),
        )
        if needs_full_refresh:
            try:
                location = json.loads(location_path.read_text()) if location_path.is_file() else None
                if not location:
                    raise FileNotFoundError(f"missing location.json for {aoi_id}")
                centroid, display_name = load_location_centroid(location)
                payload = find_all_nearest_facilities(
                    centroid_wgs84=centroid,
                    aoi_id=aoi_id,
                    display_name=display_name or location.get("display_name"),
                    limit_per_kind=requested,
                    kinds=wanted_kinds,  # type: ignore[arg-type]
                    aligned_dir=aligned_dir,
                )
            except Exception as exc:  # noqa: BLE001
                payload = {
                    "facility_kind": "all",
                    "status": "unavailable",
                    "lookup_error": str(exc),
                    "by_kind": {
                        k: unavailable_facilities_payload(k, aoi_id=aoi_id, lookup_error=str(exc))
                        for k in wanted_kinds
                    },
                    "disclaimer": (
                        "Facilities are sourced from OpenStreetMap community data and may be "
                        "incomplete or outdated."
                    ),
                }
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(payload, indent=2) + "\n")
            _sync_per_kind_facility_caches(aligned_dir, payload)
            from geoagent.runtime.activity_status import emit_tool_response_received

            emit_tool_response_received(ctx.on_status, "find_nearest_facilities")
        elif still_needs_network:
            try:
                location = json.loads(location_path.read_text()) if location_path.is_file() else None
                if not location:
                    raise FileNotFoundError(f"missing location.json for {aoi_id}")
                centroid, display_name = load_location_centroid(location)
                payload = refresh_unavailable_facility_kinds(
                    merged_payload or {},
                    centroid_wgs84=centroid,
                    aoi_id=aoi_id,
                    display_name=display_name or location.get("display_name"),
                    limit_per_kind=requested,
                    aligned_dir=aligned_dir,
                    kinds=wanted_kinds,  # type: ignore[arg-type]
                )
            except Exception as exc:  # noqa: BLE001
                print(f"  Partial facility refresh failed ({exc}); using cache", flush=True)
                payload = merged_payload or cached_payload or {}
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(payload, indent=2) + "\n")
            _sync_per_kind_facility_caches(aligned_dir, payload)
            from geoagent.runtime.activity_status import emit_tool_response_received

            emit_tool_response_received(ctx.on_status, "find_nearest_facilities")
        else:
            payload = merged_payload or cached_payload or json.loads(cache_path.read_text())

        # Answer only with the kinds this question asked for (e.g. exclude hospitals).
        display_payload = dict(payload)
        by_kind_full = dict(payload.get("by_kind") or {})
        display_payload["by_kind"] = {
            k: by_kind_full[k] for k in wanted_kinds if k in by_kind_full
        }

        fallback = _format_facilities_markdown(aoi_id, display_payload, limit=requested)
        by_kind = display_payload.get("by_kind") or {}
        facts: dict[str, Any] = {
            "aoi_id": aoi_id,
            "facility_kind": "all",
            "requested_kinds": wanted_kinds,
            "requested_per_kind": requested,
            "status": payload.get("status"),
            "disclaimer": payload.get("disclaimer"),
            "by_kind": {
                k: _facility_facts_for_kind(by_kind.get(k) or {}, k, limit=requested)
                for k in wanted_kinds
            },
        }
        answer = _llm_chat_answer(
            ctx=ctx,
            system=FACILITIES_CHAT_SYSTEM,
            facts=facts,
            fallback=fallback,
            max_new_tokens=2046,
            stream=True,
        )
        # Keep LLM prose when possible; only hard-fallback on empty / padded junk.
        lowered = (answer or "").casefold()
        if not answer or "[no other" in lowered:
            answer = fallback
            _emit_answer_once(ctx, answer)
        else:
            # Polish stored answer (stream already showed live tokens).
            answer = ensure_facility_answer(answer, display_payload, limit=requested)
        return ToolResult(
            tool="find_nearest_facilities",
            success=payload.get("status") == "ok",
            answer_markdown=answer,
            artifacts_used=[str(cache_path)],
            payload=display_payload,
            steps_run=steps_run,
            errors=[]
            if payload.get("status") == "ok"
            else [str(payload.get("lookup_error") or "unavailable")],
        )

    cache_path = cache_path_for_kind(aligned_dir, kind)  # type: ignore[arg-type]
    needs_refresh = _facilities_need_refresh(cache_path)
    _emit_lookup_progress(ctx, "find_nearest_facilities", cached=not needs_refresh)
    if needs_refresh:
        try:
            location = json.loads(location_path.read_text()) if location_path.is_file() else None
            if not location:
                raise FileNotFoundError(f"missing location.json for {aoi_id}")
            centroid, display_name = load_location_centroid(location)
            payload = find_nearest_facilities(
                kind,  # type: ignore[arg-type]
                centroid_wgs84=centroid,
                aoi_id=aoi_id,
                display_name=display_name or location.get("display_name"),
            )
        except Exception as exc:  # noqa: BLE001
            payload = unavailable_facilities_payload(
                kind,  # type: ignore[arg-type]
                aoi_id=aoi_id,
                lookup_error=str(exc),
            )
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload, indent=2) + "\n")
        from geoagent.runtime.activity_status import emit_tool_response_received

        emit_tool_response_received(ctx.on_status, "find_nearest_facilities")
    else:
        payload = json.loads(cache_path.read_text())

    fallback = _format_facilities_markdown(aoi_id, payload)
    items = _facility_list_items(payload, str(kind))
    nearest = items[0] if items else {}
    facts = {
        "aoi_id": aoi_id,
        "facility_kind": kind,
        "status": payload.get("status"),
        "disclaimer": payload.get("disclaimer"),
        "nearest": {
            "name_markdown": _facility_name_md(nearest, kind=str(kind)) if nearest else None,
            "distance_km": nearest.get("distance_km"),
            "distance_mi": nearest.get("distance_mi"),
            "phone": nearest.get("phone"),
            "website": nearest.get("website"),
        }
        if nearest
        else None,
        "other_nearby": [
            {
                "name_markdown": _facility_name_md(item, kind=str(kind)),
                "distance_km": item.get("distance_km"),
            }
            for item in items[1:4]
        ],
    }
    answer = _llm_chat_answer(
        ctx=ctx,
        system=FACILITIES_CHAT_SYSTEM,
        facts=facts,
        fallback=fallback,
        stream=True,
    )
    if not answer:
        answer = fallback
        _emit_answer_once(ctx, answer)
    else:
        answer = ensure_facility_answer(answer, payload, limit=3)
    # Ensure chat keeps a clickable map deep-link even if nothing matched by name.
    nearest_md = facts.get("nearest", {}) or {}
    link_md = nearest_md.get("name_markdown") if isinstance(nearest_md, dict) else None
    if link_md and "#map-" not in answer:
        answer = f"{answer.rstrip()}\n\n**Show on map:** {link_md}"
        if ctx.on_token is not None:
            ctx.on_token(f"\n\n**Show on map:** {link_md}")
    return ToolResult(
        tool="find_nearest_facilities",
        success=payload.get("status") == "ok",
        answer_markdown=answer,
        artifacts_used=[str(cache_path)],
        payload=payload,
        steps_run=steps_run,
        errors=[] if payload.get("status") == "ok" else [str(payload.get("lookup_error") or "unavailable")],
    )


def _load_json_if_present(path: Path) -> dict[str, Any] | None:
    if not path.is_file() or path.stat().st_size <= 0:
        return None
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _load_report_support_context(
    aligned_dir: Path,
    stats: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    """Enrich stats with 3×3 grid and load facilities + mission priority for full reports."""
    from geoagent.tools.aoi_stats import ensure_spatial_grid_3x3
    from geoagent.tools.mission_priority import build_mission_priority
    from geoagent.tools.nearest_facilities import (
        ALL_FACILITY_KINDS,
        FacilityKind,
        cache_path_for_kind,
        load_ok_kind_cache,
    )

    stats = ensure_spatial_grid_3x3(stats, aligned_dir)
    aoi_out = aligned_dir / "aoi_out"
    hospitals = _load_json_if_present(aoi_out / "nearest_hospitals.json")
    facilities = _load_json_if_present(aoi_out / "nearest_facilities_all.json")
    if facilities is None:
        by_kind: dict[str, dict[str, Any]] = {}
        for kind in ALL_FACILITY_KINDS:
            kind_t: FacilityKind = kind
            cached = load_ok_kind_cache(aligned_dir, kind_t)
            if cached is None:
                cached = _load_json_if_present(Path(cache_path_for_kind(aligned_dir, kind_t)))
            if cached:
                by_kind[kind] = cached
        if by_kind:
            facilities = {
                "facility_kind": "all",
                "status": "ok",
                "by_kind": by_kind,
                "aoi_id": str(stats.get("aoi_id") or aligned_dir.name),
            }
    if hospitals is None and facilities and (facilities.get("by_kind") or {}).get("hospital"):
        hospitals = (facilities.get("by_kind") or {}).get("hospital")

    mission = build_mission_priority(
        stats,
        facilities_payload=facilities,
        hospitals_payload=hospitals,
    )
    return stats, hospitals, facilities, mission


def tool_generate_report(ctx: ToolContext) -> ToolResult:
    aoi_id = _resolve_aoi_id(ctx)
    if not aoi_id:
        return ToolResult(
            tool="generate_report",
            success=False,
            errors=["No AOI context for report generation"],
            answer_markdown="Please specify which assessment should receive a report.",
        )

    aligned_dir = ctx.session_store.aligned_dir_for_aoi(aoi_id)
    if aligned_dir is None:
        return ToolResult(
            tool="generate_report",
            success=False,
            errors=[f"AOI not found: {aoi_id}"],
        )

    state = build_pipeline_state(
        aligned_dir,
        aoi_id,
        # Artifact report stays template-based; chat answer uses a compact LLM brief.
        use_llm=False,
        llm_model=ctx.model or DEFAULT_HF_MODEL,
    )
    steps_run: list[str] = []
    missing = missing_steps_for_tool("generate_report", aligned_dir)
    if missing:
        prereq = prerequisite_chain("report")
        to_run = [step for step in prereq if step in ("stats", "facilities", "report")]
        state, steps_run = _run_pipeline_steps(state, to_run)
    elif not (aligned_dir / "aoi_out" / "assessment_report_official.md").is_file():
        state, steps_run = _run_pipeline_steps(state, ["report"])

    report_path = Path(
        state.get("assessment_report")
        or aligned_dir / "aoi_out" / "assessment_report_official.md"
    )
    if not report_path.is_file():
        legacy = aligned_dir / "aoi_out" / "assessment_report.md"
        report_path = legacy if legacy.is_file() else report_path

    stats_path = aligned_dir / "aoi_out" / "aoi_stats.json"
    if not stats_path.is_file() and not report_path.is_file():
        return ToolResult(
            tool="generate_report",
            success=False,
            errors=["assessment report not available"],
            steps_run=steps_run,
        )

    markdown = report_path.read_text() if report_path.is_file() else ""
    hospitals: dict[str, Any] | None = None
    facilities: dict[str, Any] | None = None
    mission: dict[str, Any] | None = None
    stats: dict[str, Any] | None = None
    if stats_path.is_file():
        try:
            stats = json.loads(stats_path.read_text())
            stats, hospitals, facilities, mission = _load_report_support_context(
                aligned_dir, stats
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  Report support context skipped ({exc})", flush=True)
            stats = None

    # Prefer a complete chat report (damage + Mission Priority + facilities).
    if stats is not None:
        structured = format_structured_chat_report(
            stats,
            hospitals=hospitals,
            facilities=facilities,
            mission_priority=mission,
        )
        if ctx.use_llm:
            try:
                markdown = generate_chat_report_summary(
                    stats,
                    question=ctx.question,
                    hospitals=hospitals,
                    facilities=facilities,
                    mission_priority=mission,
                    model=ctx.model or DEFAULT_HF_MODEL,
                    stream=ctx.on_token is not None,
                    on_token=ctx.on_token,
                )
            except Exception as exc:  # noqa: BLE001
                print(
                    f"  Report chat LLM skipped ({exc}); using structured full report.",
                    flush=True,
                )
                markdown = structured
        else:
            markdown = structured
    elif len(markdown) > 1500:
        markdown = markdown[:1500].rstrip() + "\n\n_…report truncated for chat._\n"

    return ToolResult(
        tool="generate_report",
        success=True,
        answer_markdown=markdown,
        artifacts_used=[str(report_path)] if report_path.is_file() else [str(stats_path)],
        payload={
            "aoi_id": aoi_id,
            "report_path": str(report_path) if report_path.is_file() else None,
            "includes_mission_priority": bool(mission and mission.get("priorities")),
        },
        steps_run=steps_run,
    )


def tool_weather_context(ctx: ToolContext) -> ToolResult:
    aoi_id = ctx.active_aoi_id or _resolve_aoi_id(ctx)
    state: PipelineState = {
        "user_input": ctx.question,
        "weather_question": ctx.question,
        "chat_history": ctx.chat_history,
        "use_llm": ctx.use_llm,
        "intent_slots": ctx.intent.slots,
        "llm_model": ctx.model or DEFAULT_HF_MODEL,
        "on_token": ctx.on_token,
    }
    if aoi_id:
        state["aoi_id"] = aoi_id
    updates = run_weather_context(state)
    weather_path = updates.get("weather_answer_json")
    payload: dict[str, Any] = {}
    if weather_path and Path(weather_path).is_file():
        payload = json.loads(Path(weather_path).read_text())
    return ToolResult(
        tool="weather_context",
        success=True,
        answer_markdown=payload.get("answer_markdown", ""),
        artifacts_used=[str(weather_path)] if weather_path else [],
        payload=payload,
    )


def tool_situation_roads(ctx: ToolContext) -> ToolResult:
    from geoagent.runtime.activity_status import (
        emit_tool_request,
        emit_tool_response_received,
        emit_tool_waiting,
    )

    aoi_id = ctx.active_aoi_id or _resolve_aoi_id(ctx)
    if not aoi_id:
        return ToolResult(
            tool="situation_roads",
            success=False,
            errors=["missing_active_aoi"],
            answer_markdown="Select a past assessment AOI, then ask about road closures again.",
        )
    emit_tool_request(ctx.on_status, "situation_roads")
    emit_tool_waiting(ctx.on_status, "situation_roads")
    state: PipelineState = {
        "user_input": ctx.question,
        "chat_history": ctx.chat_history,
        "use_llm": ctx.use_llm,
        "intent_slots": ctx.intent.slots,
        "llm_model": ctx.model or DEFAULT_HF_MODEL,
        "on_token": ctx.on_token,
        "aoi_id": aoi_id,
    }
    try:
        updates = run_situation_roads(state)
    except Exception as exc:  # noqa: BLE001
        emit_tool_response_received(ctx.on_status, "situation_roads")
        return ToolResult(
            tool="situation_roads",
            success=False,
            errors=[str(exc)],
            answer_markdown=f"Road conditions lookup failed: {exc}",
        )
    emit_tool_response_received(ctx.on_status, "situation_roads")
    roads_path = updates.get("roads_answer_json")
    payload: dict[str, Any] = {}
    if roads_path and Path(roads_path).is_file():
        payload = json.loads(Path(roads_path).read_text())
    return ToolResult(
        tool="situation_roads",
        success=True,
        answer_markdown=payload.get("answer_markdown") or updates.get("answer_markdown") or "",
        artifacts_used=[str(roads_path)] if roads_path else [],
        payload=payload,
        steps_run=list(updates.get("completed_steps") or []),
    )


def tool_query_guidance(ctx: ToolContext) -> ToolResult:
    from geoagent.tools.knowledge_rag import answer_guidance_question

    payload = answer_guidance_question(
        ctx.question,
        use_llm=ctx.use_llm,
        model=ctx.model or DEFAULT_HF_MODEL,
        on_token=ctx.on_token,
    )
    citations = payload.get("citations") or []
    artifacts = [
        str(item.get("source_url") or item.get("doc_id") or "")
        for item in citations
        if item.get("source_url") or item.get("doc_id")
    ]
    return ToolResult(
        tool="query_guidance",
        success=bool(citations),
        answer_markdown=payload.get("answer_markdown") or "",
        artifacts_used=artifacts,
        payload=payload,
        errors=[] if citations else ["knowledge_index_no_hit"],
    )


def tool_get_mission_priority(ctx: ToolContext) -> ToolResult:
    """EOC-style Priority 1/2/3 from 3x3 damage + nearest hospital/fire."""
    from geoagent.runtime.activity_status import (
        emit_tool_request,
        emit_tool_response_received,
        emit_tool_waiting,
    )
    from geoagent.tools.aoi_stats import ensure_spatial_grid_3x3
    from geoagent.tools.mission_priority import (
        MISSION_PRIORITY_CHAT_SYSTEM,
        build_mission_priority,
        ensure_mission_facility_map_links,
        format_mission_priority_markdown,
        mission_priority_facts,
    )
    from geoagent.tools.nearest_facilities import (
        find_all_nearest_facilities,
        load_location_centroid,
        unavailable_facilities_payload,
        ALL_FACILITY_KINDS,
        FacilityKind,
    )

    aoi_id = _resolve_aoi_id(ctx)
    if not aoi_id:
        return ToolResult(
            tool="get_mission_priority",
            success=False,
            errors=["No AOI context for mission priority"],
            answer_markdown=(
                "Please select an assessment AOI (or finish an assessment) before "
                "asking for Mission Priority."
            ),
        )

    aligned_dir = ctx.session_store.aligned_dir_for_aoi(aoi_id)
    if aligned_dir is None:
        return ToolResult(
            tool="get_mission_priority",
            success=False,
            errors=[f"AOI not found in index: {aoi_id}"],
            answer_markdown=f"I could not find indexed artifacts for `{aoi_id}`.",
        )

    emit_tool_request(ctx.on_status, "get_mission_priority")
    emit_tool_waiting(ctx.on_status, "get_mission_priority")

    steps_run: list[str] = []
    missing = missing_steps_for_tool("get_mission_priority", aligned_dir)
    state = build_pipeline_state(aligned_dir, aoi_id, use_llm=False)
    if missing:
        chain = prerequisite_chain("stats")
        to_run = [step for step in chain if step in ("stats",) or step in missing]
        state, steps_run = _run_pipeline_steps(state, to_run)

    stats_path = Path(state.get("aoi_stats_json") or aligned_dir / "aoi_out" / "aoi_stats.json")
    if not stats_path.is_file():
        return ToolResult(
            tool="get_mission_priority",
            success=False,
            errors=["aoi_stats.json not available"],
            steps_run=steps_run,
            answer_markdown=(
                f"Damage statistics are not available yet for `{aoi_id}`. "
                "Run or finish the assessment first."
            ),
        )

    stats = json.loads(stats_path.read_text())
    stats = ensure_spatial_grid_3x3(stats, aligned_dir)
    emit_tool_response_received(ctx.on_status, "get_mission_priority")

    facilities_payload: dict[str, Any] | None = None
    hospitals_payload: dict[str, Any] | None = None
    facility_paths: list[str] = []

    all_cache = aligned_dir / "aoi_out" / "nearest_facilities_all.json"
    hospitals_path = aligned_dir / "aoi_out" / "nearest_hospitals.json"
    location_path = aligned_dir / "aoi_out" / "location.json"

    # Mission priority only needs hospital + fire; avoid waiting on police/shelter Overpass.
    mission_kinds: list[FacilityKind] = ["hospital", "fire_station"]

    if all_cache.is_file() and all_cache.stat().st_size > 0 and not _facilities_need_refresh(all_cache):
        try:
            facilities_payload = json.loads(all_cache.read_text())
            facility_paths.append(str(all_cache))
            by_kind = facilities_payload.get("by_kind") or {}
            # Combined cache may be incomplete for the kinds we need — fall through to refresh.
            if any((by_kind.get(k) or {}).get("status") != "ok" for k in mission_kinds):
                facilities_payload = None
        except json.JSONDecodeError:
            facilities_payload = None

    if facilities_payload is None:
        from geoagent.tools.nearest_facilities import (
            load_ok_kind_cache,
            merge_per_kind_caches_into_combined,
        )

        cache_hit = all(
            load_ok_kind_cache(aligned_dir, kind) is not None for kind in mission_kinds
        )
        _emit_lookup_progress(ctx, "find_nearest_facilities", cached=cache_hit)
        try:
            if not location_path.is_file():
                state = build_pipeline_state(aligned_dir, aoi_id, use_llm=False, resume=False)
                state, more = _run_pipeline_steps(state, ["location"])
                steps_run.extend(more)
            location = json.loads(location_path.read_text()) if location_path.is_file() else None
            if not location:
                raise FileNotFoundError(f"missing location.json for {aoi_id}")
            centroid, display_name = load_location_centroid(location)
            facilities_payload = find_all_nearest_facilities(
                centroid_wgs84=centroid,
                aoi_id=aoi_id,
                display_name=display_name or location.get("display_name"),
                limit_per_kind=5,
                kinds=mission_kinds,
                aligned_dir=aligned_dir,
            )
            # If only hospital/fire were requested, merge any other per-kind caches for completeness.
            facilities_payload, _ = merge_per_kind_caches_into_combined(
                facilities_payload, aligned_dir
            )
            all_cache.parent.mkdir(parents=True, exist_ok=True)
            all_cache.write_text(json.dumps(facilities_payload, indent=2) + "\n")
            _sync_per_kind_facility_caches(aligned_dir, facilities_payload)
            facility_paths.append(str(all_cache))
            if not cache_hit:
                emit_tool_response_received(ctx.on_status, "find_nearest_facilities")
        except Exception as exc:  # noqa: BLE001
            facilities_payload = {
                "facility_kind": "all",
                "status": "unavailable",
                "lookup_error": str(exc),
                "by_kind": {
                    k: unavailable_facilities_payload(k, aoi_id=aoi_id, lookup_error=str(exc))
                    for k in ALL_FACILITY_KINDS
                },
            }
            if hospitals_path.is_file():
                try:
                    hospitals_payload = json.loads(hospitals_path.read_text())
                    facility_paths.append(str(hospitals_path))
                except json.JSONDecodeError:
                    hospitals_payload = None

    mission = build_mission_priority(
        stats,
        facilities_payload=facilities_payload,
        hospitals_payload=hospitals_payload,
    )
    fallback = format_mission_priority_markdown(mission)
    answer = _llm_chat_answer(
        ctx=ctx,
        system=MISSION_PRIORITY_CHAT_SYSTEM,
        facts=mission_priority_facts(mission),
        fallback=fallback,
        max_new_tokens=2046,
    )
    # Keep Priority 1/2/3 structure if the model drifts.
    if ctx.use_llm and "priority 1" not in (answer or "").casefold():
        answer = fallback
    answer = ensure_mission_facility_map_links(answer, mission)

    artifacts = [str(stats_path), *facility_paths]
    return ToolResult(
        tool="get_mission_priority",
        success=True,
        answer_markdown=answer,
        artifacts_used=artifacts,
        payload={
            "aoi_id": aoi_id,
            "mission_priority": mission,
            "stats": stats,
            "facilities": facilities_payload,
            "hospitals": hospitals_payload,
        },
        steps_run=steps_run,
    )


TOOL_REGISTRY: dict[str, Callable[[ToolContext], ToolResult]] = {
    "query_historical": tool_query_historical,
    "get_damage_stats": tool_get_damage_stats,
    "get_mission_priority": tool_get_mission_priority,
    "find_nearest_hospitals": tool_find_nearest_hospitals,
    "find_nearest_facilities": tool_find_nearest_facilities,
    "generate_report": tool_generate_report,
    "weather_context": tool_weather_context,
    "situation_roads": tool_situation_roads,
    "query_guidance": tool_query_guidance,
}


def run_tool(name: str, ctx: ToolContext) -> ToolResult:
    runner = TOOL_REGISTRY.get(name)
    if runner is None:
        return ToolResult(tool=name, success=False, errors=[f"Unknown tool: {name}"])
    return runner(ctx)
