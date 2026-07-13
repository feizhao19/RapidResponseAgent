import { useCallback, useEffect, useMemo, useRef, useState, type MutableRefObject } from "react";
import {
  GeoJSON,
  ImageOverlay,
  MapContainer,
  Marker,
  Popup,
  TileLayer,
  useMap,
} from "react-leaflet";
import L from "leaflet";
import { buildingChipUrl } from "../api/client";
import type { Hospital } from "../api/client";
import { damageColor } from "../damageColors";
import { BUILDING_SCOPE_HINTS, BUILDING_SCOPE_LABELS, type BuildingScope } from "../buildingScope";
import { hospitalRowKey } from "../hospitalUtils";
import type { MapFocus } from "../mapFocus";
import { HospitalMapPopup } from "./HospitalMapPopup";
import { RotatedImageryOverlay, type ImageryCorners } from "./RotatedImageryOverlay";
import {
  BuildingsLayerControl,
  MapRegionSelect,
  RegionSelectControl,
  type RegionSelection,
} from "./MapRegionSelect";
import { RegionStatsPopover } from "./RegionStatsPopover";

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function buildingPopupHtml(aoiId: string, props: Record<string, unknown>): string {
  const label = escapeHtml(String(props.damage_label ?? "unknown"));
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
  useEffect(() => {
    if (!focus) return;
    map.invalidateSize({ pan: false });
    const [lon, lat] = focus.coordinates_wgs84;
    const targetZoom = Math.max(map.getZoom(), 15);
    map.flyTo([lat, lon], targetZoom, { duration: 0.75 });
    const timer = window.setTimeout(() => {
      if (focus.kind === "hospital") {
        markerRefs.current[focus.hospitalKey]?.openPopup();
        return;
      }
      const layer = buildingLayerRefs.current[focus.bldId];
      if (layer && "openPopup" in layer && typeof layer.openPopup === "function") {
        layer.openPopup();
      }
    }, 600);
    return () => window.clearTimeout(timer);
  }, [focus, map, markerRefs, buildingLayerRefs]);
  return null;
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
      map.invalidateSize();
    });
    observer.observe(target);
    map.invalidateSize();
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
}: Props) {
  const markerRefs = useRef<Record<string, L.Marker>>({});
  const buildingLayerRefs = useRef<Record<string, L.Layer>>({});
  const mapWrapRef = useRef<HTMLDivElement>(null);
  const [regionSelectEnabled, setRegionSelectEnabled] = useState(false);
  const [regionSelection, setRegionSelection] = useState<RegionSelection | null>(null);
  const [showBuildingPolygons, setShowBuildingPolygons] = useState(true);

  const toggleRegionSelect = useCallback(() => {
    setRegionSelectEnabled((current) => {
      if (current) setRegionSelection(null);
      return !current;
    });
  }, []);

  const toggleBuildingPolygons = useCallback(() => {
    setShowBuildingPolygons((current) => !current);
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
  }, [aoiId, buildingScope, buildingsGeojson]);
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
      </p>
      <div
        className={`map-wrap ${regionSelectEnabled ? "map-region-select-active" : ""}`}
        ref={mapWrapRef}
      >
        <MapContainer center={mapCenter} zoom={15} style={{ height: "100%", width: "100%" }}>
          <MapResizeHandler />
          <BuildingsPane />
          <StreetOverlayPane />
          <BasemapControl basemap={basemap} options={basemapOptions} onChange={onBasemapChange} />
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
                key={rowKey}
                position={[coords[1], coords[0]]}
                icon={hospitalIcon}
                ref={(marker) => {
                  if (marker) {
                    markerRefs.current[rowKey] = marker;
                  } else {
                    delete markerRefs.current[rowKey];
                  }
                }}
              >
                <Popup minWidth={240} maxWidth={320}>
                  <HospitalMapPopup hospital={hospital} />
                </Popup>
              </Marker>
            );
          })}
        </MapContainer>
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
          ["no_damage_inferred", "Inferred OK"],
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
    </div>
  );
}
