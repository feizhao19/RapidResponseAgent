"""Fusion assignment: vectorized histograms match the old per-building scans."""

from __future__ import annotations

import numpy as np
from rasterio.transform import from_origin
from shapely.geometry import box

import geopandas as gpd

from scripts.assign_building_damage import (
    assign_damage,
    building_class_count_matrix,
    class_counts,
    polygon_pixels_for_building,
    rasterize_building_ids,
)


def _toy_buildings() -> gpd.GeoDataFrame:
    # Three non-overlapping 2x2 cells in pixel space (transform = identity scale 1).
    return gpd.GeoDataFrame(
        {
            "BLD_ID": ["A", "B", "C"],
            "geometry": [
                box(0, 0, 2, 2),
                box(3, 0, 5, 2),
                box(6, 0, 8, 2),
            ],
        },
        crs="EPSG:3857",
    )


def test_building_class_count_matrix_matches_per_building_extract():
    buildings = _toy_buildings()
    transform = from_origin(0, 2, 1, 1)  # 2 rows x 8 cols covers boxes
    damage = np.array(
        [
            [1, 4, 0, 2, 2, 0, 0, 0],
            [1, 3, 0, 1, 0, 0, 4, 4],
        ],
        dtype=np.uint8,
    )
    building_ids = rasterize_building_ids(buildings, damage.shape, transform)
    matrix, totals = building_class_count_matrix(building_ids, damage, len(buildings))

    for bid in range(1, len(buildings) + 1):
        pixels = polygon_pixels_for_building(damage, building_ids, bid, "max")
        expected = class_counts(pixels)
        for c in range(5):
            assert int(matrix[bid, c]) == expected[c]
        assert int(totals[bid]) == int(pixels.size)


def test_assign_damage_max_levels():
    buildings = _toy_buildings()
    transform = from_origin(0, 2, 1, 1)
    damage = np.array(
        [
            [1, 4, 0, 2, 2, 0, 0, 0],
            [1, 3, 0, 1, 0, 0, 4, 4],
        ],
        dtype=np.uint8,
    )
    out = assign_damage(
        buildings,
        damage,
        transform,
        min_pixels=1,
        fusion_mode="max",
        detect_orphan_damage=False,
    )
    # A: classes 1,4,1,3 → max 4 destroyed
    # B: 2,2,1 → max 2 minor
    # C: 4,4 → max 4 destroyed
    assert list(out["damage_level"]) == [4, 2, 4]
    assert list(out["assignment_status"]) == ["vipde", "vipde", "vipde"]
