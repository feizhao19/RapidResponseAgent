import { useEffect, useRef } from "react";
import { useMap } from "react-leaflet";
import L from "leaflet";
import { computeRegionStats, type RegionDamageStats } from "../regionStats";

export type RegionSelection = {
  stats: RegionDamageStats;
  bounds: L.LatLngBounds;
  anchor: { x: number; y: number };
};

type Props = {
  enabled: boolean;
  buildingsGeojson: GeoJSON.FeatureCollection | null;
  onSelection: (selection: RegionSelection | null) => void;
};

const MIN_DRAG_PX = 6;

export function MapRegionSelect({ enabled, buildingsGeojson, onSelection }: Props) {
  const map = useMap();
  const rectangleRef = useRef<L.Rectangle | null>(null);
  const startLatLngRef = useRef<L.LatLng | null>(null);
  const startPointRef = useRef<L.Point | null>(null);
  const draggingRef = useRef(false);

  useEffect(() => {
    const container = map.getContainer();

    if (!enabled) {
      draggingRef.current = false;
      startLatLngRef.current = null;
      startPointRef.current = null;
      container.classList.remove("map-region-select-cursor");
      container.closest(".map-wrap")?.classList.remove("map-region-dragging");
      document.body.classList.remove("map-region-dragging");
      map.dragging.enable();
      if (rectangleRef.current) {
        map.removeLayer(rectangleRef.current);
        rectangleRef.current = null;
      }
      return;
    }

    container.classList.add("map-region-select-cursor");
    const boxZoomWasEnabled = map.boxZoom.enabled();
    const doubleClickWasEnabled = map.doubleClickZoom.enabled();
    map.boxZoom.disable();
    map.doubleClickZoom.disable();

    function setDraggingUi(active: boolean) {
      const mapWrap = container.closest(".map-wrap");
      mapWrap?.classList.toggle("map-region-dragging", active);
      document.body.classList.toggle("map-region-dragging", active);
    }

    function endDrag() {
      draggingRef.current = false;
      startLatLngRef.current = null;
      startPointRef.current = null;
      setDraggingUi(false);
      map.dragging.enable();
    }

    function clearRectangle() {
      if (rectangleRef.current) {
        map.removeLayer(rectangleRef.current);
        rectangleRef.current = null;
      }
    }

    function finishAt(latlng: L.LatLng) {
      const start = startLatLngRef.current;
      endDrag();

      if (!start || !buildingsGeojson) {
        clearRectangle();
        return;
      }

      const bounds = L.latLngBounds(start, latlng);
      const ne = bounds.getNorthEast();
      const sw = bounds.getSouthWest();
      if (Math.abs(ne.lat - sw.lat) < 1e-7 && Math.abs(ne.lng - sw.lng) < 1e-7) {
        clearRectangle();
        onSelection(null);
        return;
      }

      if (rectangleRef.current) {
        rectangleRef.current.setBounds(bounds);
      }

      const stats = computeRegionStats(
        buildingsGeojson,
        sw.lng,
        sw.lat,
        ne.lng,
        ne.lat,
      );
      const anchor = map.latLngToContainerPoint(ne);
      onSelection({ stats, bounds, anchor: { x: anchor.x, y: anchor.y } });
    }

    function onMapMouseDown(event: L.LeafletMouseEvent) {
      if (event.originalEvent.button !== 0) return;
      const target = event.originalEvent.target as HTMLElement | null;
      if (target?.closest(".leaflet-control, .leaflet-popup, .leaflet-marker-icon")) return;

      L.DomEvent.preventDefault(event.originalEvent);
      draggingRef.current = true;
      startLatLngRef.current = event.latlng;
      startPointRef.current = map.latLngToContainerPoint(event.latlng);
      map.dragging.disable();
      setDraggingUi(true);
      clearRectangle();
      onSelection(null);

      rectangleRef.current = L.rectangle(L.latLngBounds(event.latlng, event.latlng), {
        color: "#0071e3",
        weight: 2,
        fillColor: "#0071e3",
        fillOpacity: 0.14,
        dashArray: "6 4",
        interactive: false,
      }).addTo(map);
    }

    function onDocumentMouseMove(event: MouseEvent) {
      if (!draggingRef.current || !startLatLngRef.current || !rectangleRef.current) return;
      event.preventDefault();
      const latlng = map.mouseEventToLatLng(event);
      rectangleRef.current.setBounds(L.latLngBounds(startLatLngRef.current, latlng));
    }

    function onMapMouseMove(event: L.LeafletMouseEvent) {
      if (!draggingRef.current || !startLatLngRef.current || !rectangleRef.current) return;
      event.originalEvent.preventDefault();
      rectangleRef.current.setBounds(L.latLngBounds(startLatLngRef.current, event.latlng));
    }

    function onMapMouseUp(event: L.LeafletMouseEvent) {
      if (!draggingRef.current) return;
      event.originalEvent.preventDefault();
      const startPoint = startPointRef.current;
      const endPoint = map.latLngToContainerPoint(event.latlng);
      if (startPoint && startPoint.distanceTo(endPoint) < MIN_DRAG_PX) {
        endDrag();
        clearRectangle();
        onSelection(null);
        return;
      }
      finishAt(event.latlng);
    }

    function onDocumentMouseUp(event: MouseEvent) {
      if (!draggingRef.current) return;
      event.preventDefault();
      if (container.contains(event.target as Node)) return;
      const point = map.mouseEventToContainerPoint(event);
      finishAt(map.containerPointToLatLng(point));
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        endDrag();
        clearRectangle();
        onSelection(null);
      }
    }

    function dismissOnMapChange() {
      if (draggingRef.current) return;
      clearRectangle();
      onSelection(null);
    }

    map.on("mousedown", onMapMouseDown);
    map.on("mousemove", onMapMouseMove);
    map.on("mouseup", onMapMouseUp);
    map.on("movestart", dismissOnMapChange);
    map.on("zoomstart", dismissOnMapChange);
    document.addEventListener("mousemove", onDocumentMouseMove);
    document.addEventListener("mouseup", onDocumentMouseUp);
    document.addEventListener("keydown", onKeyDown);

    return () => {
      container.classList.remove("map-region-select-cursor");
      setDraggingUi(false);
      if (boxZoomWasEnabled) map.boxZoom.enable();
      if (doubleClickWasEnabled) map.doubleClickZoom.enable();
      map.off("mousedown", onMapMouseDown);
      map.off("mousemove", onMapMouseMove);
      map.off("mouseup", onMapMouseUp);
      map.off("movestart", dismissOnMapChange);
      map.off("zoomstart", dismissOnMapChange);
      document.removeEventListener("mousemove", onDocumentMouseMove);
      document.removeEventListener("mouseup", onDocumentMouseUp);
      document.removeEventListener("keydown", onKeyDown);
      map.dragging.enable();
      clearRectangle();
    };
  }, [enabled, buildingsGeojson, map, onSelection]);

  return null;
}

export function RegionSelectControl({
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
      const container = L.DomUtil.create("div", "leaflet-region-select-control");
      L.DomEvent.disableClickPropagation(container);
      L.DomEvent.disableScrollPropagation(container);

      const button = L.DomUtil.create("button", "", container);
      button.type = "button";
      button.textContent = "Select area";
      button.title = "Drag a rectangle on the map to summarize building damage in that area";
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
      .querySelector(".leaflet-region-select-control button") as HTMLButtonElement | null;
    if (!button) return;
    button.classList.toggle("active", enabled);
    button.disabled = Boolean(disabled);
  }, [enabled, disabled, map]);

  return null;
}

/** Toggle damage-assessment building polygons on/off (stacked under Select area). */
export function BuildingsLayerControl({
  visible,
  onToggle,
  disabled,
}: {
  visible: boolean;
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
      const container = L.DomUtil.create("div", "leaflet-buildings-layer-control");
      L.DomEvent.disableClickPropagation(container);
      L.DomEvent.disableScrollPropagation(container);

      const button = L.DomUtil.create("button", "", container);
      button.type = "button";
      button.textContent = "Polygons";
      button.title = "Show or hide damage assessment building polygons";
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
      .querySelector(".leaflet-buildings-layer-control button") as HTMLButtonElement | null;
    if (!button) return;
    button.classList.toggle("active", visible);
    button.disabled = Boolean(disabled);
    button.textContent = visible ? "Polygons" : "Polygons off";
    button.title = visible
      ? "Hide damage assessment building polygons"
      : "Show damage assessment building polygons";
  }, [visible, disabled, map]);

  return null;
}
