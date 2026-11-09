from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import xarray as xr

pytest.importorskip("zarr")

from climate.packager.maps import load_series_grid_from_metric  # noqa: E402
from climate.packager.registry import (
    TileRange,
    _batch_missing_tiles,
    _tiles_from_time_da,
)  # noqa: E402
from climate.packager.tiles import write_series_tiles  # noqa: E402
from climate.tiles import zarr_tiles  # noqa: E402
from climate.tiles.io import metric_ntime, read_metric_tile  # noqa: E402
from climate.tiles.layout import GridSpec  # noqa: E402

GRID = GridSpec(
    grid_id="test",
    deg=1.0,
    nlat=20,
    nlon=24,
    tile_size=16,
    lat_max=10.0,
    lon_min=-12.0,
    lon_max=12.0,
)
ZARR = {"format": "zarr", "encoding": {"dtype": "int16", "scale": 0.01, "delta": True}}


def _da(ntime: int) -> tuple[xr.DataArray, np.ndarray]:
    rng = np.random.default_rng(0)
    vals = rng.normal(10, 4, (GRID.nlat, GRID.nlon, ntime)).astype(np.float32)
    lat = GRID.lat_max - (np.arange(GRID.nlat) + 0.5) * GRID.deg
    lon = GRID.lon_min + (np.arange(GRID.nlon) + 0.5) * GRID.deg
    da = xr.DataArray(
        vals,
        coords={"latitude": lat, "longitude": lon, "month": np.arange(ntime)},
        dims=("latitude", "longitude", "month"),
    )
    return da, vals


def _package(out_root: Path, da: xr.DataArray, *, storage=ZARR, resume=False) -> int:
    return _tiles_from_time_da(
        da=da,
        axis_values=[f"2000-{m + 1:02d}" for m in range(da.sizes["month"])],
        time_dim="month",
        axis_name="monthly",
        out_root=out_root,
        grid=GRID,
        metric_id="m",
        tile_range=TileRange(tile_r0=0, tile_r1=1, tile_c0=0, tile_c1=1),
        dtype=np.dtype("float32"),
        missing="nan",
        compression=None,
        storage=storage,
        debug=False,
        resume=resume,
    )


def test_packager_writes_zarr_that_every_reader_sees(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    da, vals = _da(12)
    assert _package(tmp_path, da) == 4
    root = tmp_path / "test" / "m"
    assert (root / "zarr" / "zarr.json").exists() and not (root / "z16").exists()
    assert metric_ntime(tmp_path, GRID, "m", ZARR) == 12

    # API single-cell reader
    assert np.max(np.abs(zarr_tiles.read_cell(root, 17, 20) - vals[17, 20])) <= 0.0051
    # whole-tile reader, padded like the old format
    tile = read_metric_tile(tmp_path, GRID, "m", 1, 1, ZARR)
    assert tile.shape == (16, 16, 12) and np.isnan(tile[4:, :, :]).all()
    # maps loader over the whole grid
    spec = {
        "grid_id": "test",
        "time_axis": "monthly",
        "storage": {**ZARR, "tile_size": 16},
    }
    monkeypatch.setattr(
        "climate.packager.maps.grid_from_id", lambda gid, tile_size: GRID
    )
    full, _grid, axis = load_series_grid_from_metric(
        series_root=tmp_path, metric_id="m", metric_spec=spec
    )
    assert full.shape == (20, 24, 12) and len(axis) == 12
    assert np.max(np.abs(full - vals)) <= 0.0051


def test_resume_skips_written_tiles_and_lists_missing_ones(tmp_path: Path) -> None:
    da, _ = _da(5)
    batch = TileRange(tile_r0=0, tile_r1=1, tile_c0=0, tile_c1=1)
    assert (
        len(_batch_missing_tiles(tmp_path, GRID, "m", batch, None, storage=ZARR)) == 4
    )
    _package(tmp_path, da)
    assert _batch_missing_tiles(tmp_path, GRID, "m", batch, None, storage=ZARR) == []
    assert _package(tmp_path, da, resume=True) == 0


def test_empty_tiles_are_stored_and_a_lost_one_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Data only in tile (0, 0), as for a reef metric: the other tiles are stored empty.
    da, _ = _da(5)
    keep = np.zeros((GRID.nlat, GRID.nlon), dtype=bool)
    keep[:16, :16] = True
    da = da.where(xr.DataArray(keep, dims=("latitude", "longitude")))
    batch = TileRange(tile_r0=0, tile_r1=1, tile_c0=0, tile_c1=1)
    assert _package(tmp_path, da) == 4
    assert _batch_missing_tiles(tmp_path, GRID, "m", batch, None, storage=ZARR) == []
    assert np.isnan(read_metric_tile(tmp_path, GRID, "m", 1, 1, ZARR)).all()

    # A lost shard: resume redoes the tile and readers raise.
    (tmp_path / "test" / "m" / "zarr" / "c" / "0" / "1" / "1").unlink()
    assert _batch_missing_tiles(tmp_path, GRID, "m", batch, None, storage=ZARR) == [
        (1, 1)
    ]
    with pytest.raises(FileNotFoundError, match="Missing source tile: m r1 c1"):
        read_metric_tile(tmp_path, GRID, "m", 1, 1, ZARR)
    spec = {
        "grid_id": "test",
        "time_axis": "monthly",
        "storage": {**ZARR, "tile_size": 16},
    }
    monkeypatch.setattr(
        "climate.packager.maps.grid_from_id", lambda gid, tile_size: GRID
    )
    with pytest.raises(FileNotFoundError, match="r1 c1"):
        load_series_grid_from_metric(
            series_root=tmp_path, metric_id="m", metric_spec=spec
        )


def test_clipping_stops_the_packager(tmp_path: Path) -> None:
    da, _ = _da(3)
    da[0, 0, 0] = 400.0
    with pytest.raises(ValueError, match="refusing to clip"):
        _package(tmp_path, da)


def test_write_series_tiles_scalar_zarr(tmp_path: Path) -> None:
    scalar = np.arange(GRID.nlat * GRID.nlon, dtype=np.float32).reshape(
        GRID.nlat, GRID.nlon
    )
    n = write_series_tiles(
        out_root=tmp_path,
        grid=GRID,
        metric_id="s",
        axis_values=[],
        series=scalar,
        dtype="float32",
        missing="nan",
        storage={"format": "zarr"},
    )
    assert n == 4
    got = zarr_tiles.read_cell(tmp_path / "test" / "s", 19, 23)
    assert got.shape == (1,) and got[0] == scalar[19, 23]


def test_coverage_check_lists_zarr_tiles_and_flags_format_mismatches(
    tmp_path: Path,
) -> None:
    from scripts.tile_coverage import _format_mismatch, _read_tile, _tiles_present

    da, _ = _da(4)
    series = tmp_path / "series"
    _package(series, da)
    zdir, tiles = _tiles_present(tmp_path, GRID, "m", ZARR)
    assert tiles == [(0, 0), (0, 1), (1, 0), (1, 1)]
    nyears, arr = _read_tile(tmp_path, GRID, "m", 1, 0, ZARR)
    assert nyears == 4 and arr.shape == (16, 16, 4)

    assert _format_mismatch(tmp_path, GRID, "m", ZARR) is None
    assert "files are zarr" in _format_mismatch(tmp_path, GRID, "m", {})
    _package(series, da, storage={"compression": {"codec": "none"}})
    assert "both zarr/ and z16/" in _format_mismatch(tmp_path, GRID, "m", ZARR)


def test_coverage_check_finds_missing_tiles_and_data_outside_a_dataset_mask(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts import tile_coverage as tcov

    monkeypatch.setattr(tcov, "grid_from_id", lambda gid, tile_size: GRID)
    da, _ = _da(3)
    mask = np.zeros((GRID.nlat, GRID.nlon), dtype=bool)
    mask[2:6, 3:9] = True  # inside tile (0, 0)
    da = da.where(xr.DataArray(mask, dims=("latitude", "longitude")))
    _package(tmp_path / "series", da)
    assert tcov._missing_tiles(tmp_path, GRID, "m", ZARR) == []

    def summary() -> dict:
        return tcov._metric_summary(
            root=tmp_path, metric_id="m", grid_id="test", tile_size=16, max_tiles=0,
            summary_only=True, domain_mask=mask, domain_label="dataset_mask",
            storage=ZARR, count_outside=True,
        )  # fmt: skip

    got = summary()
    assert got["domain_coverage_pct"] == 100.0 and got["outside_cells"] == 0
    # Data next to the mask, in another tile, is data where none may be.
    mask[2, 3] = mask[2, 4] = False
    got = summary()
    assert got["outside_cells"] == 2 and got["outside_tiles"] == [(0, 0)]

    (tmp_path / "series" / "test" / "m" / "zarr" / "c" / "0" / "1" / "0").unlink()
    assert tcov._missing_tiles(tmp_path, GRID, "m", ZARR) == [(1, 0)]
