export type MapFocus =
  | {
      kind: "hospital";
      key: number;
      hospitalKey: string;
      name: string;
      coordinates_wgs84: [number, number];
    }
  | {
      kind: "building";
      key: number;
      bldId: string;
      coordinates_wgs84: [number, number];
    };
