from __future__ import annotations

from pathlib import Path

import numpy as np
import xarray as xr

from climate.packager.registry import TileRange, _batch_has_any_valid_cells, _tiles_from_time_da
from climate.tiles.layout import GridSpec


def test_batch_has_any_valid_cells() -> None:
    grid = GridSpec(
        grid_id="test",
        deg=1.0,
        nlat=4,
        nlon=4,
        tile_size=2,
        lat_max=2.0,
        lon_min=-2.0,
        lon_max=2.0,
    )
    mask = np.zeros((4, 4), dtype=bool)
    mask[2, 2] = True

    assert not _batch_has_any_valid_cells(
        dataset_mask=mask,
        grid=grid,
        tile_range=TileRange(tile_r0=0, tile_r1=0, tile_c0=0, tile_c1=0),
    )
    assert _batch_has_any_valid_cells(
        dataset_mask=mask,
        grid=grid,
        tile_range=TileRange(tile_r0=1, tile_r1=1, tile_c0=1, tile_c1=1),
    )


def test_tiles_from_time_da_applies_dataset_mask(
    monkeypatch,
    tmp_path: Path,
) -> None:
    grid = GridSpec(
        grid_id="test",
        deg=1.0,
        nlat=2,
        nlon=2,
        tile_size=2,
        lat_max=1.0,
        lon_min=-1.0,
        lon_max=1.0,
    )
    lat = np.array([0.5, -0.5], dtype=np.float64)
    lon = np.array([-0.5, 0.5], dtype=np.float64)
    da = xr.DataArray(
        np.array([[[1.0], [2.0]], [[3.0], [4.0]]], dtype=np.float32),
        coords={"latitude": lat, "longitude": lon, "year": [2025]},
        dims=("latitude", "longitude", "year"),
    )

    captured: list[np.ndarray] = []

    def _fake_write_tile(
        _path,
        tile,
        *,
        dtype,
        nyears,
        tile_h,
        tile_w,
        compress_level,
    ) -> None:
        captured.append(np.array(tile, copy=True))

    monkeypatch.setattr("climate.packager.registry.write_tile", _fake_write_tile)

    written = _tiles_from_time_da(
        da=da,
        axis_values=[2025],
        time_dim="year",
        axis_name="yearly",
        out_root=tmp_path,
        grid=grid,
        metric_id="dhw_test",
        tile_range=TileRange(tile_r0=0, tile_r1=0, tile_c0=0, tile_c1=0),
        dtype=np.dtype("float32"),
        missing=np.nan,
        compression={"codec": "none"},
        debug=False,
        resume=False,
        dataset_mask=np.array([[1, 0], [0, 1]], dtype=bool),
    )

    assert written == 1
    assert len(captured) == 1
    tile = captured[0]
    assert tile.shape == (2, 2, 1)
    assert float(tile[0, 0, 0]) == 1.0
    assert np.isnan(tile[0, 1, 0])
    assert np.isnan(tile[1, 0, 0])
    assert float(tile[1, 1, 0]) == 4.0
