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

  const postImage = normalize(record.post_image);
  const postMatch = postImage.match(/(20\d{2})(\d{2})(\d{2})/);
  if (postMatch) {
    return `${postMatch[1]}-${postMatch[2]}-${postMatch[3]}`;
  }

  return "unknown-date";
}

export function formatAssessedCaseLabel(record: AoiRecord): string {
  if (record.case_label) return record.case_label;

  const location = record.location ?? {};
  const community = extractCommunity(record);
  const city = normalize(location.city) || community;
  const state = normalize(location.state) || "Unknown state";
  const caseDate = extractCaseDate(record);

  if (community.toLowerCase() === city.toLowerCase()) {
    return `${city} · ${state} · ${caseDate}`;
  }
  return `${community} · ${city} · ${state} · ${caseDate}`;
}
