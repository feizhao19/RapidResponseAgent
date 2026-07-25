export type PriorityGridCell = {
  direction: string;
  /** west, south, east, north */
  bounds_wgs84: [number, number, number, number];
  impact_score: number;
  destroyed: number;
  major: number;
  minor: number;
  /** 1/2/3 when this cell is a ranked Mission Priority */
  priority?: number;
};

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
    }
  | {
      kind: "road";
      key: number;
      roadId: string;
      name: string;
      coordinates_wgs84: [number, number];
      roadKind?: string;
      severity?: string;
    }
  | {
      kind: "region";
      key: number;
      name: string;
      /** Focused priority cell: west, south, east, north */
      bounds_wgs84: [number, number, number, number];
      priority?: number;
      direction?: string;
      /** Full AOI bounds when available (show whole 3×3). */
      aoiBounds?: [number, number, number, number];
      cells?: PriorityGridCell[];
    };
