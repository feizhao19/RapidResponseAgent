export const DAMAGE_LABEL_ORDER = [
  "no_damage",
  "no_damage_inferred",
  "minor",
  "major",
  "destroyed",
  "unknown",
] as const;

export const DAMAGE_LABEL_DISPLAY: Record<string, string> = {
  no_damage: "No damage",
  no_damage_inferred: "Inferred OK",
  minor: "Minor",
  major: "Major",
  destroyed: "Destroyed",
  unknown: "Unknown",
};

export type RegionDamageStats = {
  total: number;
  byLabel: Record<string, number>;
};

type LngLat = [number, number];

function collectCoordinates(geometry: GeoJSON.Geometry, out: LngLat[]): void {
  switch (geometry.type) {
    case "Point":
      out.push(geometry.coordinates as LngLat);
      break;
    case "MultiPoint":
    case "LineString":
      for (const coord of geometry.coordinates) {
        out.push(coord as LngLat);
      }
      break;
    case "MultiLineString":
    case "Polygon":
      for (const ring of geometry.coordinates) {
        for (const coord of ring) {
          out.push(coord as LngLat);
        }
      }
      break;
    case "MultiPolygon":
      for (const polygon of geometry.coordinates) {
        for (const ring of polygon) {
          for (const coord of ring) {
            out.push(coord as LngLat);
          }
        }
      }
      break;
    case "GeometryCollection":
      for (const geom of geometry.geometries) {
        collectCoordinates(geom, out);
      }
      break;
    default:
      break;
  }
}

/** Approximate WGS84 centroid [lon, lat] from a GeoJSON feature geometry. */
export function featureCentroidWgs84(
  feature: GeoJSON.Feature | null | undefined,
): [number, number] | null {
  if (!feature?.geometry) return null;
  const coords: LngLat[] = [];
  collectCoordinates(feature.geometry, coords);
  if (!coords.length) return null;
  let sumLon = 0;
  let sumLat = 0;
  for (const [lon, lat] of coords) {
    sumLon += lon;
    sumLat += lat;
  }
  return [sumLon / coords.length, sumLat / coords.length];
}

export function findBuildingFeatureById(
  geojson: GeoJSON.FeatureCollection | null | undefined,
  bldId: string,
): GeoJSON.Feature | null {
  if (!geojson || !bldId) return null;
  for (const feature of geojson.features) {
    const props = feature.properties ?? {};
    const id = String(props.BLD_ID ?? "");
    if (id && id === bldId) return feature;
  }
  return null;
}

function pointInBounds(
  lon: number,
  lat: number,
  west: number,
  south: number,
  east: number,
  north: number,
): boolean {
  return lon >= west && lon <= east && lat >= south && lat <= north;
}

export function featureIntersectsBounds(
  feature: GeoJSON.Feature,
  west: number,
  south: number,
  east: number,
  north: number,
): boolean {
  if (!feature.geometry) return false;
  const coords: LngLat[] = [];
  collectCoordinates(feature.geometry, coords);
  if (!coords.length) return false;
  return coords.some(([lon, lat]) => pointInBounds(lon, lat, west, south, east, north));
}

export function computeRegionStats(
  geojson: GeoJSON.FeatureCollection,
  west: number,
  south: number,
  east: number,
  north: number,
): RegionDamageStats {
  const byLabel: Record<string, number> = {};
  let total = 0;

  for (const feature of geojson.features) {
    if (!featureIntersectsBounds(feature, west, south, east, north)) continue;
    total += 1;
    const label = String(feature.properties?.damage_label ?? "unknown");
    byLabel[label] = (byLabel[label] ?? 0) + 1;
  }

  return { total, byLabel };
}

export function pct(count: number, total: number): string {
  if (total <= 0) return "0%";
  return `${((count / total) * 100).toFixed(1)}%`;
}
