import type { Hospital } from "../api/client";
import { hospitalLocationLabel } from "../hospitalUtils";

type Props = {
  hospital: Hospital;
};

function cell(value: string | number | null | undefined): string | null {
  if (value == null || value === "") return null;
  return String(value);
}

export function HospitalMapPopup({ hospital }: Props) {
  const address = hospitalLocationLabel(hospital);
  const distance = cell(hospital.distance_mi);
  const phone = cell(hospital.phone);
  const operator = cell(hospital.operator);
  const website = hospital.website?.trim() || null;

  return (
    <div className="hospital-popup">
      <div className="hospital-popup-title">{hospital.name}</div>
      <dl className="hospital-popup-details">
        {distance && (
          <>
            <dt>Distance</dt>
            <dd>{distance} mi from AOI centroid</dd>
          </>
        )}
        {address !== "—" && (
          <>
            <dt>Location</dt>
            <dd>{address}</dd>
          </>
        )}
        {phone && (
          <>
            <dt>Phone</dt>
            <dd>
              <a href={`tel:${phone.replace(/\s/g, "")}`}>{phone}</a>
            </dd>
          </>
        )}
        {website && (
          <>
            <dt>Website</dt>
            <dd>
              <a href={website} target="_blank" rel="noreferrer">
                {website}
              </a>
            </dd>
          </>
        )}
        {operator && (
          <>
            <dt>Operator</dt>
            <dd>{operator}</dd>
          </>
        )}
      </dl>
    </div>
  );
}
