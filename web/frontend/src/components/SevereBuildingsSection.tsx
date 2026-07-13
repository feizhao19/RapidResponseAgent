import {
  resolveBuildingScopeStats,
  type BuildingScope,
  type BuildingScopeStats,
} from "../buildingScope";
import type { AoiDetail } from "../api/client";

type SevereBuilding = NonNullable<BuildingScopeStats["top_severe_buildings"]>[number];

type Props = {
  detail: AoiDetail | null;
  buildingScope: BuildingScope;
  buildingsGeojson?: GeoJSON.FeatureCollection | null;
  onShowOnMap: (building: SevereBuilding) => void;
};

function cell(value: string | number | null | undefined): string {
  if (value == null || value === "") return "—";
  return String(value);
}

function formatRatio(value: number | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return value.toFixed(2);
}

function formatArea(value: number | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return value.toLocaleString(undefined, { maximumFractionDigits: 0 });
}

export function SevereBuildingsSection({
  detail,
  buildingScope,
  buildingsGeojson,
  onShowOnMap,
}: Props) {
  const scoped = resolveBuildingScopeStats(detail, buildingScope, buildingsGeojson);
  const rows = scoped?.top_severe_buildings ?? [];
  if (!rows.length) return null;

  return (
    <section className="severe-buildings-section">
      <h2>Most Severely Affected Buildings</h2>
      <div className="report-table-wrap">
        <table>
          <thead>
            <tr>
              <th>BLD_ID</th>
              <th>Label</th>
              <th>Severe ratio</th>
              <th>Area (sq ft)</th>
              <th>Map</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const bldId = cell(row.bld_id);
              const coords = row.centroid_wgs84;
              const hasCoords =
                coords?.[0] != null && coords?.[1] != null && bldId !== "—";
              return (
                <tr key={bldId}>
                  <td>{bldId}</td>
                  <td>{cell(row.damage_label)}</td>
                  <td>{formatRatio(row.severe_ratio)}</td>
                  <td>{formatArea(row.area_sqft)}</td>
                  <td className="hospital-map-cell">
                    {hasCoords ? (
                      <button
                        type="button"
                        className="hospital-map-btn"
                        onClick={() => onShowOnMap(row)}
                      >
                        Map
                      </button>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
