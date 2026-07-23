import type { AoiRecord } from "./api/client";

const EVENT_DATES: Record<string, string> = {
  la_wildfires_jan2025: "2025-01-07",
};

const EVENT_MONTHS: Record<string, string> = {
  jan: "01",
  feb: "02",
  mar: "03",
  apr: "04",
  may: "05",
  jun: "06",
  jul: "07",
  aug: "08",
  sep: "09",
  oct: "10",
  nov: "11",
  dec: "12",
};

function normalize(text: string | undefined): string {
  return (text ?? "").trim();
}

function isSkippableLocationPart(part: string): boolean {
  const stripped = part.trim();
  if (!stripped) return true;
  const lowered = stripped.toLowerCase();
  if (lowered === "california" || lowered === "united states" || lowered === "usa") return true;
  if (lowered.endsWith(" county")) return true;
  if (/^\d{5}(?:-\d{4})?$/.test(stripped)) return true;
  return false;
}

function shortAoiSuffix(aoiId: string | undefined, length = 4): string {
  let text = normalize(aoiId);
  if (!text) return "";
  if (text.includes("_")) text = text.slice(text.lastIndexOf("_") + 1);
  text = text.replace(/[^A-Za-z0-9]/g, "");
  if (text.length <= length) return text;
  return text.slice(-length);
}

function extractCommunity(record: AoiRecord): string {
  const location = record.location ?? {};
  const neighbourhood = normalize(
    (location as { neighbourhood?: string; neighborhood?: string }).neighbourhood ??
      (location as { neighborhood?: string }).neighborhood,
  );
  if (neighbourhood) return neighbourhood;

  const city = normalize(location.city);
  const county = normalize(location.county);
  const displayName = normalize(location.display_name);
  if (displayName) {
    const cityNorm = city.toLowerCase();
    const countyNorm = county.toLowerCase();
    for (const part of displayName.split(",").map((piece) => piece.trim()).filter(Boolean)) {
      const partNorm = part.toLowerCase();
      if (cityNorm && partNorm === cityNorm) continue;
      if (countyNorm && partNorm === countyNorm) continue;
      if (isSkippableLocationPart(part)) continue;
      return part;
    }
  }

  return city || record.aoi_id || "Unknown area";
}

function extractCaseDate(record: AoiRecord): string {
  const event = normalize(record.event);
  if (event) {
    const known = EVENT_DATES[event];
    if (known) return known;

    const eventLower = event.toLowerCase();
    const yearMatch = eventLower.match(/(20\d{2})/);
    if (yearMatch) {
      const year = yearMatch[1];
      for (const [token, month] of Object.entries(EVENT_MONTHS)) {
        if (eventLower.includes(token)) return `${year}-${month}-01`;
      }
      return `${year}-01-01`;
    }
  }

  const location = record.location ?? {};
  const metaCandidates = [
    (record as { imagery_date?: string }).imagery_date,
    (record as { acquired_at?: string }).acquired_at,
    (location as { imagery_date?: string }).imagery_date,
    (location as { acquired_at?: string }).acquired_at,
  ];
  for (const raw of metaCandidates) {
    const text = normalize(raw);
    const iso = text.match(/(20\d{2})-(\d{2})-(\d{2})/);
    if (iso) return `${iso[1]}-${iso[2]}-${iso[3]}`;
    const compact = text.match(/(20\d{2})(\d{2})(\d{2})/);
    if (compact) return `${compact[1]}-${compact[2]}-${compact[3]}`;
  }

  const generated = normalize((record as { generated_at?: string }).generated_at);
  const generatedMatch = generated.match(/(20\d{2})-(\d{2})-(\d{2})/);
  if (generatedMatch) {
    return `${generatedMatch[1]}-${generatedMatch[2]}-${generatedMatch[3]}`;
  }

  return "unknown-date";
}

function formatBaseLabel(record: AoiRecord, disambiguator?: string): string {
  const location = record.location ?? {};
  const community = extractCommunity(record);
  const city = normalize(location.city) || community;
  const state = normalize(location.state) || "Unknown state";
  const caseDate = extractCaseDate(record);
  const parts =
    community.toLowerCase() === city.toLowerCase()
      ? [city, state, caseDate]
      : [community, city, state, caseDate];
  if (disambiguator) parts.push(`···${disambiguator}`);
  return parts.join(" · ");
}

/** Prefer API `case_label` (already disambiguated). Fallback mirrors backend rules. */
export function formatAssessedCaseLabel(record: AoiRecord): string {
  if (record.case_label) return record.case_label;
  return formatBaseLabel(record);
}

/** Client-side disambiguation when API labels are missing. */
export function formatAssessedCaseLabels(records: AoiRecord[]): Map<string, string> {
  const base = new Map<string, string>();
  const counts = new Map<string, number>();
  for (const record of records) {
    const label = record.case_label || formatBaseLabel(record);
    base.set(record.aoi_id, label);
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  const out = new Map<string, string>();
  for (const record of records) {
    const label = base.get(record.aoi_id) || record.aoi_id;
    if ((counts.get(label) ?? 0) > 1 && !record.case_label) {
      out.set(record.aoi_id, formatBaseLabel(record, shortAoiSuffix(record.aoi_id)));
    } else {
      out.set(record.aoi_id, label);
    }
  }
  return out;
}
