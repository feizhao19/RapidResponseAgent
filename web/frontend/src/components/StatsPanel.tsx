import type { AoiDetail } from "../api/client";
import {
  BUILDING_SCOPE_STATS_CAPTION,
  resolveBuildingScopeStats,
  type BuildingScope,
} from "../buildingScope";

type LevelRow = { count?: number; pct?: number };

type Props = {
  detail: AoiDetail | null;
  buildingScope: BuildingScope;
  buildingsGeojson?: GeoJSON.FeatureCollection | null;
};

const LEVEL_CARDS: Array<{ key: string; label: string; hint: string }> = [
  { key: "no_damage", label: "No damage", hint: "Includes inferred no-damage when applicable" },
  { key: "minor", label: "Minor damage", hint: "ViPDE / effective level 2" },
  { key: "major", label: "Major damage", hint: "ViPDE / effective level 3" },
  { key: "destroyed", label: "Destroyed", hint: "ViPDE / effective level 4" },
];

function fmtCountPct(count?: number, pct?: number): string {
  if (count == null) return "—";
  if (pct == null) return String(count);
  return `${count} (${pct}%)`;
}

export function StatsPanel({ detail, buildingScope, buildingsGeojson }: Props) {
  if (!detail) return <p>Loading AOI statistics…</p>;

  const scopeStats = resolveBuildingScopeStats(detail, buildingScope, buildingsGeojson);
  const summary = detail.summary ?? {};
  const buildings = scopeStats?.buildings;
  const levels = (scopeStats?.by_effective_level ?? {}) as Record<string, LevelRow>;
  const loc = detail.location as { display_name?: string; city?: string; county?: string } | undefined;

  const totalHint =
    buildingScope === "official"
      ? "Official footprints in this AOI"
      : buildingScope === "vlm"
        ? `${buildings?.official ?? "—"} kept official + ${buildings?.detected_orphan_damage ?? "—"} VLM-accepted extras`
        : `${buildings?.official ?? "—"} official + ${buildings?.detected_orphan_damage ?? "—"} detected extra`;

  const cards = [
    {
      label: "Buildings total",
      value: String(buildings?.total ?? summary.buildings_total ?? "—"),
      hint: totalHint,
    },
    ...LEVEL_CARDS.map((card) => {
      const row = levels[card.key] ?? {};
      return {
        label: card.label,
        value: fmtCountPct(row.count, row.pct),
        hint: card.hint,
      };
    }),
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
