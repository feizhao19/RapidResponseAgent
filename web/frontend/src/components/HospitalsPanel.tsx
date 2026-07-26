import { useState } from "react";
import type { AoiDetail, Hospital } from "../api/client";
import {
  hospitalLocationLabel,
  hospitalRowKey,
  namedFacilitiesOnly,
  resolveHospitalCoords,
} from "../hospitalUtils";

type Props = {
  detail: AoiDetail | null;
  onShowOnMap: (facility: Hospital) => void;
};

const KIND_ORDER = ["hospital", "fire_station", "police", "shelter"] as const;
type FacilityKind = (typeof KIND_ORDER)[number];

const DEFAULT_VISIBLE = 5;

const KIND_META: Record<
  FacilityKind,
  { title: string; blurb: string; empty: string }
> = {
  hospital: {
    title: "Nearest Hospitals",
    blurb:
      "Emergency medical facility context from OpenStreetMap. Distances are straight-line from the AOI imagery centroid. Verify contact details operationally.",
    empty: "No hospitals were found in OpenStreetMap within the configured search radius.",
  },
  fire_station: {
    title: "Nearest Fire Stations",
    blurb:
      "Fire station context from OpenStreetMap. Distances are straight-line from the AOI imagery centroid. Verify contact details operationally.",
    empty: "No fire stations were found in OpenStreetMap within the configured search radius.",
  },
  police: {
    title: "Nearest Police Stations",
    blurb:
      "Police station context from OpenStreetMap. Distances are straight-line from the AOI imagery centroid. Verify contact details operationally.",
    empty: "No police stations were found in OpenStreetMap within the configured search radius.",
  },
  shelter: {
    title: "Nearest Shelters",
    blurb:
      "Shelter context from OpenStreetMap. Distances are straight-line from the AOI imagery centroid. Verify contact details operationally.",
    empty: "No shelters were found in OpenStreetMap within the configured search radius.",
  },
};

function cell(value: string | number | null | undefined): string {
  if (value == null || value === "") return "—";
  return String(value);
}

function facilitiesFromDetail(detail: AoiDetail | null): Hospital[] {
  if (!detail) return [];
  if (detail.facilities && detail.facilities.length > 0) {
    return namedFacilitiesOnly(detail.facilities);
  }
  const hospitals = detail.hospitals?.hospitals ?? [];
  return namedFacilitiesOnly(
    hospitals.map((item) => ({ ...item, kind: item.kind || "hospital" })),
  );
}

function byDistance(items: Hospital[]): Hospital[] {
  return [...items].sort((a, b) => (a.distance_mi ?? 1e9) - (b.distance_mi ?? 1e9));
}

function KindSection({
  kind,
  rows,
  centroid,
  searchRadiusKm,
  onShowOnMap,
}: {
  kind: FacilityKind;
  rows: Hospital[];
  centroid: [number, number] | null;
  searchRadiusKm: number | null;
  onShowOnMap: (facility: Hospital) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const meta = KIND_META[kind];
  const nearest = rows[0];
  const canCollapse = rows.length > DEFAULT_VISIBLE;
  const visibleRows = expanded || !canCollapse ? rows : rows.slice(0, DEFAULT_VISIBLE);
  const hiddenCount = rows.length - DEFAULT_VISIBLE;

  return (
    <article className="report-md hospitals-md">
      <h2>{meta.title}</h2>
      {rows.length === 0 ? (
        <p>
          <em>{meta.empty}</em>
        </p>
      ) : (
        <>
          <p>
            <em>{meta.blurb}</em>
          </p>
          <ul>
            {centroid && (
              <li>
                AOI centroid (WGS84): <code>[{centroid[0]}, {centroid[1]}]</code>
              </li>
            )}
            {searchRadiusKm != null && <li>Search radius: {searchRadiusKm} km</li>}
          </ul>

          <div className="report-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Distance (mi)</th>
                  <th>Location</th>
                  <th>Phone</th>
                  <th>Website</th>
                  <th>Operator</th>
                  <th>Map</th>
                </tr>
              </thead>
              <tbody>
                {visibleRows.map((facility) => {
                  const coords = resolveHospitalCoords(facility);
                  return (
                    <tr key={`${kind}-${hospitalRowKey(facility)}`}>
                      <td>{facility.name}</td>
                      <td>{cell(facility.distance_mi)}</td>
                      <td>{hospitalLocationLabel(facility)}</td>
                      <td>{cell(facility.phone)}</td>
                      <td>
                        {facility.website ? (
                          <a href={facility.website} target="_blank" rel="noreferrer">
                            {facility.website}
                          </a>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td>{cell(facility.operator)}</td>
                      <td className="hospital-map-cell">
                        {coords ? (
                          <button
                            type="button"
                            className="hospital-map-btn"
                            onClick={() => onShowOnMap(facility)}
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

          {canCollapse && (
            <p className="facilities-expand-row">
              <button
                type="button"
                className="facilities-expand-btn"
                onClick={() => setExpanded((value) => !value)}
              >
                {expanded
                  ? "Show fewer"
                  : `Show all ${rows.length} (${hiddenCount} more)`}
              </button>
            </p>
          )}

          {nearest && (
            <>
              <h3>Closest facility</h3>
              <ul>
                <li>
                  <strong>{nearest.name}</strong> — {nearest.distance_mi ?? "—"} mi from AOI
                  centroid
                </li>
                {nearest.phone && <li>Phone: {nearest.phone}</li>}
                {nearest.website && <li>Website: {nearest.website}</li>}
                {nearest.operator && <li>Operator: {nearest.operator}</li>}
              </ul>
            </>
          )}
        </>
      )}
    </article>
  );
}

export function FacilitiesPanel({ detail, onShowOnMap }: Props) {
  const hospitalsPayload = detail?.hospitals;
  const facilities = facilitiesFromDetail(detail);

  if (!detail?.facilities?.length && !hospitalsPayload) {
    return <p className="muted-note">N/A — facility lookup was not run for this AOI.</p>;
  }

  if (
    !facilities.length &&
    (hospitalsPayload?.status === "unavailable" || hospitalsPayload?.lookup_error)
  ) {
    return (
      <article className="report-md hospitals-md">
        <h2>Nearest Facilities</h2>
        <p>
          <em>Facility lookup unavailable: {hospitalsPayload.lookup_error ?? "N/A"}</em>
        </p>
      </article>
    );
  }

  if (!facilities.length) {
    return (
      <article className="report-md hospitals-md">
        <h2>Nearest Facilities</h2>
        <p>
          <em>
            No named hospitals, fire stations, police stations, or shelters were found in
            OpenStreetMap within the configured search radius.
          </em>
        </p>
      </article>
    );
  }

  const location = detail?.location as { centroid_wgs84?: [number, number] } | undefined;
  const facilitiesPayload = detail?.facilities_payload as
    | {
        aoi_centroid_wgs84?: [number, number];
        search_radius_km?: number;
      }
    | undefined;
  const centroid =
    hospitalsPayload?.aoi_centroid_wgs84 ??
    facilitiesPayload?.aoi_centroid_wgs84 ??
    location?.centroid_wgs84 ??
    null;
  const searchRadiusKm =
    hospitalsPayload?.search_radius_km ?? facilitiesPayload?.search_radius_km ?? null;

  const groups = KIND_ORDER.map((kind) => ({
    kind,
    rows: byDistance(facilities.filter((item) => (item.kind || "hospital") === kind)),
  })).filter((group) => group.rows.length > 0);

  return (
    <div className="facilities-panel-stack">
      {groups.map((group) => (
        <KindSection
          key={group.kind}
          kind={group.kind}
          rows={group.rows}
          centroid={centroid}
          searchRadiusKm={searchRadiusKm}
          onShowOnMap={onShowOnMap}
        />
      ))}
    </div>
  );
}

/** @deprecated Prefer FacilitiesPanel */
export const HospitalsPanel = FacilitiesPanel;
