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
