from __future__ import annotations

import pytest

from climate.tiles.layout import GridSpec, cell_center_latlon, snap_to_cell_indices


def test_global_0p25_uses_strict_cell_grid_dimensions_and_centers() -> None:
    grid = GridSpec.global_0p25(tile_size=64)
    assert grid.nlat == 720
    assert grid.nlon == 1440

    lat0, lon0 = cell_center_latlon(0, 0, grid)
    lat_last, lon_last = cell_center_latlon(grid.nlat - 1, grid.nlon - 1, grid)

    assert lat0 == pytest.approx(89.875)
    assert lat_last == pytest.approx(-89.875)
    assert lon0 == pytest.approx(-179.875)
    assert lon_last == pytest.approx(179.875)

    # Cell edges close exactly on the poles.
    half = grid.deg / 2.0
    assert (lat0 + half) == pytest.approx(90.0)
    assert (lat_last - half) == pytest.approx(-90.0)


def test_global_0p05_uses_strict_cell_grid_dimensions_and_centers() -> None:
    grid = GridSpec.global_0p05(tile_size=64)
    assert grid.nlat == 3600
    assert grid.nlon == 7200

    lat0, _ = cell_center_latlon(0, 0, grid)
    lat_last, _ = cell_center_latlon(grid.nlat - 1, 0, grid)
    assert lat0 == pytest.approx(89.975)
    assert lat_last == pytest.approx(-89.975)


def test_snap_to_cell_indices_clamps_poles_on_cell_grid() -> None:
    grid = GridSpec.global_0p25(tile_size=64)

    north = snap_to_cell_indices(90.0, 0.0, grid)
    south = snap_to_cell_indices(-90.0, 0.0, grid)

    assert north.i_lat == 0
    assert south.i_lat == grid.nlat - 1
