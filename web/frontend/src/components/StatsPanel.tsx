import type { AoiDetail } from "../api/client";
import {
  BUILDING_SCOPE_STATS_CAPTION,
  resolveBuildingScopeStats,
  type BuildingScope,
} from "../buildingScope";

type DamageSummary = {
  damaged_count?: number;
  damaged_pct?: number;
  severe_count?: number;
  severe_pct?: number;
  destroyed_count?: number;
  destroyed_pct?: number;
};

type Props = {
  detail: AoiDetail | null;
  buildingScope: BuildingScope;
  buildingsGeojson?: GeoJSON.FeatureCollection | null;
};

function fmtCountPct(count?: number, pct?: number): string {
  if (count == null) return "—";
  if (pct == null) return String(count);
  return `${count} (${pct}%)`;
}

export function StatsPanel({ detail, buildingScope, buildingsGeojson }: Props) {
  if (!detail) return <p>Loading AOI statistics…</p>;

  const scopeStats = resolveBuildingScopeStats(detail, buildingScope, buildingsGeojson);
  const summary = detail.summary ?? {};
  const damage = scopeStats?.damage_summary ?? (summary as DamageSummary);
  const buildings = scopeStats?.buildings;
  const loc = detail.location as { display_name?: string; city?: string; county?: string } | undefined;

  const totalHint =
    buildingScope === "official"
      ? "LARIAC6 official footprints in this AOI"
      : buildingScope === "vlm"
        ? `${buildings?.official ?? "—"} kept official + ${buildings?.detected_orphan_damage ?? "—"} VLM-accepted extras`
        : `${buildings?.official ?? "—"} official + ${buildings?.detected_orphan_damage ?? "—"} detected extra`;

  const cards = [
    {
      label: "Buildings total",
      value: String(buildings?.total ?? summary.buildings_total ?? "—"),
      hint: totalHint,
    },
    {
      label: "Damaged",
      value: fmtCountPct(damage.damaged_count, damage.damaged_pct),
      hint: "Minor + major + destroyed",
    },
    {
      label: "Severe",
      value: fmtCountPct(damage.severe_count, damage.severe_pct),
      hint: "Major + destroyed",
    },
    {
      label: "Destroyed",
      value: fmtCountPct(damage.destroyed_count, damage.destroyed_pct),
      hint: "Highest damage level only (subset of damaged)",
    },
  ];

  return (
    <div className="stats-panel">
      <p className="stats-context">
        {loc?.display_name ?? detail.aoi_id} · {detail.event}
        {detail.fusion_mode && <> · fusion: {detail.fusion_mode}</>}
      </p>
      <p className="stats-note">{BUILDING_SCOPE_STATS_CAPTION[buildingScope]}</p>
      <div className="stats-grid">
        {cards.map((card) => (
          <div className="stat-card" key={card.label}>
            <div className="label">{card.label}</div>
            <div className="value">{card.value}</div>
            <div className="hint">{card.hint}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
