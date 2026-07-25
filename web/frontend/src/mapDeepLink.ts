import type { MapFocus, PriorityGridCell } from "./mapFocus";

/** Parsed chat deep-link for focusing a hospital or critical facility on the map. */
export type FacilityMapDeepLink = {
  kind: "hospital" | "fire_station" | "police" | "shelter" | "facility";
  name: string;
  hospitalKey: string;
  coordinates_wgs84: [number, number];
  distance_mi?: string;
};

/** Parsed chat deep-link for focusing a road closure / CHP incident on the map. */
export type RoadMapDeepLink = {
  kind: "road";
  name: string;
  roadId: string;
  roadKind?: string;
  severity?: string;
  coordinates_wgs84: [number, number];
};

/** Parsed chat deep-link for highlighting a Mission Priority 3×3 cell. */
export type RegionMapDeepLink = {
  kind: "region";
  name: string;
  bounds_wgs84: [number, number, number, number];
  priority?: number;
  direction?: string;
  aoiBounds?: [number, number, number, number];
  cells?: PriorityGridCell[];
};

/** @deprecated Use FacilityMapDeepLink */
export type HospitalMapDeepLink = FacilityMapDeepLink;

export type ChatMapDeepLink = FacilityMapDeepLink | RoadMapDeepLink | RegionMapDeepLink;

function decodePriorityGrid(encoded: string | null): {
  aoiBounds?: [number, number, number, number];
  cells: PriorityGridCell[];
} {
  if (!encoded) return { cells: [] };
  try {
    const padded = encoded + "=".repeat((4 - (encoded.length % 4)) % 4);
    const json = atob(padded.replace(/-/g, "+").replace(/_/g, "/"));
    const parsed = JSON.parse(json) as {
      aoi?: number[];
      cells?: Array<{
        d?: string;
        b?: number[];
        i?: number;
        x?: number;
        j?: number;
        n?: number;
        p?: number;
      }>;
    };
    const cells: PriorityGridCell[] = [];
    for (const cell of parsed.cells || []) {
      const b = cell.b;
      if (!b || b.length !== 4) continue;
      const [west, south, east, north] = b.map(Number);
      if (![west, south, east, north].every(Number.isFinite) || !(east > west && north > south)) {
        continue;
      }
      cells.push({
        direction: String(cell.d || ""),
        bounds_wgs84: [west, south, east, north],
        impact_score: Number(cell.i) || 0,
        destroyed: Number(cell.x) || 0,
        major: Number(cell.j) || 0,
        minor: Number(cell.n) || 0,
        priority: cell.p != null && Number.isFinite(Number(cell.p)) ? Number(cell.p) : undefined,
      });
    }
    let aoiBounds: [number, number, number, number] | undefined;
    if (parsed.aoi && parsed.aoi.length === 4) {
      const [west, south, east, north] = parsed.aoi.map(Number);
      if ([west, south, east, north].every(Number.isFinite) && east > west && north > south) {
        aoiBounds = [west, south, east, north];
      }
    }
    return { aoiBounds, cells };
  } catch {
    return { cells: [] };
  }
}

/**
 * Chat map links use `#map-hospital?…`, `#map-facility?…`, `#map-road?…`,
 * or `#map-region?…` so react-markdown keeps them (unlike custom schemes).
 * Handled as in-app buttons, not navigation.
 */
export function parseFacilityMapDeepLink(href: string | undefined | null): FacilityMapDeepLink | null {
  if (!href) return null;
  let url: URL;
  try {
    url = new URL(href, "http://local.invalid");
  } catch {
    return null;
  }
  const hash = url.hash || (href.startsWith("#") ? href : "");
  const isHospital = hash.startsWith("#map-hospital");
  const isFacility = hash.startsWith("#map-facility");
  if (!isHospital && !isFacility) return null;
  const query = hash.includes("?") ? hash.slice(hash.indexOf("?") + 1) : "";
  const params = new URLSearchParams(query);
  const lon = Number(params.get("lon"));
  const lat = Number(params.get("lat"));
  const name = (params.get("name") || "").trim();
  if (!Number.isFinite(lon) || !Number.isFinite(lat) || !name) return null;
  const distanceMi = params.get("distance_mi") ?? "";
  const rawKind = (params.get("kind") || (isHospital ? "hospital" : "facility")).trim();
  const kind = (
    ["hospital", "fire_station", "police", "shelter", "facility"].includes(rawKind)
      ? rawKind
      : "facility"
  ) as FacilityMapDeepLink["kind"];
  return {
    kind,
    name,
    hospitalKey: `${name}-${distanceMi}`,
    coordinates_wgs84: [lon, lat],
    distance_mi: distanceMi || undefined,
  };
}

export function parseRoadMapDeepLink(href: string | undefined | null): RoadMapDeepLink | null {
  if (!href) return null;
  let url: URL;
  try {
    url = new URL(href, "http://local.invalid");
  } catch {
    return null;
  }
  const hash = url.hash || (href.startsWith("#") ? href : "");
  if (!hash.startsWith("#map-road")) return null;
  const query = hash.includes("?") ? hash.slice(hash.indexOf("?") + 1) : "";
  const params = new URLSearchParams(query);
  const lon = Number(params.get("lon"));
  const lat = Number(params.get("lat"));
  const name = (params.get("name") || "").trim();
  if (!Number.isFinite(lon) || !Number.isFinite(lat) || !name) return null;
  return {
    kind: "road",
    name,
    roadId: (params.get("id") || `${name}-${lon.toFixed(5)}-${lat.toFixed(5)}`).trim(),
    roadKind: (params.get("kind") || "").trim() || undefined,
    severity: (params.get("severity") || "").trim() || undefined,
    coordinates_wgs84: [lon, lat],
  };
}

export function parseRegionMapDeepLink(href: string | undefined | null): RegionMapDeepLink | null {
  if (!href) return null;
  let url: URL;
  try {
    url = new URL(href, "http://local.invalid");
  } catch {
    return null;
  }
  const hash = url.hash || (href.startsWith("#") ? href : "");
  if (!hash.startsWith("#map-region")) return null;
  const query = hash.includes("?") ? hash.slice(hash.indexOf("?") + 1) : "";
  const params = new URLSearchParams(query);
  const west = Number(params.get("west"));
  const south = Number(params.get("south"));
  const east = Number(params.get("east"));
  const north = Number(params.get("north"));
  const name = (params.get("name") || "").trim();
  if (
    ![west, south, east, north].every(Number.isFinite) ||
    !(east > west && north > south) ||
    !name
  ) {
    return null;
  }
  const priorityRaw = params.get("priority");
  const priority = priorityRaw ? Number(priorityRaw) : undefined;
  const { aoiBounds, cells } = decodePriorityGrid(params.get("g"));
  return {
    kind: "region",
    name,
    bounds_wgs84: [west, south, east, north],
    priority: Number.isFinite(priority) ? priority : undefined,
    direction: (params.get("direction") || "").trim() || undefined,
    aoiBounds,
    cells: cells.length ? cells : undefined,
  };
}

export function parseChatMapDeepLink(href: string | undefined | null): ChatMapDeepLink | null {
  return (
    parseRegionMapDeepLink(href) ??
    parseRoadMapDeepLink(href) ??
    parseFacilityMapDeepLink(href)
  );
}

/** @deprecated Use parseFacilityMapDeepLink */
export const parseHospitalMapDeepLink = parseFacilityMapDeepLink;

export function toMapFocus(link: ChatMapDeepLink, key: number): MapFocus {
  if (link.kind === "road") {
    return {
      kind: "road",
      key,
      roadId: link.roadId,
      name: link.name,
      coordinates_wgs84: link.coordinates_wgs84,
      roadKind: link.roadKind,
      severity: link.severity,
    };
  }
  if (link.kind === "region") {
    return {
      kind: "region",
      key,
      name: link.name,
      bounds_wgs84: link.bounds_wgs84,
      priority: link.priority,
      direction: link.direction,
      aoiBounds: link.aoiBounds,
      cells: link.cells,
    };
  }
  return {
    kind: "hospital",
    key,
    hospitalKey: link.hospitalKey,
    name: link.name,
    coordinates_wgs84: link.coordinates_wgs84,
    facilityKind: link.kind === "hospital" ? "hospital" : link.kind,
    distance_mi: link.distance_mi,
  };
}
