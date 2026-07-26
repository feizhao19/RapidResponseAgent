import type { Hospital } from "./api/client";

export type HospitalsPayload = {
  status?: string;
  lookup_error?: string;
  aoi_centroid_wgs84?: [number, number];
  search_radius_km?: number;
  hospitals?: Hospital[];
  nearest?: Hospital;
};

export type HospitalMapFocus = {
  key: number;
  name: string;
  coordinates_wgs84: [number, number];
};

export function resolveHospitalCoords(hospital: Hospital): [number, number] | null {
  if (hospital.coordinates_wgs84?.[0] != null && hospital.coordinates_wgs84?.[1] != null) {
    return hospital.coordinates_wgs84;
  }
  if (hospital.longitude != null && hospital.latitude != null) {
    return [hospital.longitude, hospital.latitude];
  }
  return null;
}

export function hospitalLocationLabel(hospital: Hospital): string {
  if (hospital.address?.trim()) return hospital.address.trim();
  return "—";
}

export function hospitalRowKey(hospital: Hospital): string {
  return `${hospital.name}-${hospital.distance_mi ?? ""}`;
}

/** OSM placeholder names like "Unnamed hospital" — hide on the map. */
export function isUnnamedFacilityName(name?: string | null): boolean {
  const text = (name || "").trim();
  if (!text) return true;
  return text.toLowerCase().startsWith("unnamed");
}

export function namedFacilitiesOnly(facilities: Hospital[]): Hospital[] {
  return facilities.filter((item) => !isUnnamedFacilityName(item.name));
}

/** Match a chat/map focus to a loaded hospital row (key, then name + nearby coords). */
export function findHospitalForFocus(
  hospitals: Hospital[],
  focus: { hospitalKey: string; name: string; coordinates_wgs84: [number, number] },
): Hospital | undefined {
  const byKey = hospitals.find((h) => hospitalRowKey(h) === focus.hospitalKey);
  if (byKey) return byKey;
  const [flon, flat] = focus.coordinates_wgs84;
  return hospitals.find((h) => {
    if (h.name !== focus.name) return false;
    const coords = resolveHospitalCoords(h);
    if (!coords) return true;
    return Math.abs(coords[0] - flon) < 1e-4 && Math.abs(coords[1] - flat) < 1e-4;
  });
}

/** Prefer non-empty contact fields from the richer of focus vs cached facility. */
export function mergeFacilityDetails(
  base: Hospital,
  extra?: Partial<Hospital> | null,
): Hospital {
  if (!extra) return base;
  const merged: Hospital = { ...base };
  const keys: (keyof Hospital)[] = [
    "kind",
    "phone",
    "email",
    "website",
    "operator",
    "contact_name",
    "emergency",
    "beds",
    "opening_hours",
    "address",
    "osm_type",
    "osm_id",
    "distance_mi",
    "distance_km",
  ];
  for (const key of keys) {
    const value = extra[key];
    if (value != null && value !== "" && (merged[key] == null || merged[key] === "")) {
      (merged as Record<string, unknown>)[key] = value;
    }
  }
  return merged;
}
