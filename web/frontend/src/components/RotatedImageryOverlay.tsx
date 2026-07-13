import { useEffect } from "react";
import { useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet-imageoverlay-rotated";

export type ImageryCorners = {
  topLeft: [number, number];
  topRight: [number, number];
  bottomLeft: [number, number];
};

type RotatedImageLayer = L.Layer & {
  addTo(map: L.Map): RotatedImageLayer;
};

type LeafletWithRotated = typeof L & {
  imageOverlay: L.ImageOverlay & {
    rotated: (
      url: string,
      topleft: L.LatLngExpression,
      topright: L.LatLngExpression,
      bottomleft: L.LatLngExpression,
      options?: L.ImageOverlayOptions,
    ) => RotatedImageLayer;
  };
};

export function RotatedImageryOverlay({
  url,
  corners,
}: {
  url: string;
  corners: ImageryCorners;
}) {
  const map = useMap();
  const leaflet = L as LeafletWithRotated;

  useEffect(() => {
    const layer = leaflet.imageOverlay.rotated(
      url,
      L.latLng(corners.topLeft[0], corners.topLeft[1]),
      L.latLng(corners.topRight[0], corners.topRight[1]),
      L.latLng(corners.bottomLeft[0], corners.bottomLeft[1]),
      { opacity: 1, zIndex: 0, interactive: false },
    );
    layer.addTo(map);
    return () => {
      map.removeLayer(layer);
    };
  }, [map, url, corners]);

  return null;
}
