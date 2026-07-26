import { useCallback, useEffect, useMemo, useRef, useState, type MutableRefObject } from "react";
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
  aoiId: string;
  bounds?: [number, number, number, number];
  imagery?: { pre?: boolean; post?: boolean };
  imageryCorners?: ImageryCorners | null;
  buildingsGeojson?: GeoJSON.FeatureCollection | null;
  buildingScope?: BuildingScope;
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

function FitBounds({ bounds }: { bounds: [number, number, number, number] }) {
  const map = useMap();
  useEffect(() => {
    map.fitBounds(boundsToLeaflet(bounds), { padding: [24, 24] });
  }, [bounds, map]);
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
    map.flyToBounds(boundsToLeaflet(bounds), { padding: [28, 28], duration: 0.7, maxZoom: 17 });
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

  useEffect(() => {
    if (!focus) {
      lastFocusKeyRef.current = null;
      return;
    }
    // Only fly once per focus request — re-renders / layout tweaks must not yank the view back.
    if (lastFocusKeyRef.current === focus.key) return;
    lastFocusKeyRef.current = focus.key;

    map.invalidateSize({ pan: false });

    if (focus.kind === "region") {
      const overview = focus.aoiBounds ?? focus.bounds_wgs84;
      const [west, south, east, north] = overview;
      map.flyToBounds(
        [
          [south, west],
          [north, east],
        ],
        { padding: [40, 40], duration: 0.8, maxZoom: 16 },
      );
      return;
    }

    if (focus.kind === "weather") {
      if (focus.aoiBounds) {
        const [west, south, east, north] = focus.aoiBounds;
        map.flyToBounds(
          [
            [south, west],
            [north, east],
          ],
          { padding: [40, 40], duration: 0.8, maxZoom: 16 },
        );
      }
      return;
    }

    const [lon, lat] = focus.coordinates_wgs84;
    const targetZoom = Math.max(map.getZoom(), 15);
    map.flyTo([lat, lon], targetZoom, { duration: 0.75 });
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
    }, 600);
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
      fillColor: "#4a1c18",
      fillOpacity: 0.52,
      className: "priority-grid-cell priority-grid-focused",
    };
  }
  if (priority === 2) {
    return {
      color: "#7c8a9a",
      weight: 1.5,
      fillColor: "#8f5246",
      fillOpacity: 0.38,
      className: "priority-grid-cell",
    };
  }
  return {
    color: "#7c8a9a",
    weight: 1.25,
    fillColor: "#b9a094",
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
 * Low-chroma sequential ramp (low → high Score).
 * Stays in one warm family so the 3×3 reads as one layer, not a rainbow.
 * High end is deepened so top-priority cells read clearly against imagery.
 */
const SEVERITY_RAMP: Array<{ t: number; hex: string }> = [
  { t: 0, hex: "#c5ced9" },
  { t: 0.35, hex: "#b9a094" },
  { t: 0.65, hex: "#8f5246" },
  { t: 1, hex: "#4a1c18" },
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
    fillOpacity: focused ? 0.56 : hovered ? Math.min(0.62, 0.34 + t * 0.34) : 0.28 + t * 0.34,
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
        const baseStyle = gridCellStyle(cell, { maxImpact, focused });
        return (
          <Rectangle
            key={`priority-grid-${cell.direction}`}
            bounds={[
              [cell.bounds_wgs84[1], cell.bounds_wgs84[0]],
              [cell.bounds_wgs84[3], cell.bounds_wgs84[2]],
            ]}
            pathOptions={baseStyle}
            eventHandlers={{
              mouseover: (event) => {
                const layer = event.target as L.Path;
                layer.setStyle(gridCellStyle(cell, { maxImpact, focused, hovered: true }));
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

function BuildingsPane() {
  const map = useMap();
  useEffect(() => {
    if (!map.getPane("buildingsPane")) {
      map.createPane("buildingsPane");
      const pane = map.getPane("buildingsPane");
      if (pane) pane.style.zIndex = "450";
    }
  }, [map]);
  return null;
}

/** Street lines/names above imagery, below building polygons. */
function StreetOverlayPane() {
  const map = useMap();
  useEffect(() => {
    if (!map.getPane("streetOverlayPane")) {
      map.createPane("streetOverlayPane");
      const pane = map.getPane("streetOverlayPane");
      if (pane) {
        pane.style.zIndex = "425";
        pane.style.pointerEvents = "none";
      }
    }
  }, [map]);
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
}: Props) {
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
    if (!imageryReady || basemap === "street") return;
    const option = basemapOptions.find((item) => item.id === basemap);
    if (option?.available) return;
    if (basemapOptions.find((item) => item.id === "pre")?.available) {
      onBasemapChange("pre");
    } else if (basemapOptions.find((item) => item.id === "post")?.available) {
      onBasemapChange("post");
    } else {
      onBasemapChange("street");
    }
  }, [basemap, basemapOptions, imageryReady, onBasemapChange]);

  const onImagery = basemap === "post" || basemap === "pre";
  const imageryUrl =
    onImagery && bounds
      ? `/api/aois/${encodeURIComponent(aoiId)}/imagery/${basemap}`
      : null;

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

  const mapCenter = center ?? (bounds
    ? ([(bounds[1] + bounds[3]) / 2, (bounds[0] + bounds[2]) / 2] as [number, number])
    : ([34.082889, -118.598699] as [number, number]));

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
        className={`map-wrap ${regionSelectEnabled ? "map-region-select-active" : ""}`}
        ref={mapWrapRef}
      >
        <MapContainer
          center={mapCenter}
          zoom={15}
          style={{ height: "100%", width: "100%" }}
          attributionControl={false}
        >
          <MapResizeHandler />
          <BuildingsPane />
          <StreetOverlayPane />
          <SituationPanes />
          <BasemapControl basemap={basemap} options={basemapOptions} onChange={onBasemapChange} />
          <RecenterAoiControl disabled={!bounds} onRecenter={handleRecenter} />
          {bounds && <RecenterAoiView bounds={bounds} requestKey={recenterRequestKey} />}
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
          />
          <SituationRoadControl
            enabled={roadsVisible}
            onToggle={toggleRoads}
            disabled={!situationRoads}
          />
          <MapRegionSelect
            enabled={regionSelectEnabled}
            buildingsGeojson={buildingsGeojson ?? null}
            onSelection={handleRegionSelection}
          />
          {onImagery && (
            <TileLayer
              key="context-satellite"
              url={CONTEXT_SATELLITE_TILES.url}
              attribution={CONTEXT_SATELLITE_TILES.attribution}
              maxZoom={CONTEXT_SATELLITE_TILES.maxZoom}
            />
          )}
          {basemap === "street" && (
            <TileLayer
              key="street"
              url={STREET_TILES.url}
              attribution={STREET_TILES.attribution}
              subdomains={STREET_TILES.subdomains}
              maxZoom={STREET_TILES.maxZoom}
            />
          )}
          {imageryUrl && bounds && imageryCorners && (
            <RotatedImageryOverlay url={imageryUrl} corners={imageryCorners} />
          )}
          {imageryUrl && bounds && !imageryCorners && (
            <ImageOverlay url={imageryUrl} bounds={boundsToLeaflet(bounds)} opacity={1} zIndex={0} />
          )}
          {onImagery && (
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
          {situationWeather && situationVisible && (
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
          {situationRoads && roadsVisible && <SituationRoadLayer roads={situationRoads} />}
          {bounds && <FitBounds bounds={bounds} />}
          <FocusMapTarget
            focus={focusMap}
            markerRefs={markerRefs}
            buildingLayerRefs={buildingLayerRefs}
          />
          {buildingsGeojson && showBuildingPolygons && (
            <GeoJSON
              key={`${aoiId}-${basemap}-${buildingScope}`}
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
          {hospitals.map((hospital) => {
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
          {focusMap?.kind === "hospital" &&
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
          {priorityVisible &&
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
                      pathOptions={priorityRegionStyle(focusMap.priority)}
                    >
                      <Tooltip permanent direction="center" className="priority-region-tooltip">
                        <div className="priority-cell-label">{focusMap.name}</div>
                      </Tooltip>
                    </Rectangle>
                  );
                }
                return null;
              }
              return (
                <PriorityGridOverlay
                  key={`priority-overlay-${focusMap?.kind === "region" ? focusMap.key : "layer"}`}
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
        {situationWeather && (
          <SituationOverlay
            weather={situationWeather}
            hourIndex={hourIndex}
            onHourChange={setHourIndex}
            visible={situationVisible}
          />
        )}
        {situationRoads && (
          <SituationRoadChip
            roads={situationRoads}
            visible={roadsVisible}
            withTimeline={Boolean(situationWeather && situationVisible)}
          />
        )}
        {regionSelection && popoverAnchor && (
          <RegionStatsPopover
            stats={regionSelection.stats}
            anchor={popoverAnchor}
            onClose={clearRegionSelection}
          />
        )}
      </div>
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
            AOI: {basemap === "post" ? "Post-disaster (NOAA ERI)" : "Pre-disaster (Maxar)"} · streets:
            OSM/CARTO · context: Esri
          </span>
        )}
      </div>
      <p className="map-scope-note">
        Building layer: <strong>{BUILDING_SCOPE_LABELS[buildingScope]}</strong>
        {" — "}
        {BUILDING_SCOPE_HINTS[buildingScope]}
        {regionSelectEnabled && (
          <>
            {" · "}
            <strong>Select area:</strong> drag on the map to summarize damage in the box
          </>
        )}
        {!showBuildingPolygons && (
          <>
            {" · "}
            <strong>Polygons hidden</strong>
          </>
        )}
        {situationWeather && situationVisible && (
          <>
            {" · "}
            <strong>Situation layer</strong> — Temp wash + humidity labels + timeline scrub
          </>
        )}
        {situationRoads && roadsVisible && (
          <>
            {" · "}
            <strong>Road conditions</strong> — closures / lane restrictions
          </>
        )}
        {situationLoading && (
          <>
            {" · "}
            Loading situation forecast…
          </>
        )}
        {situationRoadsLoading && (
          <>
            {" · "}
            Loading road conditions…
          </>
        )}
        {situationError && !situationWeather && (
          <>
            {" · "}
            Situation forecast unavailable
          </>
        )}
        {situationRoadsError && !situationRoads && (
          <>
            {" · "}
            Road conditions unavailable
          </>
        )}
      </p>
    </div>
  );
}
