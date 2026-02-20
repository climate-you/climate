from __future__ import annotations

import numpy as np
import xarray as xr

from climate.packager.registry import TileRange, _maybe_regrid_to_metric_grid
from climate.tiles.layout import GridSpec


def test_regrid_fills_only_outside_source_bounds_with_nearest() -> None:
    src_lat = np.array([-1.0, 0.0, 1.0], dtype=np.float64)
    src_lon = np.array([-1.0, 0.0, 1.0], dtype=np.float64)
    src_vals = np.array(
        [
            [0.0, 1.0, 2.0],
            [1.0, 2.0, 3.0],
            [2.0, 3.0, 4.0],
        ],
        dtype=np.float64,
    )
    da = xr.DataArray(
        src_vals,
        coords={"lat": src_lat, "lon": src_lon},
        dims=("lat", "lon"),
    )
    grid = GridSpec(
        grid_id="test",
        deg=1.0,
        nlat=5,
        nlon=5,
        tile_size=5,
        lat_max=2.5,
        lon_min=-2.5,
        lon_max=2.5,
    )
    out = _maybe_regrid_to_metric_grid(
        da=da,
        grid=grid,
        tile_range=TileRange(0, 0, 0, 0),
        params={"regrid_to_metric_grid": True, "regrid_method": "bilinear"},
        debug=False,
        label="test",
        metric_id="metric_test",
    )
    vals = np.asarray(out.values, dtype=np.float64)
    assert vals.shape == (5, 5)
    assert np.all(np.isfinite(vals))
    assert vals[0, 0] == src_vals[2, 0]
    assert vals[-1, -1] == src_vals[0, 2]


def test_regrid_does_not_fill_interior_nans() -> None:
    src_lat = np.array([-1.0, 0.0, 1.0], dtype=np.float64)
    src_lon = np.array([-1.0, 0.0, 1.0], dtype=np.float64)
    src_vals = np.array(
        [
            [0.0, 1.0, 2.0],
            [1.0, np.nan, 3.0],
            [2.0, 3.0, 4.0],
        ],
        dtype=np.float64,
    )
    da = xr.DataArray(
        src_vals,
        coords={"lat": src_lat, "lon": src_lon},
        dims=("lat", "lon"),
    )
    grid = GridSpec(
        grid_id="test",
        deg=1.0,
        nlat=3,
        nlon=3,
        tile_size=3,
        lat_max=1.5,
        lon_min=-1.5,
        lon_max=1.5,
    )
    out = _maybe_regrid_to_metric_grid(
        da=da,
        grid=grid,
        tile_range=TileRange(0, 0, 0, 0),
        params={"regrid_to_metric_grid": True, "regrid_method": "bilinear"},
        debug=False,
        label="test",
        metric_id="metric_test",
    )
    vals = np.asarray(out.values, dtype=np.float64)
    assert np.isnan(vals[1, 1])
