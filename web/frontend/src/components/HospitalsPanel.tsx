import type { AoiDetail, Hospital } from "../api/client";
import {
  hospitalLocationLabel,
  hospitalRowKey,
  resolveHospitalCoords,
  type HospitalsPayload,
} from "../hospitalUtils";

type Props = {
  detail: AoiDetail | null;
  onShowOnMap: (hospital: Hospital) => void;
};

function cell(value: string | number | null | undefined): string {
  if (value == null || value === "") return "—";
  return String(value);
}

export function HospitalsPanel({ detail, onShowOnMap }: Props) {
  const payload = detail?.hospitals as HospitalsPayload | undefined;

  if (!payload) {
    return <p className="muted-note">N/A — hospital lookup was not run for this AOI.</p>;
  }

  if (payload.status === "unavailable" || payload.lookup_error) {
    return (
      <article className="report-md hospitals-md">
        <h2>Nearest Hospitals</h2>
        <p>
          <em>Hospital lookup unavailable: {payload.lookup_error ?? "N/A"}</em>
        </p>
      </article>
    );
  }

  const hospitals = payload.hospitals ?? [];
  if (!hospitals.length) {
    return (
      <article className="report-md hospitals-md">
        <h2>Nearest Hospitals</h2>
        <p>
          <em>No hospitals were found in OpenStreetMap within the configured search radius.</em>
        </p>
      </article>
    );
  }

  const nearest = payload.nearest;
  const centroid = payload.aoi_centroid_wgs84;

  return (
    <article className="report-md hospitals-md">
      <h2>Nearest Hospitals</h2>
      <p>
        <em>
          Emergency medical facility context from OpenStreetMap. Distances are straight-line from
          the AOI imagery centroid. Verify contact details operationally.
        </em>
      </p>
      <ul>
        {centroid && (
          <li>
            AOI centroid (WGS84): <code>[{centroid[0]}, {centroid[1]}]</code>
          </li>
        )}
        {payload.search_radius_km != null && (
          <li>Search radius: {payload.search_radius_km} km</li>
        )}
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
            {hospitals.map((hospital) => {
              const coords = resolveHospitalCoords(hospital);
              return (
                <tr key={hospitalRowKey(hospital)}>
                  <td>{hospital.name}</td>
                  <td>{cell(hospital.distance_mi)}</td>
                  <td>{hospitalLocationLabel(hospital)}</td>
                  <td>{cell(hospital.phone)}</td>
                  <td>
                    {hospital.website ? (
                      <a href={hospital.website} target="_blank" rel="noreferrer">
                        {hospital.website}
                      </a>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td>{cell(hospital.operator)}</td>
                  <td className="hospital-map-cell">
                    {coords ? (
                      <button
                        type="button"
                        className="hospital-map-btn"
                        onClick={() => onShowOnMap(hospital)}
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

      {nearest && (
        <>
          <h3>Closest facility</h3>
          <ul>
            <li>
              <strong>{nearest.name}</strong> — {nearest.distance_mi ?? "—"} mi from AOI centroid
            </li>
            {nearest.phone && <li>Phone: {nearest.phone}</li>}
            {nearest.website && <li>Website: {nearest.website}</li>}
            {nearest.operator && <li>Operator: {nearest.operator}</li>}
          </ul>
        </>
      )}
    </article>
  );
}
