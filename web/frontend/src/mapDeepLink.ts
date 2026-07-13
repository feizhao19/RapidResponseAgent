import type { MapFocus } from "./mapFocus";

/** Parsed chat deep-link for focusing a hospital on the map. */
export type HospitalMapDeepLink = {
  kind: "hospital";
  name: string;
  hospitalKey: string;
  coordinates_wgs84: [number, number];
};

/**
 * Chat hospital links use `#map-hospital?lon=&lat=&name=&distance_mi=` so
 * react-markdown keeps them (unlike custom schemes).
 */
export function parseHospitalMapDeepLink(href: string | undefined | null): HospitalMapDeepLink | null {
  if (!href) return null;
  let url: URL;
  try {
    url = new URL(href, "http://local.invalid");
  } catch {
    return null;
  }
  const hash = url.hash || (href.startsWith("#") ? href : "");
  if (!hash.startsWith("#map-hospital")) return null;
  const query = hash.includes("?") ? hash.slice(hash.indexOf("?") + 1) : "";
  const params = new URLSearchParams(query);
  const lon = Number(params.get("lon"));
  const lat = Number(params.get("lat"));
  const name = (params.get("name") || "").trim();
  if (!Number.isFinite(lon) || !Number.isFinite(lat) || !name) return null;
  const distanceMi = params.get("distance_mi") ?? "";
  return {
    kind: "hospital",
    name,
    hospitalKey: `${name}-${distanceMi}`,
    coordinates_wgs84: [lon, lat],
  };
}

export function toMapFocus(link: HospitalMapDeepLink, key: number): MapFocus {
  return {
    kind: "hospital",
    key,
    hospitalKey: link.hospitalKey,
    name: link.name,
    coordinates_wgs84: link.coordinates_wgs84,
  };
}
