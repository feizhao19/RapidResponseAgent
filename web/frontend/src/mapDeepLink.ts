import type { MapFocus } from "./mapFocus";

/** Parsed chat deep-link for focusing a hospital or critical facility on the map. */
export type FacilityMapDeepLink = {
  kind: "hospital" | "fire_station" | "police" | "shelter" | "facility";
  name: string;
  hospitalKey: string;
  coordinates_wgs84: [number, number];
  distance_mi?: string;
};

/** @deprecated Use FacilityMapDeepLink */
export type HospitalMapDeepLink = FacilityMapDeepLink;

/**
 * Chat map links use `#map-hospital?…` or `#map-facility?…` so react-markdown
 * keeps them (unlike custom schemes). Handled as in-app buttons, not navigation.
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

/** @deprecated Use parseFacilityMapDeepLink */
export const parseHospitalMapDeepLink = parseFacilityMapDeepLink;

export function toMapFocus(link: FacilityMapDeepLink, key: number): MapFocus {
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
