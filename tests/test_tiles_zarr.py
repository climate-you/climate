from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

zarr = pytest.importorskip("zarr")

from climate.tiles import zarr_tiles as zt  # noqa: E402
from climate.tiles.layout import GridSpec  # noqa: E402

# Small grid with a partial last tile row and column (40 = 2x16 + 8, 56 = 3x16 + 8).
GRID = GridSpec(grid_id="test", deg=1.0, nlat=40, nlon=56, tile_size=16)
NTR, NTC = 3, 4

I16 = zt.Encoding(dtype=np.dtype("int16"), scale=0.01, delta=True)
U16 = zt.Encoding(dtype=np.dtype("uint16"), scale=0.02)
F32 = zt.Encoding()


def _field(
    ntime: int, *, seed: int = 0, lo: float = -40.0, hi: float = 40.0
) -> np.ndarray:
    """(nlat, nlon, ntime) smooth-ish field with some NaNs."""
    rng = np.random.default_rng(seed)
    base = np.linspace(lo, hi, GRID.nlat)[:, None, None]
    a = base + rng.normal(0, 3, (GRID.nlat, GRID.nlon, max(ntime, 1)))
    a[rng.random(a.shape) < 0.02] = np.nan
    return a.astype(np.float32) if ntime else a[:, :, 0].astype(np.float32)


def _padded_tile(field: np.ndarray, tr: int, tc: int) -> np.ndarray:
    ts = GRID.tile_size
    shape = (ts, ts) + field.shape[2:]
    out = np.full(shape, np.nan, dtype=np.float32)
    blk = field[tr * ts : (tr + 1) * ts, tc * ts : (tc + 1) * ts]
    out[: blk.shape[0], : blk.shape[1]] = blk
    return out


def _write(
    root: Path, field: np.ndarray, enc: zt.Encoding, shard_time: int | None = None
) -> zt.ZarrTileWriter:
    ntime = field.shape[2] if field.ndim == 3 else 0
    w = zt.ZarrTileWriter(
        root, grid=GRID, ntime=ntime, encoding=enc, shard_time=shard_time
    )
    for tr in range(NTR):
        for tc in range(NTC):
            w.write(tr, tc, _padded_tile(field, tr, tc))
    return w


@pytest.mark.parametrize(
    "enc, shard_time, ntime",
    [
        (I16, None, 30),
        (I16, 7, 30),
        (U16, 12, 25),
        (F32, 10, 21),
        (F32, None, 0),
        (I16, None, 0),
    ],
)
def test_read_cell_matches_source_and_zarr_python(
    tmp_path: Path, enc, shard_time, ntime
) -> None:
    lo = 0.0 if enc.dtype.kind == "u" else -40.0
    field = _field(ntime, lo=lo, hi=80.0 if lo == 0 else 40.0)
    if enc.dtype.kind == "u":
        field = np.abs(field)
    _write(tmp_path, field, enc, shard_time)
    arr = zarr.open_array(str(zt.zarr_dir(tmp_path)), mode="r")
    tol = enc.scale / 2 + 1e-4 if not enc.is_float else 0.0
    for i, j in [(0, 0), (15, 16), (39, 55), (33, 50), (20, 3)]:
        got = zt.read_cell(tmp_path, i, j)
        want = field[i, j] if ntime else field[i, j : j + 1]
        assert got.shape == ((ntime,) if ntime else (1,))
        assert np.array_equal(np.isnan(got), np.isnan(want))
        assert np.nanmax(np.abs(got - want), initial=0.0) <= tol
        via_zarr = np.asarray(arr[:, i, j] if ntime else arr[i, j : j + 1])
        assert np.array_equal(got, enc.decode(via_zarr), equal_nan=True)


def test_read_tile_has_old_format_shape_and_padding(tmp_path: Path) -> None:
    field = _field(9)
    _write(tmp_path, field, I16, shard_time=4)
    tile = zt.read_tile(tmp_path, 2, 3, tile_size=GRID.tile_size)
    assert tile.shape == (16, 16, 9)
    assert np.isnan(tile[8:, :, :]).all() and np.isnan(tile[:, 8:, :]).all()
    want = field[32:40, 48:56]
    assert np.nanmax(np.abs(tile[:8, :8] - want)) <= 0.0051
    scalar = _field(0)
    _write(tmp_path / "s", scalar, F32)
    assert zt.read_tile(tmp_path / "s", 0, 1, tile_size=16).shape == (16, 16)


def test_shard_files_one_per_tile_and_time_block(tmp_path: Path) -> None:
    _write(tmp_path, _field(30), I16, shard_time=12)
    shards = sorted(
        p.relative_to(zt.zarr_dir(tmp_path) / "c")
        for p in (zt.zarr_dir(tmp_path) / "c").rglob("*")
        if p.is_file()
    )
    assert len(shards) == 3 * NTR * NTC
    assert Path("2/1/3") in shards


def test_empty_tiles_are_stored_and_a_missing_shard_is_an_error(tmp_path: Path) -> None:
    field = _field(10)
    w = zt.ZarrTileWriter(tmp_path, grid=GRID, ntime=10, encoding=I16, shard_time=4)
    w.write(0, 0, _padded_tile(field, 0, 0))
    assert w.exists(0, 0) and not w.exists(1, 1)
    with pytest.raises(FileNotFoundError):
        zt.read_cell(tmp_path, 20, 20)
    # An all-missing tile still writes its shards, as the old format writes its file.
    w.write(1, 1, np.full((16, 16, 10), np.nan, dtype=np.float32))
    assert w.exists(1, 1)
    assert np.isnan(zt.read_cell(tmp_path, 20, 20)).all()
    # Rewriting a tile that had data as empty leaves no stale values.
    w.write(0, 0, np.full((16, 16, 10), np.nan, dtype=np.float32))
    assert w.exists(0, 0)
    assert np.isnan(zt.read_cell(tmp_path, 3, 3)).all()


def test_writers_in_parallel_processes_share_one_array(tmp_path: Path) -> None:
    import concurrent.futures as cf

    field = _field(8)
    tiles = [(tr, tc) for tr in range(NTR) for tc in range(NTC)]
    with cf.ProcessPoolExecutor(max_workers=4) as ex:
        list(ex.map(_write_one_tile, [(tmp_path, field, t) for t in tiles]))
    for i, j in [(0, 0), (39, 55), (17, 30)]:
        assert np.nanmax(np.abs(zt.read_cell(tmp_path, i, j) - field[i, j])) <= 0.0051


def _write_one_tile(args) -> None:
    root, field, (tr, tc) = args
    w = zt.ZarrTileWriter(
        root, grid=GRID, ntime=field.shape[2], encoding=I16, shard_time=3
    )
    w.write(tr, tc, _padded_tile(field, tr, tc))


def test_rerun_keeps_tiles_outside_its_range_and_recreates_on_new_layout(
    tmp_path: Path,
) -> None:
    field = _field(6)
    _write(tmp_path, field, I16, shard_time=3)
    # A same-layout run over one tile leaves the others in place.
    w = zt.ZarrTileWriter(tmp_path, grid=GRID, ntime=6, encoding=I16, shard_time=3)
    w.write(0, 0, _padded_tile(field + 1, 0, 0))
    assert np.nanmax(np.abs(zt.read_cell(tmp_path, 1, 1) - (field[1, 1] + 1))) <= 0.0051
    assert np.nanmax(np.abs(zt.read_cell(tmp_path, 30, 50) - field[30, 50])) <= 0.0051
    # A different encoding recreates the array: the old tiles are gone.
    zt.ZarrTileWriter(tmp_path, grid=GRID, ntime=6, encoding=F32, shard_time=3)
    with pytest.raises(FileNotFoundError):
        zt.read_cell(tmp_path, 30, 50)


def test_non_nan_fill_value_marks_missing(tmp_path: Path) -> None:
    field = _field(4)
    tile = _padded_tile(field, 0, 0)
    tile[np.isnan(tile)] = -9999.0
    w = zt.ZarrTileWriter(tmp_path, grid=GRID, ntime=4, encoding=I16)
    w.write(0, 0, tile, fill=-9999.0)
    got = zt.read_cell(tmp_path, 2, 3)
    assert np.array_equal(np.isnan(got), np.isnan(field[2, 3]))


def test_encode_refuses_to_clip() -> None:
    enc = zt.Encoding(dtype=np.dtype("uint16"), scale=0.01)
    assert enc.encode(np.array([0.0, 655.34, np.nan]))[1] == 65534
    with pytest.raises(ValueError, match="refusing to clip"):
        enc.encode(np.array([1.0, 655.35]), label="tp")
    with pytest.raises(ValueError, match="refusing to clip"):
        enc.encode(np.array([-0.01]))
    with pytest.raises(ValueError, match="refusing to clip"):
        I16.encode(np.array([-327.68]))


def test_round_trip_error_is_half_a_step() -> None:
    x = np.linspace(-300, 300, 100_001)
    err = np.abs(I16.decode(I16.encode(x)) - x)
    assert err.max() <= 0.005 + 1e-4


def test_encoding_from_storage_and_shard_time() -> None:
    storage = {"format": "zarr", "encoding": {"dtype": "uint16", "scale": 0.02}}
    enc = zt.Encoding.from_storage(storage)
    assert enc.dtype == np.dtype("<u2") and enc.scale == 0.02 and not enc.delta
    assert zt.Encoding.from_storage(None) == zt.Encoding()
    assert zt.shard_time_for(storage, "daily", 2069) == 366
    assert zt.shard_time_for(storage, "monthly", 572) == 120
    assert zt.shard_time_for(storage, "yearly", 47) == 47
    assert zt.shard_time_for({"shard_time": 24}, "monthly", 572) == 24
    with pytest.raises(ValueError):
        zt.Encoding(dtype=np.dtype("float32"), scale=0.01)


def test_resume_reopens_and_rejects_a_changed_axis(tmp_path: Path) -> None:
    field = _field(10)
    _write(tmp_path, field, I16, shard_time=4)
    w = zt.ZarrTileWriter(
        tmp_path, grid=GRID, ntime=10, encoding=I16, shard_time=4, resume=True
    )
    assert w.exists(2, 3)
    with pytest.raises(SystemExit, match="re-run without --resume"):
        zt.ZarrTileWriter(
            tmp_path, grid=GRID, ntime=11, encoding=I16, shard_time=4, resume=True
        )
    with pytest.raises(SystemExit, match="re-run without --resume"):
        zt.ZarrTileWriter(
            tmp_path, grid=GRID, ntime=10, encoding=U16, shard_time=4, resume=True
        )


def test_reader_rejects_layouts_it_does_not_know(tmp_path: Path) -> None:
    arr = zarr.create_array(
        str(tmp_path / "zarr"), shape=(4, 4), chunks=(2, 2), dtype="f4"
    )
    arr[:] = 1.0
    with pytest.raises(ValueError, match="sharding"):
        zt.read_cell(tmp_path, 0, 0)
