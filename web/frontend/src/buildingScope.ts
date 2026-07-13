import type { AoiDetail, VlmArbitrationResult, VlmJudgment } from "./api/client";
import { featureCentroidWgs84 } from "./regionStats";

export type BuildingScope = "official" | "fused" | "vlm";

type CountRow = { count?: number; pct?: number };

export type BuildingScopeStats = {
  buildings?: {
    total?: number;
    official?: number;
    detected_orphan_damage?: number;
    vipde_assigned?: number;
    inferred_no_damage?: number;
  };
  damage_summary?: {
    damaged_count?: number;
    damaged_pct?: number;
    severe_count?: number;
    severe_pct?: number;
    destroyed_count?: number;
    destroyed_pct?: number;
  };
  by_damage_label?: Record<string, CountRow>;
  by_effective_level?: Record<string, CountRow>;
  area_weighted?: {
    total_area_sqft?: number;
    by_effective_level?: Record<string, { area_sqft?: number; pct?: number }>;
  };
  top_severe_buildings?: Array<{
    bld_id?: string;
    damage_label?: string;
    severe_ratio?: number;
    area_sqft?: number;
    assignment_status?: string;
    centroid_wgs84?: [number, number] | null;
  }>;
  limitations?: string[];
};

type ScopedStatsRoot = {
  building_scope_default?: BuildingScope;
  scopes?: Partial<Record<BuildingScope, BuildingScopeStats>>;
  buildings?: BuildingScopeStats["buildings"];
  damage_summary?: BuildingScopeStats["damage_summary"];
  area_weighted?: BuildingScopeStats["area_weighted"];
  top_severe_buildings?: BuildingScopeStats["top_severe_buildings"];
  limitations?: string[];
};

const DAMAGED_LABELS = new Set(["minor", "major", "destroyed"]);
const SEVERE_LABELS = new Set(["major", "destroyed"]);
const M2_TO_SQFT = 10.7639;

export function fusedDetectedCount(detail: AoiDetail | null | undefined): number {
  const stats = detail?.stats as ScopedStatsRoot | undefined;
  if (!stats) return 0;
  const fused = stats.scopes?.fused?.buildings?.detected_orphan_damage;
  if (fused != null) return fused;
  const buildings = stats.buildings;
  if (!buildings) return 0;
  const total = buildings.total ?? 0;
  const official = buildings.official ?? total;
  return Math.max(0, total - official);
}

export function resolveDetectedExtraCount(
  detail: AoiDetail | null | undefined,
  indexDetected?: number,
): number {
  const fromDetail = fusedDetectedCount(detail);
  if (fromDetail > 0) return fromDetail;
  if (indexDetected != null && indexDetected > 0) return indexDetected;
  return 0;
}

export function hasFusedBuildingView(
  detail: AoiDetail | null | undefined,
  indexDetected?: number,
): boolean {
  return resolveDetectedExtraCount(detail, indexDetected) > 0;
}

export function hasVlmReviewedView(detail: AoiDetail | null | undefined): boolean {
  const discrepancy = detail?.vlm_arbitration?.results?.length ?? 0;
  const damage = detail?.vlm_damage_review?.results?.length ?? 0;
  return discrepancy + damage > 0;
}

function recommendationOf(row: VlmArbitrationResult): string | null {
  const rec = row.vlm?.recommendation ?? row.ensemble?.winning_recommendation;
  return rec ? String(rec) : null;
}

function judgmentOf(row: VlmArbitrationResult): VlmJudgment | undefined {
  return row.vlm;
}

/** Apply VLM footprint + damage decisions on top of the fused inventory. */
export function applyVlmReviewedBuildings(
  geojson: GeoJSON.FeatureCollection,
  detail: AoiDetail | null | undefined,
): GeoJSON.FeatureCollection {
  const presenceById = new Map<string, VlmArbitrationResult>();
  for (const row of detail?.vlm_arbitration?.results ?? []) {
    if (recommendationOf(row)) presenceById.set(row.feature_id, row);
  }

  const damageById = new Map<string, VlmArbitrationResult>();
  for (const row of detail?.vlm_damage_review?.results ?? []) {
    if (recommendationOf(row)) damageById.set(row.feature_id, row);
  }

  const features: GeoJSON.Feature[] = [];
  for (const feature of geojson.features) {
    const props = { ...(feature.properties ?? {}) };
    const bldId = String(props.BLD_ID ?? "");
    const origin = String(props.building_origin ?? "lariac");
    const presenceRow = bldId ? presenceById.get(bldId) : undefined;
    const presenceRec = presenceRow ? recommendationOf(presenceRow) : null;

    // Drop ViPDE extras that VLM rejected as non-buildings.
    if (origin === "detected" && presenceRec === "reject_as_building") {
      continue;
    }

    if (presenceRow && presenceRec) {
      props.vlm_presence_recommendation = presenceRec;
      const present = judgmentOf(presenceRow)?.building_present;
      if (present !== undefined) props.vlm_building_present = present;
    }

    const damageRow = bldId ? damageById.get(bldId) : undefined;
    const damageRec = damageRow ? recommendationOf(damageRow) : null;
    if (damageRow && damageRec) {
      props.vlm_damage_recommendation = damageRec;
      props.pipeline_damage_label = props.damage_label;
      if (damageRec === "not_damaged") {
        props.damage_label = "no_damage";
        props.damage_level = 1;
      } else if (damageRec === "damaged") {
        if (!DAMAGED_LABELS.has(String(props.damage_label ?? ""))) {
          props.damage_label = "destroyed";
          props.damage_level = 4;
        }
      } else if (damageRec === "needs_field_check") {
        props.vlm_needs_field_check = true;
      }
    }

    features.push({ ...feature, properties: props });
  }

  return { type: "FeatureCollection", features };
}

function featureAreaSqft(props: Record<string, unknown>): number {
  const direct = Number(props.area_sqft);
  if (Number.isFinite(direct) && direct > 0) return direct;
  const shape = Number(props.Shape_Area ?? props.AREA ?? 0);
  if (!Number.isFinite(shape) || shape <= 0) return 0;
  // Shape_Area in this project is typically square meters.
  return shape * M2_TO_SQFT;
}

export function computeBuildingScopeStatsFromGeojson(
  geojson: GeoJSON.FeatureCollection,
): BuildingScopeStats {
  let total = 0;
  let official = 0;
  let detected = 0;
  let damaged = 0;
  let severe = 0;
  let destroyed = 0;
  const byLabel: Record<string, number> = {};

  const severeRows: NonNullable<BuildingScopeStats["top_severe_buildings"]> = [];

  for (const feature of geojson.features) {
    const props = (feature.properties ?? {}) as Record<string, unknown>;
    total += 1;
    const origin = String(props.building_origin ?? "lariac");
    if (origin === "detected") detected += 1;
    else official += 1;

    const label = String(props.damage_label ?? "unknown");
    byLabel[label] = (byLabel[label] ?? 0) + 1;
    if (DAMAGED_LABELS.has(label)) damaged += 1;
    if (SEVERE_LABELS.has(label)) {
      severe += 1;
      severeRows.push({
        bld_id: props.BLD_ID != null ? String(props.BLD_ID) : undefined,
        damage_label: label,
        severe_ratio: Number(props.severe_ratio ?? 0) || undefined,
        area_sqft: featureAreaSqft(props) || undefined,
        assignment_status:
          props.assignment_status != null ? String(props.assignment_status) : undefined,
        centroid_wgs84: featureCentroidWgs84(feature),
      });
    }
    if (label === "destroyed") destroyed += 1;
  }

  const pct = (count: number) => (total > 0 ? Math.round((count / total) * 1000) / 10 : 0);

  severeRows.sort((a, b) => {
    const rank = (label?: string) => (label === "destroyed" ? 0 : label === "major" ? 1 : 2);
    const byRank = rank(a.damage_label) - rank(b.damage_label);
    if (byRank !== 0) return byRank;
    return (b.severe_ratio ?? 0) - (a.severe_ratio ?? 0);
  });

  return {
    buildings: {
      total,
      official,
      detected_orphan_damage: detected,
    },
    damage_summary: {
      damaged_count: damaged,
      damaged_pct: pct(damaged),
      severe_count: severe,
      severe_pct: pct(severe),
      destroyed_count: destroyed,
      destroyed_pct: pct(destroyed),
    },
    by_damage_label: Object.fromEntries(
      Object.entries(byLabel).map(([label, count]) => [label, { count, pct: pct(count) }]),
    ),
    top_severe_buildings: severeRows.slice(0, 20),
    limitations: [
      "VLM reviewed view applies footprint accept/reject and destroyed verification on top of the fused inventory.",
    ],
  };
}

export function resolveBuildingScopeStats(
  detail: AoiDetail | null | undefined,
  scope: BuildingScope,
  buildingsGeojson?: GeoJSON.FeatureCollection | null,
): BuildingScopeStats | null {
  const stats = detail?.stats as ScopedStatsRoot | undefined;

  if (scope === "vlm") {
    if (!buildingsGeojson || !detail) return null;
    const reviewed = applyVlmReviewedBuildings(buildingsGeojson, detail);
    return computeBuildingScopeStatsFromGeojson(reviewed);
  }

  if (!stats) return null;

  const scoped = stats.scopes?.[scope];
  if (scoped) return scoped;

  if (scope === "official") {
    return {
      buildings: stats.buildings,
      damage_summary: stats.damage_summary,
      area_weighted: stats.area_weighted,
      top_severe_buildings: stats.top_severe_buildings,
      limitations: stats.limitations,
    };
  }

  return null;
}

export function filterBuildingsGeojson(
  geojson: GeoJSON.FeatureCollection | null | undefined,
  scope: BuildingScope,
  detail?: AoiDetail | null,
): GeoJSON.FeatureCollection | null {
  if (!geojson) return null;
  if (scope === "vlm") {
    return applyVlmReviewedBuildings(geojson, detail ?? null);
  }
  if (scope === "fused") return geojson;

  const features = geojson.features.filter((feature) => {
    const origin = String(feature.properties?.building_origin ?? "lariac");
    return origin !== "detected";
  });

  return { type: "FeatureCollection", features };
}

export const BUILDING_SCOPE_LABELS: Record<BuildingScope, string> = {
  official: "Official footprints",
  fused: "Official + detected extra",
  vlm: "VLM reviewed",
};

export const BUILDING_SCOPE_STATS_CAPTION: Record<BuildingScope, string> = {
  official: "LARIAC footprints",
  fused: "LARIAC + ViPDE extras (reference)",
  vlm: "Final inventory after VLM footprint + damage review",
};

export const BUILDING_SCOPE_HINTS: Record<BuildingScope, string> = {
  official: "LARIAC6 building polygons only (primary assessment view).",
  fused: "Official footprints plus extra ViPDE-detected structures outside the inventory (reference).",
  vlm: "Final result: fused inventory with VLM accept/reject for extras and destroyed verification.",
};
