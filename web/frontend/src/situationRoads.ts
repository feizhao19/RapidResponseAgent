import type { SituationRoadFeature, SituationRoads } from "./api/client";

export function situationRoadsGeoJson(roads: SituationRoads): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: roads.features.map((feature) => ({
      type: "Feature",
      id: feature.id,
      properties: {
        id: feature.id,
        kind: feature.kind,
        severity: feature.severity,
        status: feature.status,
        title: feature.title,
        description: feature.description ?? "",
        route: feature.route ?? "",
        source: feature.source,
      },
      geometry: feature.geometry,
    })),
  };
}

/** Operational palette — readable on imagery; no purple wash. */
export function roadStrokeColor(
  severity: SituationRoadFeature["severity"],
  kind?: SituationRoadFeature["kind"],
): string {
  if (kind === "incident") {
    return severity === "major" ? "#b45309" : "#57534e";
  }
  if (severity === "closed") return "#e11d48";
  if (severity === "major") return "#ea580c";
  return "#a16207";
}

export function roadCasingColor(kind?: SituationRoadFeature["kind"]): string {
  if (kind === "incident") return "rgba(255,255,255,0.92)";
  return "rgba(15, 23, 42, 0.72)";
}

export function roadStrokeWeight(severity: SituationRoadFeature["severity"]): number {
  if (severity === "closed") return 4;
  if (severity === "major") return 3.5;
  return 3;
}

export function roadCasingWeight(severity: SituationRoadFeature["severity"]): number {
  return roadStrokeWeight(severity) + 3.5;
}

export function roadKindLabel(kind: SituationRoadFeature["kind"] | string): string {
  switch (kind) {
    case "closure":
      return "Full closure";
    case "lane_closure":
      return "Lane closure";
    case "construction":
      return "Construction";
    case "incident":
      return "CHP incident";
    case "restriction":
      return "Restriction";
    default:
      return "Road event";
  }
}

export function roadSummaryCounts(roads: SituationRoads): {
  closures: number;
  lanes: number;
  incidents: number;
  other: number;
} {
  const s = roads.summary;
  return {
    closures: s.closure_count || 0,
    lanes: s.lane_closure_count || 0,
    incidents: s.incident_count || 0,
    other: Math.max(
      0,
      (s.feature_count || 0) -
        (s.closure_count || 0) -
        (s.lane_closure_count || 0) -
        (s.incident_count || 0),
    ),
  };
}

export function roadSummaryLabel(roads: SituationRoads): string {
  const c = roadSummaryCounts(roads);
  const parts: string[] = [];
  if (c.closures) parts.push(`${c.closures} closed`);
  if (c.lanes) parts.push(`${c.lanes} lane`);
  if (c.incidents) parts.push(`${c.incidents} CHP`);
  if (c.other) parts.push(`${c.other} other`);
  if (!parts.length) return "Clear nearby";
  return parts.join(" · ");
}

/** Midpoint for short LineStrings — used as an anchor pin when the segment is tiny. */
export function roadLineAnchor(feature: SituationRoadFeature): [number, number] | null {
  const geom = feature.geometry;
  if (geom.type === "Point") {
    const [lon, lat] = geom.coordinates;
    return [lat, lon];
  }
  if (geom.type === "LineString" && geom.coordinates.length >= 2) {
    const mid = Math.floor((geom.coordinates.length - 1) / 2);
    const [lon, lat] = geom.coordinates[mid];
    return [lat, lon];
  }
  return null;
}
