export type MapFocus =
  | {
      kind: "hospital";
      key: number;
      hospitalKey: string;
      name: string;
      coordinates_wgs84: [number, number];
      /** Optional subtype when focused from chat (fire/police/shelter). */
      facilityKind?: string;
      distance_mi?: string;
    }
  | {
      kind: "building";
      key: number;
      bldId: string;
      coordinates_wgs84: [number, number];
    };
