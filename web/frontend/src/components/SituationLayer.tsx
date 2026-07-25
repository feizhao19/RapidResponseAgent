import { useEffect, useMemo, useRef, type ReactNode } from "react";
import { GeoJSON, Marker, useMap } from "react-leaflet";
import L from "leaflet";
import type { SituationRoads, SituationWeather } from "../api/client";
import {
  TIMELINE_TICKS,
  cToF,
  formatHourLabel,
  humidityFill,
  humidityBandLabel,
  kmhToMph,
  situationCellGeoJson,
  temperatureFill,
  windArrowRotationDeg,
  windPointsAtHour,
  type SituationFillMode,
} from "../situationWeather";
import {
  roadCasingColor,
  roadCasingWeight,
  roadKindLabel,
  roadLineAnchor,
  roadStrokeColor,
  roadStrokeWeight,
  roadSummaryCounts,
  roadSummaryLabel,
  situationRoadsGeoJson,
} from "../situationRoads";

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function roadMarkerIcon(
  kind: string,
  severity: "closed" | "major" | "minor",
): L.DivIcon {
  const color = roadStrokeColor(severity, kind as SituationRoads["features"][number]["kind"]);
  const isIncident = kind === "incident";
  const isClosed = severity === "closed" || kind === "closure";
  const size = isClosed ? 28 : isIncident && severity === "major" ? 26 : 22;
  const symbol = isClosed
    ? `<path d="M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16zm3.5 8.7H8.5v-1.4h7v1.4z" fill="${color}"/>`
    : isIncident
      ? `<path d="M12 3.2 21 20.5H3L12 3.2zm0 5.3-4.8 9h9.6L12 8.5zm-.7 3.2h1.4v3.2h-1.4V11.7zm0 4h1.4V17h-1.4v-1.3z" fill="${color}"/>`
      : `<circle cx="12" cy="12" r="6.5" fill="${color}"/>`;
  return L.divIcon({
    className: "situation-road-marker",
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
    html: `<div class="situation-road-marker-inner" style="width:${size}px;height:${size}px">
      <svg viewBox="0 0 24 24" width="${size}" height="${size}" aria-hidden="true">${symbol}</svg>
    </div>`,
  });
}

function roadPopupHtml(props: GeoJSON.GeoJsonProperties): string {
  const p = props ?? {};
  const title = escapeHtml(String(p.title ?? "Road condition"));
  const description = escapeHtml(String(p.description ?? ""));
  const status = String(p.status ?? "");
  const severity = String(p.severity ?? "");
  const kind = String(p.kind ?? "");
  const source = escapeHtml(String(p.source ?? ""));
  const kindLabel = escapeHtml(roadKindLabel(kind));
  const statusBit = status === "scheduled" ? "Scheduled" : "Active";
  return `<div class="situation-road-popup">
    <div class="situation-road-popup-badge kind-${escapeHtml(kind)} sev-${escapeHtml(severity)}">${kindLabel}</div>
    <div class="situation-road-popup-title">${title}</div>
    <div class="situation-road-popup-meta">${escapeHtml(statusBit)} · ${escapeHtml(severity)}${source ? ` · ${source}` : ""}</div>
    ${description ? `<div class="situation-road-popup-desc">${description}</div>` : ""}
  </div>`;
}

/** Shared Leaflet glass toggle — same pattern as Select area / Polygons. */
function useMapGlassToggle({
  className,
  label,
  labelOff,
  titleOn,
  titleOff,
  active,
  onToggle,
  disabled,
  position = "topleft",
}: {
  className: string;
  label: string;
  labelOff?: string;
  titleOn: string;
  titleOff: string;
  active: boolean;
  onToggle: () => void;
  disabled?: boolean;
  position?: L.ControlPosition;
}) {
  const map = useMap();
  const onToggleRef = useRef(onToggle);
  onToggleRef.current = onToggle;
  const disabledRef = useRef(disabled);
  disabledRef.current = disabled;

  useEffect(() => {
    const control = new L.Control({ position });
    control.onAdd = () => {
      const container = L.DomUtil.create("div", className);
      L.DomEvent.disableClickPropagation(container);
      L.DomEvent.disableScrollPropagation(container);
      const button = L.DomUtil.create("button", "", container);
      button.type = "button";
      button.textContent = label;
      button.title = titleOn;
      button.addEventListener("click", () => {
        if (!disabledRef.current) onToggleRef.current();
      });
      return container;
    };
    control.addTo(map);
    return () => {
      control.remove();
    };
  }, [map, className, label, titleOn, position]);

  useEffect(() => {
    const button = map
      .getContainer()
      .querySelector(`.${className} button`) as HTMLButtonElement | null;
    if (!button) return;
    button.classList.toggle("active", active);
    button.disabled = Boolean(disabled);
    button.textContent = !active && labelOff ? labelOff : label;
    button.title = active ? titleOn : titleOff;
  }, [active, disabled, map, className, label, labelOff, titleOn, titleOff]);
}

export function SituationPanes() {
  const map = useMap();
  useEffect(() => {
    const ensurePane = (name: string, zIndex: string, pointerEvents?: string) => {
      if (!map.getPane(name)) map.createPane(name);
      const pane = map.getPane(name);
      if (!pane) return;
      pane.style.zIndex = zIndex;
      if (pointerEvents) pane.style.pointerEvents = pointerEvents;
    };
    // Weather / roads above buildingsPane (450) so polygons do not cover them.
    ensurePane("humidityPane", "455", "none");
    ensurePane("tempLabelPane", "458", "none");
    ensurePane("windPane", "460", "none");
    ensurePane("roadPane", "465");
  }, [map]);
  return null;
}

type ControlProps = {
  enabled: boolean;
  onToggle: () => void;
  disabled?: boolean;
};

export function SituationLayerControl({ enabled, onToggle, disabled }: ControlProps) {
  useMapGlassToggle({
    className: "leaflet-situation-weather-control",
    label: "Weather",
    labelOff: "Weather off",
    titleOn: "Hide wind / humidity / temperature situation layer",
    titleOff: "Show wind / humidity / temperature situation layer",
    active: enabled,
    onToggle,
    disabled,
  });
  return null;
}

export function SituationRoadControl({ enabled, onToggle, disabled }: ControlProps) {
  useMapGlassToggle({
    className: "leaflet-situation-roads-control",
    label: "Roads",
    labelOff: "Roads off",
    titleOn: "Hide road closures and CHP incidents",
    titleOff: "Show road closures and CHP incidents",
    active: enabled,
    onToggle,
    disabled,
  });
  return null;
}

function windIcon(
  speedKmh: number | null,
  fromDeg: number | null,
  delaySec = 0,
): L.DivIcon {
  const mph = kmhToMph(speedKmh) ?? 0;
  const intensity = Math.max(0, Math.min(1, mph / 35));
  const width = Math.round(22 + intensity * 10);
  const height = Math.round(36 + intensity * 14);
  const rot = windArrowRotationDeg(fromDeg);
  // Faster wind → shorter period (1.6s … 0.75s).
  const duration = (1.55 - intensity * 0.8).toFixed(2);
  const delay = (delaySec % 1.4).toFixed(2);
  return L.divIcon({
    className: "situation-wind-icon",
    iconSize: [width, height],
    iconAnchor: [width / 2, height / 2],
    html: `<div class="situation-wind" style="--wind-rot:${rot}deg;--wind-dur:${duration}s;--wind-delay:${delay}s;width:${width}px;height:${height}px">
      <div class="situation-wind-shaft" aria-hidden="true"></div>
      <div class="situation-wind-stream" aria-hidden="true">
        <span class="situation-wind-mark"></span>
        <span class="situation-wind-mark"></span>
        <span class="situation-wind-mark"></span>
      </div>
      <div class="situation-wind-head" aria-hidden="true"></div>
    </div>`,
  });
}

function tempLabelIcon(tempC: number | null): L.DivIcon {
  const f = cToF(tempC);
  const text = f != null ? `${f}°` : "—";
  return L.divIcon({
    className: "situation-temp-label-icon",
    iconSize: [36, 18],
    iconAnchor: [18, 9],
    html: `<span class="situation-temp-label">${text}</span>`,
  });
}

function cellClimateIcon(
  tempC: number | null,
  rhPct: number | null,
): L.DivIcon {
  const f = cToF(tempC);
  const tempText = f != null ? `${f}°` : "—";
  const rhText = rhPct != null ? `${Math.round(rhPct)}%` : "—";
  return L.divIcon({
    className: "situation-cell-label-icon",
    iconSize: [44, 30],
    // Sit well above the wind mark at the cell center (larger Y = higher on map).
    iconAnchor: [22, 52],
    html: `<div class="situation-cell-label">
      <span class="situation-cell-temp">${tempText}</span>
      <span class="situation-cell-rh">${rhText}</span>
    </div>`,
  });
}

type LayersProps = {
  weather: SituationWeather;
  hourIndex: number;
  fillMode: SituationFillMode;
};

export function SituationChoroplethLayer({ weather, hourIndex, fillMode }: LayersProps) {
  const data = useMemo(() => situationCellGeoJson(weather, hourIndex), [weather, hourIndex]);
  const style = useMemo(
    () => (feature?: GeoJSON.Feature) => {
      const props = feature?.properties ?? {};
      const fill =
        fillMode === "temperature"
          ? temperatureFill(props.temperature_c as number | null | undefined)
          : humidityFill(props.relative_humidity_pct as number | null | undefined);
      return {
        fillColor: fill,
        fillOpacity: 1,
        color: "rgba(15, 23, 42, 0.15)",
        weight: 0.5,
        pane: "humidityPane",
      };
    },
    [fillMode],
  );
  return (
    <GeoJSON
      key={`choropleth-${fillMode}-${hourIndex}-${weather.fetched_at}`}
      data={data}
      style={style}
      pane="humidityPane"
    />
  );
}

/** @deprecated Use SituationChoroplethLayer */
export function SituationHumidityLayer({
  weather,
  hourIndex,
}: {
  weather: SituationWeather;
  hourIndex: number;
}) {
  return <SituationChoroplethLayer weather={weather} hourIndex={hourIndex} fillMode="humidity" />;
}

export function SituationTempLabels({ weather, hourIndex }: { weather: SituationWeather; hourIndex: number }) {
  const points = useMemo(() => windPointsAtHour(weather.cells, hourIndex), [weather, hourIndex]);
  return (
    <>
      {points.map((p) => (
        <Marker
          key={`temp-${p.id}-${hourIndex}`}
          position={[p.lat, p.lon]}
          icon={tempLabelIcon(p.sample.temperature_c)}
          interactive={false}
          pane="tempLabelPane"
        />
      ))}
    </>
  );
}

/** Per-cell temperature (°F) + humidity (%) labels under the wind arrow. */
export function SituationClimateLabels({
  weather,
  hourIndex,
}: {
  weather: SituationWeather;
  hourIndex: number;
}) {
  const points = useMemo(() => windPointsAtHour(weather.cells, hourIndex), [weather, hourIndex]);
  return (
    <>
      {points.map((p) => (
        <Marker
          key={`climate-${p.id}-${hourIndex}`}
          position={[p.lat, p.lon]}
          icon={cellClimateIcon(p.sample.temperature_c, p.sample.relative_humidity_pct)}
          interactive={false}
          pane="tempLabelPane"
        />
      ))}
    </>
  );
}

export function SituationWindLayer({ weather, hourIndex }: { weather: SituationWeather; hourIndex: number }) {
  const points = useMemo(() => windPointsAtHour(weather.cells, hourIndex), [weather, hourIndex]);
  return (
    <>
      {points.map((p, index) => (
        <Marker
          key={`wind-${p.id}-${hourIndex}`}
          position={[p.lat, p.lon]}
          icon={windIcon(p.sample.wind_speed_kmh, p.sample.wind_direction_deg, (index * 0.17) % 1.4)}
          interactive={false}
          pane="windPane"
        />
      ))}
    </>
  );
}

type HudProps = {
  weather: SituationWeather;
  hourIndex: number;
};

export function SituationHUD({ weather, hourIndex }: HudProps) {
  const sample = weather.centroid_series[hourIndex] ?? weather.centroid_series[0];
  if (!sample) return null;
  const mph = kmhToMph(sample.wind_speed_kmh);
  const gustMph = kmhToMph(sample.wind_gusts_kmh);
  const tempF = cToF(sample.temperature_c);
  const band = humidityBandLabel(sample.humidity_band);
  return (
    <div className="situation-hud" aria-live="polite">
      <div className="situation-hud-head">
        <span className="situation-hud-kicker">Weather</span>
        <span className="situation-hud-time">{formatHourLabel(weather.hours[hourIndex], hourIndex)}</span>
      </div>
      <div className="situation-hud-rows">
        <div className="situation-hud-row">
          <span className="situation-hud-label">Wind</span>
          <strong>
            {mph != null ? `${mph} mph` : "—"}
            {gustMph != null ? ` · gust ${gustMph}` : ""}
          </strong>
        </div>
        <div className="situation-hud-row">
          <span className="situation-hud-label">Temp</span>
          <strong>
            {tempF != null ? `${tempF}°F` : "—"}
            {sample.temperature_c != null ? ` (${Math.round(sample.temperature_c)}°C)` : ""}
          </strong>
        </div>
        <div className="situation-hud-row">
          <span className="situation-hud-label">Humidity</span>
          <strong>
            {sample.relative_humidity_pct != null ? `${Math.round(sample.relative_humidity_pct)}%` : "—"}
            <span className={`situation-hud-band band-${sample.humidity_band ?? "moderate"}`}> {band}</span>
          </strong>
        </div>
      </div>
    </div>
  );
}

type TimelineProps = {
  weather: SituationWeather;
  hourIndex: number;
  onChange: (index: number) => void;
};

export function ForecastTimeline({ weather, hourIndex, onChange }: TimelineProps) {
  const max = Math.max(0, Math.min(24, weather.hours.length - 1));
  return (
    <div className="situation-timeline">
      <div className="situation-timeline-label">
        Forecast · {formatHourLabel(weather.hours[hourIndex], hourIndex)}
      </div>
      <input
        type="range"
        className="situation-timeline-slider"
        min={0}
        max={max}
        step={1}
        value={Math.min(hourIndex, max)}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-label="Forecast timeline"
      />
      <div className="situation-timeline-ticks">
        {TIMELINE_TICKS.filter((t) => t.hour <= max).map((t) => (
          <button
            key={t.hour}
            type="button"
            className={hourIndex === t.hour ? "is-active" : undefined}
            onClick={() => onChange(t.hour)}
          >
            {t.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export function SituationOverlay({
  weather,
  hourIndex,
  onHourChange,
  visible,
}: {
  weather: SituationWeather;
  hourIndex: number;
  onHourChange: (index: number) => void;
  visible: boolean;
}): ReactNode {
  if (!visible) return null;
  return (
    <>
      <SituationHUD weather={weather} hourIndex={hourIndex} />
      <ForecastTimeline weather={weather} hourIndex={hourIndex} onChange={onHourChange} />
      <div className="situation-legend" aria-hidden="true">
        <span>Temperature</span>
        <span className="swatch temp-cool" />
        <span className="swatch temp-mild" />
        <span className="swatch temp-warm" />
        <span className="swatch temp-hot" />
        <span className="swatch temp-extreme" />
        <span className="situation-legend-sep">·</span>
        <span>Labels</span>
        <span className="situation-legend-chip">Temp °F</span>
        <span className="situation-legend-chip">Humidity %</span>
      </div>
    </>
  );
}

export function SituationRoadLayer({ roads }: { roads: SituationRoads }) {
  const data = useMemo(() => situationRoadsGeoJson(roads), [roads]);
  const pinFeatures = useMemo(
    () =>
      roads.features.filter((f) => {
        if (f.geometry.type === "Point") return true;
        // Short LCS segments are hard to see — pin the midpoint.
        if (f.geometry.type === "LineString" && f.geometry.coordinates.length <= 3) return true;
        return f.kind === "closure" || f.severity === "closed";
      }),
    [roads.features],
  );

  const onEachFeature = useMemo(
    () => (feature: GeoJSON.Feature, layer: L.Layer) => {
      layer.bindPopup(roadPopupHtml(feature.properties), {
        className: "situation-road-popup-wrap",
        maxWidth: 280,
      });
    },
    [],
  );

  const casingStyle = useMemo(
    () => (feature?: GeoJSON.Feature) => {
      const severity = String(feature?.properties?.severity ?? "minor") as
        | "closed"
        | "major"
        | "minor";
      const kind = String(feature?.properties?.kind ?? "") as SituationRoads["features"][number]["kind"];
      const dashed = String(feature?.properties?.status ?? "") === "scheduled";
      return {
        color: roadCasingColor(kind),
        weight: roadCasingWeight(severity),
        opacity: dashed ? 0.45 : 0.85,
        lineCap: "round" as const,
        lineJoin: "round" as const,
        dashArray: dashed ? "7 8" : undefined,
        pane: "roadPane",
        interactive: false,
      };
    },
    [],
  );

  const strokeStyle = useMemo(
    () => (feature?: GeoJSON.Feature) => {
      const severity = String(feature?.properties?.severity ?? "minor") as
        | "closed"
        | "major"
        | "minor";
      const kind = String(feature?.properties?.kind ?? "") as SituationRoads["features"][number]["kind"];
      const dashed = String(feature?.properties?.status ?? "") === "scheduled";
      return {
        color: roadStrokeColor(severity, kind),
        weight: roadStrokeWeight(severity),
        opacity: dashed ? 0.75 : 1,
        lineCap: "round" as const,
        lineJoin: "round" as const,
        dashArray: dashed ? "7 8" : undefined,
        pane: "roadPane",
      };
    },
    [],
  );

  // Points rendered via Marker pins; GeoJSON pointToLayer unused for Points
  // when we filter — keep a no-op circle for safety.
  const pointToLayer = useMemo(
    () => (_feature: GeoJSON.Feature, latlng: L.LatLng) =>
      L.circleMarker(latlng, {
        radius: 0,
        opacity: 0,
        fillOpacity: 0,
        interactive: false,
        pane: "roadPane",
      }),
    [],
  );

  return (
    <>
      <GeoJSON
        key={`roads-casing-${roads.fetched_at}-${roads.features.length}`}
        data={data}
        style={casingStyle}
        pointToLayer={pointToLayer}
        pane="roadPane"
        interactive={false}
      />
      <GeoJSON
        key={`roads-stroke-${roads.fetched_at}-${roads.features.length}`}
        data={data}
        style={strokeStyle}
        pointToLayer={pointToLayer}
        onEachFeature={onEachFeature}
        pane="roadPane"
      />
      {pinFeatures.map((feature) => {
        const anchor = roadLineAnchor(feature);
        if (!anchor) return null;
        return (
          <Marker
            key={`road-pin-${feature.id}`}
            position={anchor}
            icon={roadMarkerIcon(feature.kind, feature.severity)}
            pane="roadPane"
            eventHandlers={{
              click: (event) => {
                const marker = event.target as L.Marker;
                marker
                  .bindPopup(
                    roadPopupHtml({
                      title: feature.title,
                      description: feature.description ?? "",
                      status: feature.status,
                      severity: feature.severity,
                      kind: feature.kind,
                      source: feature.source,
                    }),
                    { className: "situation-road-popup-wrap", maxWidth: 280 },
                  )
                  .openPopup();
              },
            }}
          />
        );
      })}
    </>
  );
}

export function SituationRoadChip({
  roads,
  visible,
  withTimeline = false,
}: {
  roads: SituationRoads;
  visible: boolean;
  withTimeline?: boolean;
}) {
  if (!visible) return null;
  const counts = roadSummaryCounts(roads);
  return (
    <div
      className={`situation-road-hud${withTimeline ? " with-timeline" : ""}`}
      aria-live="polite"
    >
      <div className="situation-road-hud-head">
        <span className="situation-road-hud-title">Roads</span>
        <span className="situation-road-hud-source">{roads.source}</span>
      </div>
      <div className="situation-road-hud-counts">
        <span className="situation-road-count">
          <i className="dot closed" />
          {counts.closures} closed
        </span>
        <span className="situation-road-count">
          <i className="dot lane" />
          {counts.lanes} lane
        </span>
        <span className="situation-road-count">
          <i className="dot incident" />
          {counts.incidents} CHP
        </span>
      </div>
      <div className="situation-road-hud-legend" aria-hidden="true">
        <span>
          <i className="sym closed" /> Closure
        </span>
        <span>
          <i className="sym lane" /> Lane
        </span>
        <span>
          <i className="sym incident" /> Incident
        </span>
        <span className="muted">{roadSummaryLabel(roads)}</span>
      </div>
    </div>
  );
}
