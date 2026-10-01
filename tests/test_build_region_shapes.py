from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("rasterio")
pytest.importorskip("scipy")

from scripts.build.build_region_shapes import polygonise_regions  # noqa: E402

# A 1°-cell grid spanning 10°N..0° and 20°W..0°: row r, column c is the cell
# whose top-left corner is (lon=-20+c, lat=10-r).
GRID = dict(deg=1.0, lat_max=10.0, lon_min=-20.0)


def _mask() -> np.ndarray:
    mask = np.zeros((10, 20), dtype=np.int32)
    # Region 1: two separate blocks, like a mainland and an island.
    mask[1:3, 1:4] = 1
    mask[6:8, 10:12] = 1
    # Region 2: a 5x5 block with a one-cell hole, like a lake inside a country.
    mask[2:7, 14:19] = 2
    mask[4, 16] = 0
    return mask


def _shapes() -> dict:
    return polygonise_regions(
        _mask(),
        **GRID,
        region_ids={1: "country:AA", 2: "country:BB", 3: "ocean:erased"},
    )


def test_one_multipolygon_per_region_with_cells() -> None:
    shapes = _shapes()
    # Region 3 is named but has no cells — like the Great Barrier Reef, erased
    # from the ocean mask — so it gets no outline, just as it gets no average.
    assert set(shapes) == {"country:AA", "country:BB"}
    assert all(s["type"] == "MultiPolygon" for s in shapes.values())


def test_separate_parts_stay_separate() -> None:
    assert len(_shapes()["country:AA"]["coordinates"]) == 2


def test_a_hole_in_the_mask_is_a_hole_in_the_outline() -> None:
    (polygon,) = _shapes()["country:BB"]["coordinates"]
    exterior, *holes = polygon
    assert len(holes) == 1
    hole_xs = sorted({x for x, _ in holes[0]})
    hole_ys = sorted({y for _, y in holes[0]})
    # Row 4, column 16: lon -4..-3, lat 6..5.
    assert (hole_xs, hole_ys) == ([-4.0, -3.0], [5.0, 6.0])


def test_outline_lies_exactly_on_cell_corners() -> None:
    (mainland, _island) = _shapes()["country:AA"]["coordinates"]
    xs = sorted({x for x, _ in mainland[0]})
    ys = sorted({y for _, y in mainland[0]})
    # Rows 1..2, columns 1..3: lon -19..-16, lat 9..7.
    assert (xs[0], xs[-1], ys[0], ys[-1]) == (-19.0, -16.0, 7.0, 9.0)


def test_values_the_caller_does_not_name_are_skipped() -> None:
    shapes = polygonise_regions(_mask(), **GRID, region_ids={2: "country:BB"})
    assert set(shapes) == {"country:BB"}
