/** Helpers for Environmental Situation Layer map visuals. */

import type { SituationCell, SituationHourSample, SituationWeather } from "./api/client";

export type SituationFillMode = "humidity" | "temperature";

export function kmhToMph(kmh: number | null | undefined): number | null {
  if (kmh == null || Number.isNaN(kmh)) return null;
  return Math.round(kmh * 0.621371 * 10) / 10;
}

export function cToF(c: number | null | undefined): number | null {
  if (c == null || Number.isNaN(c)) return null;
  return Math.round((c * 9) / 5 + 32);
}

export function humidityBandLabel(band: SituationHourSample["humidity_band"] | undefined): string {
  switch (band) {
    case "danger":
      return "Danger";
    case "elevated":
      return "Elevated";
    case "moist":
      return "Moist";
    default:
      return "Moderate";
  }
}

export function humidityFill(rh: number | null | undefined): string {
  if (rh == null) return "rgba(148, 163, 184, 0.28)";
  if (rh < 15) return "rgba(220, 38, 38, 0.38)";
  if (rh < 25) return "rgba(234, 88, 12, 0.36)";
  if (rh < 40) return "rgba(202, 138, 4, 0.32)";
  return "rgba(22, 163, 74, 0.30)";
}

/** Blue → yellow → orange → red (matches backend temperature_band). */
export function temperatureFill(tempC: number | null | undefined): string {
  if (tempC == null) return "rgba(148, 163, 184, 0.28)";
  if (tempC < 15) return "rgba(59, 130, 246, 0.40)";
  if (tempC < 24) return "rgba(125, 211, 252, 0.38)";
  if (tempC < 32) return "rgba(250, 204, 21, 0.40)";
  if (tempC < 38) return "rgba(249, 115, 22, 0.42)";
  return "rgba(220, 38, 38, 0.45)";
}

/** Meteorological: direction wind comes FROM; rotate arrow so it points TOWARD travel. */
export function windArrowRotationDeg(fromDeg: number | null | undefined): number {
  if (fromDeg == null || Number.isNaN(fromDeg)) return 0;
  return (fromDeg + 180) % 360;
}

export function formatHourLabel(iso: string | undefined, index: number): string {
  if (!iso) return index === 0 ? "Now" : `+${index}h`;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return index === 0 ? "Now" : `+${index}h`;
  return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

export function situationCellGeoJson(
  weather: SituationWeather,
  hourIndex: number,
): GeoJSON.FeatureCollection {
  const features: GeoJSON.Feature[] = weather.cells.map((cell: SituationCell) => {
    const sample = cell.series[hourIndex] ?? cell.series[0];
    const ring = cell.polygon.map((pair) => {
      const lon = pair[0];
      const lat = pair[1];
      return [lon, lat] as [number, number];
    });
    return {
      type: "Feature",
      properties: {
        id: cell.id,
        relative_humidity_pct: sample?.relative_humidity_pct ?? null,
        humidity_band: sample?.humidity_band ?? "moderate",
        temperature_c: sample?.temperature_c ?? null,
        temperature_band: sample?.temperature_band ?? "mild",
      },
      geometry: {
        type: "Polygon",
        coordinates: [ring],
      },
    };
  });
  return { type: "FeatureCollection", features };
}

/** @deprecated Prefer situationCellGeoJson */
export function humidityGeoJson(
  weather: SituationWeather,
  hourIndex: number,
): GeoJSON.FeatureCollection {
  return situationCellGeoJson(weather, hourIndex);
}

export function windPointsAtHour(
  cells: SituationCell[],
  hourIndex: number,
): Array<{
  id: string;
  lat: number;
  lon: number;
  sample: SituationHourSample;
}> {
  return cells.map((cell) => ({
    id: cell.id,
    lat: cell.lat,
    lon: cell.lon,
    sample: cell.series[hourIndex] ?? cell.series[0] ?? {
      temperature_c: null,
      relative_humidity_pct: null,
      wind_speed_kmh: null,
      wind_gusts_kmh: null,
      wind_direction_deg: null,
    },
  }));
}

export const TIMELINE_TICKS = [
  { hour: 0, label: "Now" },
  { hour: 1, label: "1h" },
  { hour: 3, label: "3h" },
  { hour: 6, label: "6h" },
  { hour: 12, label: "12h" },
  { hour: 24, label: "24h" },
] as const;
