import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type MutableRefObject } from "react";
import {
  GeoJSON,
  ImageOverlay,
  MapContainer,
  Marker,
  Popup,
  Rectangle,
  TileLayer,
  Tooltip,
  useMap,
} from "react-leaflet";
import L from "leaflet";
import { buildingChipUrl } from "../api/client";
import type { Hospital, SituationRoads, SituationWeather } from "../api/client";
import { damageColor, displayDamageLabel } from "../damageColors";
import { BUILDING_SCOPE_HINTS, BUILDING_SCOPE_LABELS, type BuildingScope } from "../buildingScope";
import { findHospitalForFocus, hospitalRowKey } from "../hospitalUtils";
import type { MapFocus, PriorityGridCell } from "../mapFocus";
import { buildPriorityGridCells } from "../priorityGrid";
import { HospitalMapPopup } from "./HospitalMapPopup";
import { RotatedImageryOverlay, type ImageryCorners } from "./RotatedImageryOverlay";
import {
  BuildingsLayerControl,
  MapRegionSelect,
  RegionSelectControl,
  type RegionSelection,
} from "./MapRegionSelect";
import { RegionStatsPopover } from "./RegionStatsPopover";
import {
  SituationChoroplethLayer,
  SituationClimateLabels,
  SituationLayerControl,
  SituationOverlay,
  SituationPanes,
  SituationRoadChip,
  SituationRoadControl,
  SituationRoadLayer,
  SituationWindLayer,
} from "./SituationLayer";
import {
  CONUS_CENTER,
  CONUS_ZOOM,
  FLY_DURATION_SEC,
  FLY_HOLD_MS,
  FLY_MAX_ZOOM,
  FLY_PADDING,
  FOCUS_DURATION_SEC,
  IMAGERY_FADE_MS,
  MARKERS_AFTER_POLYGONS_MS,
  OVERLAY_FADE_MS,
  POLYGON_FADE_MS,
  POST_TO_POLYGONS_MS,
  PRE_ARRIVAL_HOLD_MS,
  PRE_TO_POST_MS,
  RECENTER_DURATION_SEC,
  STREET_REF_FADE_MS,
  animateOpacity,
  deriveMapRevealReadiness,
  imageryPreviewUrl,
  prefetchImageryPreview,
  revealPhaseOrder,
  type MapRevealPhase,
  type PipelineProgressHint,
} from "../mapCinematic";

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function buildingPopupDisplayLabel(props: Record<string, unknown>): string {
  const display = displayDamageLabel(String(props.damage_label ?? "unknown"));
  if (display === "no_damage") return "No damage";
  if (display === "minor") return "Minor";
  if (display === "major") return "Major";
  if (display === "destroyed") return "Destroyed";
  return display;
}

function buildingPopupHtml(aoiId: string, props: Record<string, unknown>): string {
  const label = escapeHtml(buildingPopupDisplayLabel(props));
  const bldId = String(props.BLD_ID ?? "");
  const area = props.AREA ? Number(props.AREA).toFixed(0) : "n/a";
  const preUrl = buildingChipUrl(aoiId, bldId, "pre");
  const postUrl = buildingChipUrl(aoiId, bldId, "post");

  return `
    <div class="building-popup">
      <div class="building-popup-meta">
        <strong>${label}</strong><br/>
        ID: ${escapeHtml(bldId || "n/a")}<br/>
        Area: ${area} m²
      </div>
      <div class="building-popup-chips">
        <figure>
          <figcaption>Pre-disaster</figcaption>
          <img src="${preUrl}" alt="Pre-disaster view" loading="lazy" />
        </figure>
        <figure>
          <figcaption>Post-disaster</figcaption>
          <img src="${postUrl}" alt="Post-disaster view" loading="lazy" />
        </figure>
      </div>
    </div>
  `;
}

export type BasemapId = "street" | "post" | "pre";

const STREET_TILES = {
  url: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
  subdomains: "abc",
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
};

/** Roads + labels only — overlaid on pre/post imagery without covering the photo. */
const STREET_REFERENCE_TILES = {
  url: "https://{s}.basemaps.cartocdn.com/rastertiles/voyager_only_labels/{z}/{x}/{y}{r}.png",
  subdomains: "abcd",
  maxZoom: 20,
  opacity: 0.92,
  attribution:
    'Streets &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>, &copy; <a href="https://carto.com/attributions">CARTO</a>',
};

/** Regional context fill when viewing AOI pre/post chips. */
const CONTEXT_SATELLITE_TILES = {
  url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
  maxZoom: 19,
  attribution:
    'Context &copy; <a href="https://www.esri.com/">Esri</a> — Maxar, Earthstar Geographics, USDA FSA, USGS',
};

type BasemapOption = {
  id: BasemapId;
  label: string;
  available: boolean;
};

type Props = {
  /** Null / empty = shared idle CONUS map (no AOI chrome). */
  aoiId: string | null;
  bounds?: [number, number, number, number];
  imagery?: { pre?: boolean; post?: boolean };
  imageryCorners?: ImageryCorners | null;
  buildingsGeojson?: GeoJSON.FeatureCollection | null;
  buildingScope?: BuildingScope;
  /** Switch Official / Fused inventory on the map (left control above Recenter). */
  onBuildingScopeChange?: (scope: BuildingScope) => void;
  showFusedBuildingScope?: boolean;
  buildingScopePending?: boolean;
  center?: [number, number];
  basemap: BasemapId;
  onBasemapChange: (id: BasemapId) => void;
  imageryReady?: boolean;
  hospitals?: Hospital[];
  focusMap?: MapFocus | null;
  situationWeather?: SituationWeather | null;
  situationLoading?: boolean;
  situationError?: string | null;
  situationRoads?: SituationRoads | null;
  situationRoadsLoading?: boolean;
  situationRoadsError?: string | null;
  /** AOI stats (optional) — used to build the Priority 3×3 grid. */
  aoiStats?: Record<string, unknown> | null;
  /** Cleared focus / chat deep-link after user recenters on the AOI. */
  onRecenter?: () => void;
  /** Optional pre/post dates for the soft imagery timeline strip. */
  imageryTimeline?: { pre?: string | null; post?: string | null } | null;
  /**
   * When true (default), open with CONUS satellite then slowly fly + fade overlays.
   * Set false only for tests / non-cinematic embeds.
   */
  cinematic?: boolean;
  /** Live assessment job progress — gates Pre / Post / polygons during upload. */
  pipelineProgress?: PipelineProgressHint | null;
  /** Caption shown on the shared idle CONUS map. */
  idleCaption?: string;
};

function boundsToLeaflet(
  bounds: [number, number, number, number],
): [[number, number], [number, number]] {
  const [west, south, east, north] = bounds;
  return [
    [south, west],
    [north, east],
  ];
}

/** Non-rotated imagery: fade in on mount (Pre ↔ Post / Street → imagery). */
function FadingImageOverlay({
  url,
  bounds,
  opacity = 1,
}: {
  url: string;
  bounds: [[number, number], [number, number]];
  opacity?: number;
}) {
  const [layerOpacity, setLayerOpacity] = useState(0);

  useEffect(() => {
    setLayerOpacity(0);
    return animateOpacity(0, opacity, IMAGERY_FADE_MS, setLayerOpacity);
  }, [url, bounds[0][0], bounds[0][1], bounds[1][0], bounds[1][1], opacity]);

  return <ImageOverlay url={url} bounds={bounds} opacity={layerOpacity} zIndex={0} />;
}

/**
 * First reveal: hold CONUS briefly, then ease into the AOI.
 * Subsequent bound updates for the same AOI are ignored (recenter uses RecenterAoiView).
 */
function CinematicApproach({
  aoiId,
  bounds,
  enabled,
  onPhase,
}: {
  aoiId: string | null;
  bounds: [number, number, number, number] | undefined;
  enabled: boolean;
  onPhase: (phase: MapRevealPhase) => void;
}) {
  const map = useMap();
  const flownKeyRef = useRef<string | null>(null);
  const timersRef = useRef<number[]>([]);

  const clearTimers = useCallback(() => {
    for (const id of timersRef.current) window.clearTimeout(id);
    timersRef.current = [];
  }, []);

  // useLayoutEffect: snap to CONUS before paint so AOI switches don't flash the old zoom.
  useLayoutEffect(() => {
    flownKeyRef.current = null;
    clearTimers();
    if (!enabled || !aoiId) return;
    onPhase("idle");
    const center = map.getCenter();
    const zoom = map.getZoom();
    const alreadyConus =
      Math.abs(center.lat - CONUS_CENTER[0]) < 0.8 &&
      Math.abs(center.lng - CONUS_CENTER[1]) < 0.8 &&
      Math.abs(zoom - CONUS_ZOOM) < 0.6;
    if (!alreadyConus) {
      map.setView(CONUS_CENTER, CONUS_ZOOM, { animate: false });
    }
  }, [aoiId, enabled, map, onPhase, clearTimers]);

  useEffect(() => {
    if (!enabled || !aoiId) {
      if (!enabled && bounds) {
        map.fitBounds(boundsToLeaflet(bounds), { padding: FLY_PADDING, maxZoom: FLY_MAX_ZOOM });
        onPhase("settled");
      }
      return;
    }
    if (!bounds) {
      onPhase("idle");
      return;
    }

    const key = `${aoiId}:${bounds.join(",")}`;
    if (flownKeyRef.current === key) return;
    flownKeyRef.current = key;
    clearTimers();
    onPhase("flying");

    const holdId = window.setTimeout(() => {
      map.invalidateSize({ pan: false });
      map.flyToBounds(boundsToLeaflet(bounds), {
        padding: FLY_PADDING,
        duration: FLY_DURATION_SEC,
        easeLinearity: 0.18,
        maxZoom: FLY_MAX_ZOOM,
      });
      const arriveId = window.setTimeout(() => {
        // Fly finished — brief linger on context satellite, then advance to Pre.
        const preId = window.setTimeout(() => {
          onPhase("pre");
        }, PRE_ARRIVAL_HOLD_MS);
        timersRef.current.push(preId);
      }, FLY_DURATION_SEC * 1000 + 120);
      timersRef.current.push(arriveId);
    }, FLY_HOLD_MS);
    timersRef.current.push(holdId);

    return () => clearTimers();
  }, [aoiId, bounds, enabled, map, onPhase, clearTimers]);

  return null;
}

/** One-shot recenter when the user clicks the Recenter control. */
function RecenterAoiView({
  bounds,
  requestKey,
}: {
  bounds: [number, number, number, number] | undefined;
  requestKey: number;
}) {
  const map = useMap();
  const lastKeyRef = useRef(0);

  useEffect(() => {
    if (!bounds || requestKey <= 0 || requestKey === lastKeyRef.current) return;
    lastKeyRef.current = requestKey;
    map.invalidateSize({ pan: false });
    map.flyToBounds(boundsToLeaflet(bounds), {
      padding: [36, 36],
      duration: RECENTER_DURATION_SEC,
      easeLinearity: 0.2,
      maxZoom: FLY_MAX_ZOOM,
    });
  }, [bounds, requestKey, map]);

  return null;
}

function RecenterAoiControl({
  disabled,
  onRecenter,
}: {
  disabled?: boolean;
  onRecenter: () => void;
}) {
  const map = useMap();
  const onRecenterRef = useRef(onRecenter);
  onRecenterRef.current = onRecenter;
  const disabledRef = useRef(disabled);
  disabledRef.current = disabled;

  useEffect(() => {
    const control = new L.Control({ position: "topleft" });
    control.onAdd = () => {
      const container = L.DomUtil.create("div", "leaflet-recenter-aoi-control");
      L.DomEvent.disableClickPropagation(container);
      L.DomEvent.disableScrollPropagation(container);

      const button = L.DomUtil.create("button", "", container);
      button.type = "button";
      button.textContent = "Recenter";
      button.title = "Fit the map back to this AOI";
      button.disabled = Boolean(disabledRef.current);
      button.addEventListener("click", () => {
        if (!disabledRef.current) onRecenterRef.current();
      });
      return container;
    };
    control.addTo(map);
    return () => {
      control.remove();
    };
  }, [map]);

  useEffect(() => {
    const button = map
      .getContainer()
      .querySelector(".leaflet-recenter-aoi-control button") as HTMLButtonElement | null;
    if (!button) return;
    button.disabled = Boolean(disabled);
  }, [disabled, map]);

  return null;
}

const BUILDING_SCOPE_SHORT: Record<"official" | "fused", string> = {
  official: "Official",
  fused: "Official+",
};

/** Toggle Official ↔ fused inventory — single control above Recenter. */
function BuildingScopeMapControl({
  value,
  onChange,
  showFused,
  pending = false,
}: {
  value: BuildingScope;
  onChange: (scope: BuildingScope) => void;
  showFused: boolean;
  pending?: boolean;
}) {
  const map = useMap();
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const valueRef = useRef(value);
  valueRef.current = value;
  const showFusedRef = useRef(showFused);
  showFusedRef.current = showFused;
  const pendingRef = useRef(pending);
  pendingRef.current = pending;

  useEffect(() => {
    const control = new L.Control({ position: "topleft" });
    control.onAdd = () => {
      const container = L.DomUtil.create("div", "leaflet-building-scope-control");
      L.DomEvent.disableClickPropagation(container);
      L.DomEvent.disableScrollPropagation(container);

      const button = L.DomUtil.create("button", "", container) as HTMLButtonElement;
      button.type = "button";
      button.addEventListener("click", () => {
        const fusedReady = showFusedRef.current || pendingRef.current;
        if (!fusedReady) return;
        const current = valueRef.current === "fused" ? "fused" : "official";
        onChangeRef.current(current === "official" ? "fused" : "official");
      });
      return container;
    };
    control.addTo(map);
    return () => {
      control.remove();
    };
  }, [map]);

  useEffect(() => {
    const button = map
      .getContainer()
      .querySelector(".leaflet-building-scope-control button") as HTMLButtonElement | null;
    if (!button) return;
    const scope: "official" | "fused" = value === "fused" ? "fused" : "official";
    const fusedReady = showFused || pending;
    button.textContent = BUILDING_SCOPE_SHORT[scope];
    button.title = fusedReady
      ? `${BUILDING_SCOPE_HINTS[scope]} (click to toggle Official / Official+)`
      : `${BUILDING_SCOPE_HINTS.official} (Official+ unavailable until extras load)`;
    button.setAttribute("aria-label", BUILDING_SCOPE_LABELS[scope]);
    button.setAttribute("aria-pressed", scope === "fused" ? "true" : "false");
    button.classList.toggle("active", scope === "fused");
    button.disabled = !fusedReady;
  }, [value, showFused, pending, map]);

  return null;
}

function FocusMapTarget({
  focus,
  markerRefs,
  buildingLayerRefs,
}: {
  focus: MapFocus | null;
  markerRefs: MutableRefObject<Record<string, L.Marker>>;
  buildingLayerRefs: MutableRefObject<Record<string, L.Layer>>;
}) {
  const map = useMap();
  const lastFocusKeyRef = useRef<number | null>(null);
  /** Same AOI overview for P1/P2/P3 — don't re-fly (causes camera wobble). */
  const lastRegionOverviewRef = useRef<string | null>(null);

  useEffect(() => {
    if (!focus) {
      lastFocusKeyRef.current = null;
      lastRegionOverviewRef.current = null;
      return;
    }
    // Only fly once per focus request — re-renders / layout tweaks must not yank the view back.
    if (lastFocusKeyRef.current === focus.key) return;
    lastFocusKeyRef.current = focus.key;

    if (focus.kind === "region") {
      const overview = focus.aoiBounds ?? focus.bounds_wgs84;
      const overviewKey = overview.join(",");
      // Switching Priority 1→2→3 only changes the highlighted cell; keep the camera still.
      if (lastRegionOverviewRef.current === overviewKey) {
        return;
      }
      lastRegionOverviewRef.current = overviewKey;
      const [west, south, east, north] = overview;
      map.invalidateSize({ pan: false });
      map.flyToBounds(
        [
          [south, west],
          [north, east],
        ],
        {
          padding: [44, 44],
          duration: FOCUS_DURATION_SEC,
          easeLinearity: 0.2,
          maxZoom: FLY_MAX_ZOOM,
        },
      );
      return;
    }

    lastRegionOverviewRef.current = null;
    map.invalidateSize({ pan: false });

    if (focus.kind === "weather") {
      if (focus.aoiBounds) {
        const [west, south, east, north] = focus.aoiBounds;
        map.flyToBounds(
          [
            [south, west],
            [north, east],
          ],
          {
            padding: [44, 44],
            duration: FOCUS_DURATION_SEC,
            easeLinearity: 0.2,
            maxZoom: FLY_MAX_ZOOM,
          },
        );
      }
      return;
    }

    const [lon, lat] = focus.coordinates_wgs84;
    const targetZoom = Math.max(map.getZoom(), 15);
    map.flyTo([lat, lon], targetZoom, {
      duration: FOCUS_DURATION_SEC,
      easeLinearity: 0.2,
    });
    const timer = window.setTimeout(() => {
      if (focus.kind === "hospital") {
        const matched = Object.keys(markerRefs.current).find((key) => {
          if (key === focus.hospitalKey) return true;
          // Matched AOI hospital row uses name-distance key; try opening that too.
          return key.startsWith(`${focus.name}-`);
        });
        const marker =
          markerRefs.current[focus.hospitalKey] ??
          (matched ? markerRefs.current[matched] : undefined);
        const popup = marker?.getPopup();
        if (popup) popup.options.autoPan = false;
        marker?.openPopup();
        return;
      }
      if (focus.kind === "road") {
        const marker = markerRefs.current[`road-${focus.roadId}`];
        const popup = marker?.getPopup();
        if (popup) popup.options.autoPan = false;
        marker?.openPopup();
        return;
      }
      const layer = buildingLayerRefs.current[focus.bldId];
      if (layer && "getPopup" in layer && typeof layer.getPopup === "function") {
        const popup = layer.getPopup();
        if (popup) popup.options.autoPan = false;
      }
      if (layer && "openPopup" in layer && typeof layer.openPopup === "function") {
        layer.openPopup();
      }
    }, FOCUS_DURATION_SEC * 1000 * 0.75);
    return () => window.clearTimeout(timer);
  }, [focus, map, markerRefs, buildingLayerRefs]);

  // After the user pans away, close popups so later invalidateSize / UI toggles
  // cannot autoPan the map back to the previously focused feature.
  useEffect(() => {
    function onUserMove() {
      map.closePopup();
    }
    map.on("dragstart", onUserMove);
    map.on("zoomstart", onUserMove);
    return () => {
      map.off("dragstart", onUserMove);
      map.off("zoomstart", onUserMove);
    };
  }, [map]);

  return null;
}

function priorityRegionStyle(priority?: number): L.PathOptions {
  // Quiet fallback when full grid payload is missing.
  if (priority === 1) {
    return {
      color: "#64748b",
      weight: 2.25,
      fillColor: "#9f1212",
      fillOpacity: 0.56,
      className: "priority-grid-cell priority-grid-focused",
    };
  }
  if (priority === 2) {
    return {
      color: "#7c8a9a",
      weight: 1.5,
      fillColor: "#d1433a",
      fillOpacity: 0.42,
      className: "priority-grid-cell",
    };
  }
  return {
    color: "#7c8a9a",
    weight: 1.25,
    fillColor: "#c9a9a0",
    fillOpacity: 0.26,
    className: "priority-grid-cell",
  };
}

/** Hex → RGB for sequential colormap interpolation. */
function hexToRgb(hex: string): [number, number, number] {
  const raw = hex.replace("#", "");
  const value = Number.parseInt(raw, 16);
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
}

function rgbToHex(r: number, g: number, b: number): string {
  const to = (n: number) => Math.max(0, Math.min(255, Math.round(n))).toString(16).padStart(2, "0");
  return `#${to(r)}${to(g)}${to(b)}`;
}

/**
 * Low → high Score sequential ramp.
 * High end shifts toward clear reds so heavily damaged cells read as urgent on imagery.
 */
const SEVERITY_RAMP: Array<{ t: number; hex: string }> = [
  { t: 0, hex: "#c5ced9" },
  { t: 0.3, hex: "#c9a9a0" },
  { t: 0.55, hex: "#d1433a" },
  { t: 0.8, hex: "#c41e1e" },
  { t: 1, hex: "#9f1212" },
];

function lerpSeverityColor(t: number): string {
  const x = Math.max(0, Math.min(1, t));
  let lo = SEVERITY_RAMP[0];
  let hi = SEVERITY_RAMP[SEVERITY_RAMP.length - 1];
  for (let i = 0; i < SEVERITY_RAMP.length - 1; i += 1) {
    if (x >= SEVERITY_RAMP[i].t && x <= SEVERITY_RAMP[i + 1].t) {
      lo = SEVERITY_RAMP[i];
      hi = SEVERITY_RAMP[i + 1];
      break;
    }
  }
  const span = hi.t - lo.t || 1;
  const u = (x - lo.t) / span;
  const [r0, g0, b0] = hexToRgb(lo.hex);
  const [r1, g1, b1] = hexToRgb(hi.hex);
  return rgbToHex(r0 + (r1 - r0) * u, g0 + (g1 - g0) * u, b0 + (b1 - b0) * u);
}

function cellScore(cell: {
  impact_score: number;
  destroyed: number;
  major: number;
  minor: number;
}): number {
  // Color must follow the same Score shown on the label.
  if (cell.impact_score > 0) return cell.impact_score;
  // Fallback only when Score is missing: match backend weights (destroyed=3, major=2, minor=1).
  return cell.destroyed * 3 + cell.major * 2 + cell.minor;
}

function cellRelativeSeverity(
  cell: { impact_score: number; destroyed: number; major: number; minor: number },
  maxImpact: number,
): number {
  const score = cellScore(cell);
  if (maxImpact <= 0 || score <= 0) return 0;
  // Linear relative score — keeps mid cells from jumping too hot.
  return Math.min(1, score / maxImpact);
}

function gridCellStyle(
  cell: {
    impact_score: number;
    destroyed: number;
    major: number;
    minor: number;
    priority?: number;
  },
  options: { maxImpact: number; focused: boolean; hovered?: boolean },
): L.PathOptions {
  const { maxImpact, focused, hovered = false } = options;
  const t = cellRelativeSeverity(cell, maxImpact);
  const fillColor = lerpSeverityColor(t);
  const highlight = focused || hovered;
  return {
    color: highlight ? "#334155" : "#7c8a9a",
    weight: focused ? 2.4 : hovered ? 2.15 : 1.15,
    fillColor,
    fillOpacity: focused ? 0.6 : hovered ? Math.min(0.66, 0.36 + t * 0.36) : 0.3 + t * 0.36,
    className: focused
      ? "priority-grid-cell priority-grid-focused"
      : hovered
        ? "priority-grid-cell priority-grid-hovered"
        : "priority-grid-cell",
  };
}

function PriorityLayerControl({
  enabled,
  onToggle,
  disabled,
}: {
  enabled: boolean;
  onToggle: () => void;
  disabled?: boolean;
}) {
  const map = useMap();
  const onToggleRef = useRef(onToggle);
  onToggleRef.current = onToggle;
  const disabledRef = useRef(disabled);
  disabledRef.current = disabled;

  useEffect(() => {
    const control = new L.Control({ position: "topleft" });
    control.onAdd = () => {
      const container = L.DomUtil.create("div", "leaflet-priority-layer-control");
      L.DomEvent.disableClickPropagation(container);
      L.DomEvent.disableScrollPropagation(container);
      const button = L.DomUtil.create("button", "", container);
      button.type = "button";
      button.textContent = "Priority";
      button.title = "Show or hide mission-priority 3×3 damage grid";
      button.addEventListener("click", () => {
        if (!disabledRef.current) onToggleRef.current();
      });
      return container;
    };
    control.addTo(map);
    return () => {
      control.remove();
    };
  }, [map]);

  useEffect(() => {
    const button = map
      .getContainer()
      .querySelector(".leaflet-priority-layer-control button") as HTMLButtonElement | null;
    if (!button) return;
    button.classList.toggle("active", enabled);
    button.disabled = Boolean(disabled);
    button.textContent = enabled ? "Priority" : "Priority off";
    button.title = enabled
      ? "Hide mission-priority 3×3 damage grid"
      : "Show mission-priority 3×3 damage grid";
  }, [enabled, disabled, map]);

  return null;
}

function PriorityGridOverlay({
  cells,
  focus,
}: {
  cells: PriorityGridCell[];
  focus?: {
    priority?: number;
    direction?: string;
    bounds_wgs84?: [number, number, number, number];
    name?: string;
  } | null;
}) {
  const maxImpact = Math.max(1, ...cells.map((item) => cellScore(item)));
  return (
    <>
      {cells.map((cell) => {
        const focused = Boolean(
          focus &&
            ((focus.priority != null && cell.priority === focus.priority) ||
              (focus.direction != null &&
                cell.direction.toUpperCase() === focus.direction.toUpperCase()) ||
              (focus.bounds_wgs84 &&
                cell.bounds_wgs84[0] === focus.bounds_wgs84[0] &&
                cell.bounds_wgs84[1] === focus.bounds_wgs84[1] &&
                cell.bounds_wgs84[2] === focus.bounds_wgs84[2] &&
                cell.bounds_wgs84[3] === focus.bounds_wgs84[3])),
        );
        const baseStyle = {
          ...gridCellStyle(cell, { maxImpact, focused }),
          pane: "priorityPane",
        };
        return (
          <Rectangle
            key={`priority-grid-${cell.direction}`}
            bounds={[
              [cell.bounds_wgs84[1], cell.bounds_wgs84[0]],
              [cell.bounds_wgs84[3], cell.bounds_wgs84[2]],
            ]}
            pathOptions={baseStyle}
            pane="priorityPane"
            eventHandlers={{
              mouseover: (event) => {
                const layer = event.target as L.Path;
                layer.setStyle({
                  ...gridCellStyle(cell, { maxImpact, focused, hovered: true }),
                  pane: "priorityPane",
                });
                layer.bringToFront();
              },
              mouseout: (event) => {
                const layer = event.target as L.Path;
                layer.setStyle(baseStyle);
              },
            }}
          >
            <Tooltip
              permanent
              direction="center"
              pane="priorityLabelPane"
              className={
                focused
                  ? "priority-region-tooltip priority-region-tooltip-focus"
                  : "priority-region-tooltip"
              }
            >
              <div className="priority-cell-label">
                <div className="priority-cell-label-head">
                  {focused && focus?.name
                    ? focus.name
                    : cell.priority
                      ? `P${cell.priority} · ${directionShortLabel(cell.direction) || cell.direction}`
                      : directionShortLabel(cell.direction) || cell.direction}
                </div>
                <div className="priority-cell-label-score">Score {cell.impact_score}</div>
                <div className="priority-cell-label-stats">
                  <span>D {cell.destroyed}</span>
                  <span>Ma {cell.major}</span>
                  <span>Mi {cell.minor}</span>
                </div>
              </div>
            </Tooltip>
          </Rectangle>
        );
      })}
    </>
  );
}

function directionShortLabel(direction: string): string {
  const raw = direction.trim();
  if (!raw) return "";
  const map: Record<string, string> = {
    Northwest: "NW",
    North: "N",
    Northeast: "NE",
    West: "W",
    Center: "C",
    East: "E",
    Southwest: "SW",
    South: "S",
    Southeast: "SE",
  };
  return map[raw] || raw;
}

function useOverlayReveal(visible: boolean, fadeMs: number = OVERLAY_FADE_MS) {
  const [mounted, setMounted] = useState(visible);
  const [revealed, setRevealed] = useState(visible);

  useEffect(() => {
    if (visible) {
      setMounted(true);
      const frame = window.requestAnimationFrame(() => setRevealed(true));
      return () => window.cancelAnimationFrame(frame);
    }
    setRevealed(false);
    const timer = window.setTimeout(() => setMounted(false), fadeMs);
    return () => window.clearTimeout(timer);
  }, [visible, fadeMs]);

  return { mounted, revealed };
}

function PriorityPane({ revealed }: { revealed: boolean }) {
  const map = useMap();
  useEffect(() => {
    const ensure = (name: string, zIndex: string) => {
      if (!map.getPane(name)) map.createPane(name);
      const pane = map.getPane(name);
      if (!pane) return;
      pane.style.zIndex = zIndex;
      pane.style.opacity = pane.style.opacity || "0";
      pane.style.transition = `opacity ${OVERLAY_FADE_MS}ms cubic-bezier(0.4, 0, 0.2, 1)`;
      pane.style.pointerEvents = "none";
    };
    // Labels sit above the grid fill so P1 / score stay readable.
    ensure("priorityPane", "452");
    ensure("priorityLabelPane", "453");
  }, [map]);

  useEffect(() => {
    for (const name of ["priorityPane", "priorityLabelPane"] as const) {
      const pane = map.getPane(name);
      if (!pane) continue;
      pane.style.opacity = revealed ? "1" : "0";
      // Grid cells need hover; labels stay non-interactive.
      if (name === "priorityPane") {
        pane.style.pointerEvents = revealed ? "auto" : "none";
      }
    }
  }, [revealed, map]);

  return null;
}

function BuildingsPane({ revealed }: { revealed: boolean }) {
  const map = useMap();
  useEffect(() => {
    if (!map.getPane("buildingsPane")) {
      map.createPane("buildingsPane");
      const pane = map.getPane("buildingsPane");
      if (pane) {
        pane.style.zIndex = "450";
        pane.style.opacity = "0";
        pane.style.transition = `opacity ${POLYGON_FADE_MS}ms cubic-bezier(0.4, 0, 0.2, 1)`;
      }
    }
  }, [map]);

  useEffect(() => {
    const pane = map.getPane("buildingsPane");
    if (!pane) return;
    pane.style.opacity = revealed ? "1" : "0";
  }, [revealed, map]);

  return null;
}

/** Street lines/names above imagery, below building polygons. */
function StreetOverlayPane({ opacity }: { opacity: number }) {
  const map = useMap();
  useEffect(() => {
    if (!map.getPane("streetOverlayPane")) {
      map.createPane("streetOverlayPane");
      const pane = map.getPane("streetOverlayPane");
      if (pane) {
        pane.style.zIndex = "425";
        pane.style.pointerEvents = "none";
        pane.style.opacity = "0";
        pane.style.transition = `opacity ${STREET_REF_FADE_MS}ms cubic-bezier(0.4, 0, 0.2, 1)`;
      }
    }
  }, [map]);

  useEffect(() => {
    const pane = map.getPane("streetOverlayPane");
    if (!pane) return;
    pane.style.opacity = String(opacity);
  }, [opacity, map]);

  return null;
}

function MapResizeHandler() {
  const map = useMap();
  useEffect(() => {
    const target = map.getContainer().closest(".map-wrap") ?? map.getContainer();
    const observer = new ResizeObserver(() => {
      map.invalidateSize({ pan: false });
    });
    observer.observe(target);
    map.invalidateSize({ pan: false });
    return () => observer.disconnect();
  }, [map]);
  return null;
}

/** Snap back to continental overview when the shared map returns to idle. */
function IdleConusSnap({ active }: { active: boolean }) {
  const map = useMap();
  useLayoutEffect(() => {
    if (!active) return;
    map.setView(CONUS_CENTER, CONUS_ZOOM, { animate: false });
    map.invalidateSize({ pan: false });
  }, [active, map]);
  return null;
}

function BasemapControl({
  basemap,
  options,
  onChange,
}: {
  basemap: BasemapId;
  options: BasemapOption[];
  onChange: (id: BasemapId) => void;
}) {
  const map = useMap();
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const optionsRef = useRef(options);
  optionsRef.current = options;

  useEffect(() => {
    const control = new L.Control({ position: "topright" });
    control.onAdd = () => {
      const container = L.DomUtil.create("div", "leaflet-basemap-control");
      L.DomEvent.disableClickPropagation(container);
      L.DomEvent.disableScrollPropagation(container);

      for (const id of ["street", "post", "pre"] as BasemapId[]) {
        const button = L.DomUtil.create("button", "", container);
        button.type = "button";
        button.dataset.basemap = id;
        button.addEventListener("click", () => {
          onChangeRef.current(id);
        });
      }
      return container;
    };
    control.addTo(map);
    return () => {
      control.remove();
    };
  }, [map]);

  useEffect(() => {
    const root = map.getContainer().querySelector(".leaflet-basemap-control");
    if (!root) return;
    root.querySelectorAll("button").forEach((button) => {
      const id = (button as HTMLButtonElement).dataset.basemap as BasemapId;
      const option = optionsRef.current.find((item) => item.id === id);
      if (!option) return;
      button.textContent = option.label;
      (button as HTMLButtonElement).disabled = !option.available;
      button.classList.toggle("active", id === basemap);
    });
  }, [basemap, map, options]);

  return null;
}

const hospitalIcon = L.divIcon({
  className: "",
  html: '<div style="background:#dc2626;width:12px;height:12px;border-radius:50%;border:2px solid white;box-shadow:0 0 0 1px #991b1b"></div>',
  iconSize: [12, 12],
  iconAnchor: [6, 6],
});

const fireStationIcon = L.divIcon({
  className: "",
  html: '<div style="background:#ea580c;width:12px;height:12px;border-radius:50%;border:2px solid white;box-shadow:0 0 0 1px #9a3412"></div>',
  iconSize: [12, 12],
  iconAnchor: [6, 6],
});

const policeIcon = L.divIcon({
  className: "",
  html: '<div style="background:#2563eb;width:12px;height:12px;border-radius:50%;border:2px solid white;box-shadow:0 0 0 1px #1e40af"></div>',
  iconSize: [12, 12],
  iconAnchor: [6, 6],
});

const shelterIcon = L.divIcon({
  className: "",
  html: '<div style="background:#059669;width:12px;height:12px;border-radius:50%;border:2px solid white;box-shadow:0 0 0 1px #065f46"></div>',
  iconSize: [12, 12],
  iconAnchor: [6, 6],
});

const facilityFocusIcon = L.divIcon({
  className: "",
  html: '<div style="background:#2563eb;width:14px;height:14px;border-radius:50%;border:2px solid white;box-shadow:0 0 0 1px #1e40af"></div>',
  iconSize: [14, 14],
  iconAnchor: [7, 7],
});

function facilityMarkerIcon(kind?: string) {
  switch (kind) {
    case "fire_station":
      return fireStationIcon;
    case "police":
      return policeIcon;
    case "shelter":
      return shelterIcon;
    case "hospital":
    default:
      return hospitalIcon;
  }
}

export function MapPanel({
  aoiId,
  bounds,
  imagery,
  imageryCorners,
  buildingsGeojson = null,
  buildingScope = "official",
  onBuildingScopeChange,
  showFusedBuildingScope = false,
  buildingScopePending = false,
  center,
  basemap,
  onBasemapChange,
  imageryReady = false,
  hospitals = [],
  focusMap = null,
  situationWeather = null,
  situationLoading = false,
  situationError = null,
  situationRoads = null,
  situationRoadsLoading = false,
  situationRoadsError = null,
  aoiStats = null,
  onRecenter,
  imageryTimeline = null,
  cinematic = true,
  pipelineProgress = null,
  idleCaption = "Select an AOI or upload post-disaster imagery to begin",
}: Props) {
  const isIdle = !aoiId;
  const cinematicEnabled = cinematic && !isIdle;
  const markerRefs = useRef<Record<string, L.Marker>>({});
  const buildingLayerRefs = useRef<Record<string, L.Layer>>({});
  const mapWrapRef = useRef<HTMLDivElement>(null);
  const [regionSelectEnabled, setRegionSelectEnabled] = useState(false);
  const [regionSelection, setRegionSelection] = useState<RegionSelection | null>(null);
  const [showBuildingPolygons, setShowBuildingPolygons] = useState(true);
  const [priorityVisible, setPriorityVisible] = useState(false);
  const [situationVisible, setSituationVisible] = useState(false);
  const [roadsVisible, setRoadsVisible] = useState(false);
  const [hourIndex, setHourIndex] = useState(0);
  const [recenterRequestKey, setRecenterRequestKey] = useState(0);
  const [revealPhase, setRevealPhase] = useState<MapRevealPhase>(
    cinematicEnabled ? "idle" : "settled",
  );
  const [axisOpacity, setAxisOpacity] = useState(cinematicEnabled ? 0 : 1);
  const [polygonsRevealed, setPolygonsRevealed] = useState(!cinematicEnabled);
  const [markersRevealed, setMarkersRevealed] = useState(!cinematicEnabled);
  /** During cinematic drive, MapPanel owns Pre/Post so parent prefs cannot skip Pre. */
  const [cinematicBasemap, setCinematicBasemap] = useState<BasemapId | null>(null);
  /** True once the Pre preview PNG is in the browser cache / decoded. */
  const [prePreviewReady, setPrePreviewReady] = useState(false);
  const priorityReveal = useOverlayReveal(priorityVisible);
  const weatherReveal = useOverlayReveal(situationVisible);
  const roadsReveal = useOverlayReveal(roadsVisible);
  const cinematicDrivingRef = useRef(false);

  const readiness = useMemo(
    () =>
      deriveMapRevealReadiness({
        bounds,
        imagery,
        hasBuildings: Boolean(buildingsGeojson?.features?.length),
        progress: pipelineProgress,
      }),
    [bounds, imagery, buildingsGeojson, pipelineProgress],
  );

  // Prefer locked cinematic basemap; while approaching/on Pre, never inherit a stale parent "post".
  const effectiveBasemap: BasemapId =
    cinematicBasemap ??
    (cinematicEnabled &&
    (revealPhase === "idle" || revealPhase === "flying" || revealPhase === "pre")
      ? "pre"
      : basemap);

  const handleRevealPhase = useCallback((phase: MapRevealPhase) => {
    setRevealPhase((current) => {
      if (phase === "idle") return "idle";
      if (current === "settled" && phase !== "settled") return current;
      if (revealPhaseOrder(phase) < revealPhaseOrder(current) && current !== "idle") {
        return current;
      }
      return phase;
    });
  }, []);

  useLayoutEffect(() => {
    if (isIdle || !cinematicEnabled) {
      setRevealPhase(isIdle ? "idle" : "settled");
      setAxisOpacity(isIdle ? 0 : 1);
      setPolygonsRevealed(!isIdle);
      setMarkersRevealed(!isIdle);
      setCinematicBasemap(null);
      setPrePreviewReady(false);
      cinematicDrivingRef.current = false;
      return;
    }
    setRevealPhase("idle");
    setAxisOpacity(0);
    setPolygonsRevealed(false);
    setMarkersRevealed(false);
    setCinematicBasemap(null);
    setPrePreviewReady(false);
    cinematicDrivingRef.current = true;
  }, [aoiId, cinematicEnabled, isIdle]);

  // Warm Pre/Post preview PNGs during the fly (first request builds from GeoTIFF — often >1s).
  useEffect(() => {
    if (!aoiId) return;
    let cancelled = false;
    if (imagery?.pre) {
      void prefetchImageryPreview(imageryPreviewUrl(aoiId, "pre")).then(() => {
        if (!cancelled) setPrePreviewReady(true);
      });
    } else {
      setPrePreviewReady(false);
    }
    if (imagery?.post) {
      // Warm Post so the Pre → Post cut is not blocked on PNG generation.
      void prefetchImageryPreview(imageryPreviewUrl(aoiId, "post"));
    }
    return () => {
      cancelled = true;
    };
  }, [aoiId, imagery?.pre, imagery?.post]);

  // Fly finished → lock Pre, fade in only after the preview is actually ready.
  useEffect(() => {
    if (!cinematicEnabled || !cinematicDrivingRef.current) return;
    if (revealPhase !== "pre") return;
    if (!readiness.canPre) return;

    if (cinematicBasemap !== "pre") {
      setCinematicBasemap("pre");
      onBasemapChange("pre");
    }

    if (!prePreviewReady) {
      setAxisOpacity(0);
      return;
    }

    const cancel = animateOpacity(0, 1, IMAGERY_FADE_MS, setAxisOpacity);
    return cancel;
  }, [
    revealPhase,
    readiness.canPre,
    cinematicEnabled,
    cinematicBasemap,
    onBasemapChange,
    prePreviewReady,
  ]);

  // Hold Pre on-screen after it has loaded + faded, then switch to Post.
  useEffect(() => {
    if (!cinematicEnabled || !cinematicDrivingRef.current) return;
    if (revealPhase !== "pre" || !readiness.canPre) return;
    if (!readiness.canPost) return;
    if (cinematicBasemap !== "pre") return;
    if (!prePreviewReady) return;

    const timer = window.setTimeout(() => {
      setCinematicBasemap("post");
      onBasemapChange("post");
      setRevealPhase("post");
      animateOpacity(0, 1, IMAGERY_FADE_MS, setAxisOpacity);
    }, PRE_TO_POST_MS);
    return () => window.clearTimeout(timer);
  }, [
    revealPhase,
    readiness.canPre,
    readiness.canPost,
    cinematicEnabled,
    cinematicBasemap,
    onBasemapChange,
    prePreviewReady,
  ]);

  // Post → polygons when footprints/damage layer is ready.
  useEffect(() => {
    if (!cinematicEnabled || !cinematicDrivingRef.current) return;
    if (revealPhase !== "post") return;
    if (!readiness.canPolygons) return;
    const timer = window.setTimeout(() => {
      setPolygonsRevealed(true);
      setRevealPhase("polygons");
    }, POST_TO_POLYGONS_MS);
    return () => window.clearTimeout(timer);
  }, [revealPhase, readiness.canPolygons, cinematicEnabled]);

  // Late buildings after we already settled without them.
  useEffect(() => {
    if (!cinematicEnabled || !readiness.canPolygons || polygonsRevealed) return;
    if (revealPhase !== "settled") return;
    setPolygonsRevealed(true);
  }, [readiness.canPolygons, cinematicEnabled, polygonsRevealed, revealPhase]);

  useEffect(() => {
    if (!cinematicEnabled) return;
    if (revealPhase !== "polygons") return;
    const markerId = window.setTimeout(() => {
      setMarkersRevealed(true);
      setRevealPhase("settled");
      setCinematicBasemap(null);
      cinematicDrivingRef.current = false;
    }, MARKERS_AFTER_POLYGONS_MS);
    return () => window.clearTimeout(markerId);
  }, [revealPhase, cinematicEnabled]);

  // Chat deep-links / focus should not wait for the cinematic sequence.
  useEffect(() => {
    if (!focusMap || !cinematicEnabled) return;
    setPolygonsRevealed(true);
    setMarkersRevealed(true);
    setAxisOpacity(1);
    setRevealPhase("settled");
    setCinematicBasemap(null);
    cinematicDrivingRef.current = false;
  }, [focusMap, cinematicEnabled]);

  const priorityCells = useMemo(
    () =>
      buildPriorityGridCells({
        stats: aoiStats,
        bounds,
        buildingsGeojson,
      }),
    [aoiStats, bounds, buildingsGeojson],
  );

  const handleRecenter = useCallback(() => {
    if (!bounds) return;
    setRecenterRequestKey((key) => key + 1);
    onRecenter?.();
  }, [bounds, onRecenter]);

  const toggleRegionSelect = useCallback(() => {
    setRegionSelectEnabled((current) => {
      if (current) setRegionSelection(null);
      return !current;
    });
  }, []);

  const toggleBuildingPolygons = useCallback(() => {
    setShowBuildingPolygons((current) => {
      const next = !current;
      if (next) {
        setPriorityVisible(false);
        setSituationVisible(false);
      }
      return next;
    });
  }, []);

  const togglePriority = useCallback(() => {
    setPriorityVisible((current) => {
      const next = !current;
      if (next) {
        setShowBuildingPolygons(false);
        setSituationVisible(false);
      }
      return next;
    });
  }, []);

  const toggleSituation = useCallback(() => {
    setSituationVisible((current) => {
      const next = !current;
      if (next) {
        setShowBuildingPolygons(false);
        setPriorityVisible(false);
      }
      return next;
    });
  }, []);

  const toggleRoads = useCallback(() => {
    setRoadsVisible((current) => !current);
  }, []);

  const handleRegionSelection = useCallback((selection: RegionSelection | null) => {
    setRegionSelection(selection);
  }, []);

  const clearRegionSelection = useCallback(() => {
    setRegionSelection(null);
  }, []);

  useEffect(() => {
    setRegionSelectEnabled(false);
    setRegionSelection(null);
    setShowBuildingPolygons(true);
    setPriorityVisible(false);
    setSituationVisible(false);
    setRoadsVisible(false);
    setHourIndex(0);
  }, [aoiId, buildingScope, buildingsGeojson]);

  useEffect(() => {
    setHourIndex(0);
  }, [situationWeather?.fetched_at]);

  useEffect(() => {
    if (focusMap?.kind === "road") {
      setRoadsVisible(true);
    }
    if (focusMap?.kind === "region") {
      setPriorityVisible(true);
      setShowBuildingPolygons(false);
      setSituationVisible(false);
    }
    if (focusMap?.kind === "weather") {
      setSituationVisible(true);
      setShowBuildingPolygons(false);
      setPriorityVisible(false);
    }
  }, [focusMap]);
  const basemapOptions = useMemo<BasemapOption[]>(
    () => [
      { id: "street", label: "Street", available: true },
      { id: "post", label: "Post", available: Boolean(imagery?.post && bounds) },
      { id: "pre", label: "Pre", available: Boolean(imagery?.pre && bounds) },
    ],
    [imagery, bounds],
  );

  useEffect(() => {
    if (!imageryReady || effectiveBasemap === "street") return;
    // While the cinematic sequence is driving Pre → Post, don't auto-correct basemap.
    if (cinematicEnabled && cinematicBasemap) return;
    const option = basemapOptions.find((item) => item.id === effectiveBasemap);
    if (option?.available) return;
    if (basemapOptions.find((item) => item.id === "pre")?.available) {
      onBasemapChange("pre");
    } else if (basemapOptions.find((item) => item.id === "post")?.available) {
      onBasemapChange("post");
    } else {
      onBasemapChange("street");
    }
  }, [
    effectiveBasemap,
    basemapOptions,
    imageryReady,
    onBasemapChange,
    cinematicEnabled,
    cinematicBasemap,
  ]);

  const onImagery = !isIdle && (effectiveBasemap === "post" || effectiveBasemap === "pre");
  const imageryAvailable =
    (effectiveBasemap === "pre" && Boolean(imagery?.pre)) ||
    (effectiveBasemap === "post" && Boolean(imagery?.post));
  const imageryUrl =
    onImagery && aoiId && bounds && imageryAvailable
      ? `/api/aois/${encodeURIComponent(aoiId)}/imagery/${effectiveBasemap}`
      : null;

  const showImageryOverlay =
    Boolean(imageryUrl) &&
    (!cinematicEnabled ||
      (revealPhase === "pre" && readiness.canPre && prePreviewReady) ||
      revealPhase === "post" ||
      revealPhase === "polygons" ||
      revealPhase === "settled");
  const streetRefOpacity =
    onImagery && showImageryOverlay ? STREET_REFERENCE_TILES.opacity * axisOpacity : 0;
  const showMarkers = !isIdle && (!cinematicEnabled || markersRevealed || Boolean(focusMap));
  /** Keep the chrome mounted so Street ↔ imagery can opacity-fade; stay put on Pre ↔ Post. */
  const timelineMounted =
    !isIdle && Boolean(bounds) && (Boolean(imagery?.pre) || Boolean(imagery?.post));
  const timelineVisible =
    timelineMounted &&
    onImagery &&
    showImageryOverlay &&
    (!cinematicEnabled ||
      revealPhase === "pre" ||
      revealPhase === "post" ||
      revealPhase === "polygons" ||
      revealPhase === "settled");
  const imageryCrossfade = onImagery && showImageryOverlay;

  const style = useMemo(
    () =>
      (feature?: GeoJSON.Feature): L.PathOptions => ({
        color: onImagery ? "#ffffff" : "#334155",
        weight: onImagery ? 0.9 : 0.6,
        fillColor: damageColor(String(feature?.properties?.damage_label ?? "unknown")),
        fillOpacity: onImagery ? 0.72 : 0.72,
      }),
    [onImagery],
  );

  const mapCenter = cinematicEnabled || isIdle
    ? CONUS_CENTER
    : (center ??
      (bounds
        ? ([(bounds[1] + bounds[3]) / 2, (bounds[0] + bounds[2]) / 2] as [number, number])
        : CONUS_CENTER));

  const popoverAnchor = useMemo(() => {
    if (!regionSelection || !mapWrapRef.current) return null;
    const width = mapWrapRef.current.clientWidth;
    const height = mapWrapRef.current.clientHeight;
    const popoverWidth = 220;
    const popoverHeight = 260;
    return {
      x: Math.max(8, Math.min(regionSelection.anchor.x + 8, width - popoverWidth)),
      y: Math.max(8, Math.min(regionSelection.anchor.y + 8, height - popoverHeight)),
    };
  }, [regionSelection]);

  return (
    <div>
      <div
        className={`map-wrap ${isIdle ? "map-wrap-idle" : ""} ${
          regionSelectEnabled ? "map-region-select-active" : ""
        } ${
          cinematicEnabled && revealPhase !== "settled" ? "map-cinematic-active" : ""
        }`}
        ref={mapWrapRef}
      >
        <MapContainer
          center={mapCenter}
          zoom={cinematicEnabled || isIdle ? CONUS_ZOOM : 15}
          style={{ height: "100%", width: "100%" }}
          attributionControl={false}
        >
          <MapResizeHandler />
          <IdleConusSnap active={isIdle} />
          <BuildingsPane revealed={!isIdle && polygonsRevealed && showBuildingPolygons} />
          <PriorityPane revealed={!isIdle && priorityReveal.revealed} />
          <StreetOverlayPane opacity={isIdle ? 0 : streetRefOpacity} />
          <SituationPanes
            weatherRevealed={!isIdle && weatherReveal.revealed}
            roadsRevealed={!isIdle && roadsReveal.revealed}
          />
          {!isIdle && (
            <>
              <BasemapControl
                basemap={effectiveBasemap}
                options={basemapOptions}
                onChange={(id) => {
                  if (cinematicBasemap) return;
                  onBasemapChange(id);
                }}
              />
              <BuildingScopeMapControl
                value={buildingScope === "vlm" ? "official" : buildingScope}
                onChange={(scope) => onBuildingScopeChange?.(scope)}
                showFused={showFusedBuildingScope}
                pending={buildingScopePending}
              />
              <RecenterAoiControl disabled={!bounds} onRecenter={handleRecenter} />
              {bounds && <RecenterAoiView bounds={bounds} requestKey={recenterRequestKey} />}
              <CinematicApproach
                aoiId={aoiId}
                bounds={bounds}
                enabled={cinematicEnabled}
                onPhase={handleRevealPhase}
              />
              <RegionSelectControl
                enabled={regionSelectEnabled}
                onToggle={toggleRegionSelect}
                disabled={!buildingsGeojson}
              />
              <BuildingsLayerControl
                visible={showBuildingPolygons}
                onToggle={toggleBuildingPolygons}
                disabled={!buildingsGeojson}
              />
              <PriorityLayerControl
                enabled={priorityVisible}
                onToggle={togglePriority}
                disabled={!priorityCells}
              />
              <SituationLayerControl
                enabled={situationVisible}
                onToggle={toggleSituation}
                disabled={!situationWeather}
                loading={situationLoading && !situationWeather}
              />
              <SituationRoadControl
                enabled={roadsVisible}
                onToggle={toggleRoads}
                disabled={!situationRoads}
                loading={situationRoadsLoading && !situationRoads}
              />
              <MapRegionSelect
                enabled={regionSelectEnabled}
                buildingsGeojson={buildingsGeojson ?? null}
                onSelection={handleRegionSelection}
              />
            </>
          )}
          {(isIdle || onImagery || (cinematicEnabled && effectiveBasemap !== "street")) && (
            <TileLayer
              key="context-satellite"
              url={CONTEXT_SATELLITE_TILES.url}
              attribution={CONTEXT_SATELLITE_TILES.attribution}
              maxZoom={CONTEXT_SATELLITE_TILES.maxZoom}
            />
          )}
          {!isIdle && effectiveBasemap === "street" && (
            <TileLayer
              key="street"
              url={STREET_TILES.url}
              attribution={STREET_TILES.attribution}
              subdomains={STREET_TILES.subdomains}
              maxZoom={STREET_TILES.maxZoom}
            />
          )}
          {showImageryOverlay && imageryUrl && bounds && imageryCorners && (
            <RotatedImageryOverlay
              key={`${aoiId}-${effectiveBasemap}-rotated`}
              url={imageryUrl}
              corners={imageryCorners}
              opacity={1}
              fadeIn={imageryCrossfade}
            />
          )}
          {showImageryOverlay && imageryUrl && bounds && !imageryCorners && (
            <FadingImageOverlay
              key={`${aoiId}-${effectiveBasemap}-box`}
              url={imageryUrl}
              bounds={boundsToLeaflet(bounds)}
              opacity={axisOpacity}
            />
          )}
          {onImagery && showImageryOverlay && (
            <TileLayer
              key="street-reference"
              pane="streetOverlayPane"
              url={STREET_REFERENCE_TILES.url}
              attribution={STREET_REFERENCE_TILES.attribution}
              subdomains={STREET_REFERENCE_TILES.subdomains}
              maxZoom={STREET_REFERENCE_TILES.maxZoom}
              opacity={STREET_REFERENCE_TILES.opacity}
            />
          )}
          {situationWeather && weatherReveal.mounted && (
            <>
              <SituationChoroplethLayer
                weather={situationWeather}
                hourIndex={hourIndex}
                fillMode="temperature"
              />
              <SituationClimateLabels weather={situationWeather} hourIndex={hourIndex} />
              <SituationWindLayer weather={situationWeather} hourIndex={hourIndex} />
            </>
          )}
          {situationRoads && roadsReveal.mounted && <SituationRoadLayer roads={situationRoads} />}
          <FocusMapTarget
            focus={focusMap}
            markerRefs={markerRefs}
            buildingLayerRefs={buildingLayerRefs}
          />
          {aoiId && buildingsGeojson && showBuildingPolygons && (
            <GeoJSON
              key={`${aoiId}-${effectiveBasemap}-${buildingScope}`}
              data={buildingsGeojson}
              pane="buildingsPane"
              style={style}
              onEachFeature={(feature, layer) => {
                const props = feature.properties ?? {};
                layer.bindPopup(buildingPopupHtml(aoiId, props), {
                  maxWidth: 360,
                  minWidth: 280,
                });
                const bldId = String(props.BLD_ID ?? "");
                if (bldId) {
                  buildingLayerRefs.current[bldId] = layer;
                }
                if ("bringToFront" in layer && typeof layer.bringToFront === "function") {
                  layer.bringToFront();
                }
              }}
            />
          )}
          {showMarkers &&
            hospitals.map((hospital) => {
            const coords =
              hospital.coordinates_wgs84 ??
              (hospital.latitude != null && hospital.longitude != null
                ? ([hospital.longitude, hospital.latitude] as [number, number])
                : null);
            if (!coords) return null;
            const rowKey = hospitalRowKey(hospital);
            return (
              <Marker
                key={`${hospital.kind || "facility"}-${rowKey}`}
                position={[coords[1], coords[0]]}
                icon={facilityMarkerIcon(hospital.kind)}
                ref={(marker) => {
                  if (marker) {
                    markerRefs.current[rowKey] = marker;
                  } else {
                    delete markerRefs.current[rowKey];
                  }
                }}
              >
                <Popup minWidth={260} maxWidth={340}>
                  <HospitalMapPopup hospital={hospital} />
                </Popup>
              </Marker>
            );
          })}
          {showMarkers &&
            focusMap?.kind === "hospital" &&
            !findHospitalForFocus(hospitals, focusMap) && (
              <Marker
                key={`chat-focus-${focusMap.key}`}
                position={[focusMap.coordinates_wgs84[1], focusMap.coordinates_wgs84[0]]}
                icon={facilityMarkerIcon(focusMap.facilityKind)}
                ref={(marker) => {
                  if (marker) {
                    markerRefs.current[focusMap.hospitalKey] = marker;
                  } else {
                    delete markerRefs.current[focusMap.hospitalKey];
                  }
                }}
              >
                <Popup minWidth={260} maxWidth={340}>
                  <HospitalMapPopup
                    hospital={{
                      name: focusMap.name,
                      coordinates_wgs84: focusMap.coordinates_wgs84,
                      distance_mi: focusMap.distance_mi
                        ? Number(focusMap.distance_mi)
                        : undefined,
                      phone: focusMap.phone,
                      email: focusMap.email,
                      website: focusMap.website,
                      operator: focusMap.operator,
                      contact_name: focusMap.contact_name,
                      emergency: focusMap.emergency,
                      beds: focusMap.beds,
                      opening_hours: focusMap.opening_hours,
                      address: focusMap.address,
                      osm_type: focusMap.osm_type,
                      osm_id: focusMap.osm_id,
                      kind: focusMap.facilityKind,
                    }}
                  />
                </Popup>
              </Marker>
            )}
          {focusMap?.kind === "road" && (
            <Marker
              key={`chat-road-focus-${focusMap.key}`}
              position={[focusMap.coordinates_wgs84[1], focusMap.coordinates_wgs84[0]]}
              icon={facilityFocusIcon}
              ref={(marker) => {
                const refKey = `road-${focusMap.roadId}`;
                if (marker) {
                  markerRefs.current[refKey] = marker;
                } else {
                  delete markerRefs.current[refKey];
                }
              }}
            >
              <Popup minWidth={220} maxWidth={300}>
                <div className="hospital-popup">
                  <div className="hospital-popup-title">{focusMap.name}</div>
                  <dl className="hospital-popup-details">
                    {focusMap.roadKind && (
                      <>
                        <dt>Type</dt>
                        <dd>{String(focusMap.roadKind).replace(/_/g, " ")}</dd>
                      </>
                    )}
                    {focusMap.severity && (
                      <>
                        <dt>Severity</dt>
                        <dd>{focusMap.severity}</dd>
                      </>
                    )}
                  </dl>
                </div>
              </Popup>
            </Marker>
          )}
          {priorityReveal.mounted &&
            (() => {
              const cells =
                (focusMap?.kind === "region" && focusMap.cells && focusMap.cells.length > 0
                  ? focusMap.cells
                  : priorityCells) ?? null;
              if (!cells || cells.length === 0) {
                if (focusMap?.kind === "region") {
                  return (
                    <Rectangle
                      key={`chat-region-focus-${focusMap.key}`}
                      bounds={[
                        [focusMap.bounds_wgs84[1], focusMap.bounds_wgs84[0]],
                        [focusMap.bounds_wgs84[3], focusMap.bounds_wgs84[2]],
                      ]}
                      pathOptions={{ ...priorityRegionStyle(focusMap.priority), pane: "priorityPane" }}
                      pane="priorityPane"
                    >
                      <Tooltip
                        permanent
                        direction="center"
                        pane="priorityLabelPane"
                        className="priority-region-tooltip"
                      >
                        <div className="priority-cell-label">{focusMap.name}</div>
                      </Tooltip>
                    </Rectangle>
                  );
                }
                return null;
              }
              return (
                <PriorityGridOverlay
                  key="priority-overlay"
                  cells={cells}
                  focus={
                    focusMap?.kind === "region"
                      ? {
                          priority: focusMap.priority,
                          direction: focusMap.direction,
                          bounds_wgs84: focusMap.bounds_wgs84,
                          name: focusMap.name,
                        }
                      : null
                  }
                />
              );
            })()}
        </MapContainer>
        {timelineMounted && (
          <div
            className={`map-imagery-timeline ${
              timelineVisible ? "map-imagery-timeline-visible" : ""
            }`}
            aria-hidden={!timelineVisible}
          >
            <div
              className={`map-imagery-timeline-item ${
                effectiveBasemap === "pre" ||
                (cinematicEnabled && revealPhase === "pre")
                  ? "active"
                  : ""
              }`}
            >
              <span className="map-imagery-timeline-label">Pre</span>
              <span className="map-imagery-timeline-date">
                {imageryTimeline?.pre?.trim() || "—"}
              </span>
            </div>
            <div className="map-imagery-timeline-rule" />
            <div
              className={`map-imagery-timeline-item ${
                effectiveBasemap === "post" &&
                !(cinematicEnabled && revealPhase === "pre")
                  ? "active"
                  : ""
              }`}
            >
              <span className="map-imagery-timeline-label">Post</span>
              <span className="map-imagery-timeline-date">
                {imageryTimeline?.post?.trim() || "—"}
              </span>
            </div>
          </div>
        )}
        {situationWeather && weatherReveal.mounted && (
          <SituationOverlay
            weather={situationWeather}
            hourIndex={hourIndex}
            onHourChange={setHourIndex}
            visible={weatherReveal.revealed}
          />
        )}
        {situationRoads && roadsReveal.mounted && (
          <SituationRoadChip
            roads={situationRoads}
            visible={roadsReveal.revealed}
            withTimeline={Boolean(situationWeather && weatherReveal.revealed)}
          />
        )}
        {regionSelection && popoverAnchor && (
          <RegionStatsPopover
            stats={regionSelection.stats}
            anchor={popoverAnchor}
            onClose={clearRegionSelection}
          />
        )}
        {isIdle && <p className="map-idle-caption">{idleCaption}</p>}
      </div>
      {!isIdle && (
        <>
          <div className="legend">
            {[
              ["no_damage", "No damage"],
              ["minor", "Minor"],
              ["major", "Major"],
              ["destroyed", "Destroyed"],
            ].map(([label, text]) => (
              <span className="legend-item" key={label}>
                <span className="legend-swatch" style={{ background: damageColor(label) }} />
                {text}
              </span>
            ))}
            {onImagery && (
              <span className="legend-item" style={{ marginLeft: "0.5rem", color: "#64748b" }}>
                AOI:{" "}
                {effectiveBasemap === "post" ? "Post-disaster (NOAA ERI)" : "Pre-disaster (Maxar)"} ·
                streets: OSM/CARTO · context: Esri
              </span>
            )}
          </div>
          <p className="map-scope-note">
            <strong>
              {buildingScope === "fused"
                ? "Official+"
                : buildingScope === "vlm"
                  ? "VLM"
                  : "Official"}
            </strong>
            {regionSelectEnabled && (
              <>
                {" · "}
                <strong>Select area</strong>
              </>
            )}
            {!showBuildingPolygons && (
              <>
                {" · "}
                <strong>Polygons off</strong>
              </>
            )}
            {situationWeather && situationVisible && (
              <>
                {" · "}
                <strong>Weather</strong>
              </>
            )}
            {situationRoads && roadsVisible && (
              <>
                {" · "}
                <strong>Roads</strong>
              </>
            )}
            {situationLoading && (
              <>
                {" · "}
                Weather…
              </>
            )}
            {situationRoadsLoading && (
              <>
                {" · "}
                Roads…
              </>
            )}
            {situationError && !situationWeather && (
              <>
                {" · "}
                Weather unavailable
              </>
            )}
            {situationRoadsError && !situationRoads && (
              <>
                {" · "}
                Roads unavailable
              </>
            )}
          </p>
        </>
      )}
    </div>
  );
}
