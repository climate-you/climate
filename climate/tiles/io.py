# climate/tiles/io.py
"""Format-independent access to a metric's tiles, for packager-side readers.

A metric's registry ``storage.format`` says how its tiles are stored
(``clmtile`` by default, or ``zarr``); these helpers hide the difference from
code that reads whole tiles (maps, aggregates, coverage checks).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from climate.tiles import zarr_tiles
from climate.tiles.layout import GridSpec, tile_path
from climate.tiles.spec import read_tile_array, write_tile


def storage_format(storage: dict[str, Any] | None) -> str:
    fmt = str((storage or {}).get("format", "clmtile"))
    if fmt not in ("clmtile", "zarr"):
        raise ValueError(f"Unknown storage format: {fmt}")
    return fmt


def clmtile_ext(storage: dict[str, Any] | None) -> str:
    codec = ((storage or {}).get("compression") or {}).get("codec", "zstd")
    if codec == "zstd":
        return ".bin.zst"
    if codec == "none":
        return ".bin"
    raise ValueError(f"Unsupported compression codec: {codec}")


def metric_root(series_root: str | Path, grid: GridSpec, metric_id: str) -> Path:
    """{series_root}/{grid_id}/{metric_id}: holds time/ and z<tile_size>/ or zarr/."""
    return Path(series_root) / grid.grid_id / metric_id


def metric_exists(
    series_root: str | Path,
    grid: GridSpec,
    metric_id: str,
    storage: dict[str, Any] | None,
) -> bool:
    root = metric_root(series_root, grid, metric_id)
    if storage_format(storage) == "zarr":
        return (zarr_tiles.zarr_dir(root) / "zarr.json").exists()
    return (root / f"z{int(grid.tile_size)}").is_dir()


def tile_written(
    series_root: str | Path,
    grid: GridSpec,
    metric_id: str,
    tile_r: int,
    tile_c: int,
    storage: dict[str, Any] | None,
) -> bool:
    """Whether a tile is completely on disk: its file, or in zarr every time shard of it.

    Both formats store every tile, an empty one included, so a tile that is
    not written is missing.
    """
    if storage_format(storage) != "zarr":
        return tile_path(
            series_root,
            grid,
            metric=metric_id,
            tile_r=tile_r,
            tile_c=tile_c,
            ext=clmtile_ext(storage),
        ).exists()
    zdir = zarr_tiles.zarr_dir(metric_root(series_root, grid, metric_id))
    meta_path = zdir / "zarr.json"
    if not meta_path.exists():
        return False
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    shape = meta["shape"]
    if len(shape) == 2:
        return (zdir / "c" / str(tile_r) / str(tile_c)).is_file()
    st = int(meta["chunk_grid"]["configuration"]["chunk_shape"][0])
    return all(
        (zdir / "c" / str(k) / str(tile_r) / str(tile_c)).is_file()
        for k in range(-(-int(shape[0]) // st))
    )


def _series_length(
    series_root: str | Path,
    grid: GridSpec,
    metric_id: str,
    storage: dict[str, Any] | None,
) -> int | None:
    """Time steps per cell, 0 for a scalar metric; None when the metric has no tiles."""
    if storage_format(storage) == "zarr":
        meta_path = (
            zarr_tiles.zarr_dir(metric_root(series_root, grid, metric_id)) / "zarr.json"
        )
        if not meta_path.exists():
            return None
        shape = json.loads(meta_path.read_text(encoding="utf-8"))["shape"]
        return int(shape[0]) if len(shape) == 3 else 0
    zdir = metric_root(series_root, grid, metric_id) / f"z{int(grid.tile_size)}"
    for p in sorted(zdir.glob(f"r*_c*{clmtile_ext(storage)}")):
        hdr, _ = read_tile_array(p)
        return max(int(hdr.nyears), 0)
    return None


def metric_ntime(
    series_root: str | Path,
    grid: GridSpec,
    metric_id: str,
    storage: dict[str, Any] | None,
) -> int | None:
    """Time steps per cell (1 for a scalar metric); None when the metric has no tiles."""
    n = _series_length(series_root, grid, metric_id, storage)
    return None if n is None else (n or 1)


class ClmtileWriter:
    """The old format behind the same exists/write interface as ZarrTileWriter."""

    def __init__(
        self,
        out_root: str | Path,
        grid: GridSpec,
        metric_id: str,
        *,
        ntime: int,
        dtype: np.dtype,
        storage: dict[str, Any] | None,
    ) -> None:
        self.out_root = Path(out_root)
        self.grid = grid
        self.metric_id = metric_id
        self.ntime = int(ntime)
        self.dtype = np.dtype(dtype)
        self.ext = clmtile_ext(storage)
        self.level = int(((storage or {}).get("compression") or {}).get("level", 10))

    def path(self, tile_r: int, tile_c: int) -> Path:
        return tile_path(
            self.out_root,
            self.grid,
            metric=self.metric_id,
            tile_r=tile_r,
            tile_c=tile_c,
            ext=self.ext,
        )

    def exists(self, tile_r: int, tile_c: int) -> bool:
        return self.path(tile_r, tile_c).exists()

    def write(self, tile_r: int, tile_c: int, tile: np.ndarray, **_: Any) -> None:
        write_tile(
            self.path(tile_r, tile_c),
            tile,
            dtype=self.dtype,
            nyears=self.ntime,
            tile_h=self.grid.tile_size,
            tile_w=self.grid.tile_size,
            compress_level=self.level,
        )


def open_tile_writer(
    out_root: str | Path,
    grid: GridSpec,
    metric_id: str,
    *,
    ntime: int,
    dtype: np.dtype,
    storage: dict[str, Any] | None,
    time_axis: str | None,
    resume: bool,
) -> ClmtileWriter | zarr_tiles.ZarrTileWriter:
    """A writer for one metric's tiles, in the format its registry entry asks for.

    ``ntime`` = 0 for a scalar metric. Both writers take the padded tiles the
    packager builds; the zarr one also needs the fill value used for missing
    data (pass it to ``write`` as ``fill=``).
    """
    if storage_format(storage) == "zarr":
        return zarr_tiles.ZarrTileWriter(
            metric_root(out_root, grid, metric_id),
            grid=grid,
            ntime=ntime,
            encoding=zarr_tiles.Encoding.from_storage(storage),
            shard_time=zarr_tiles.shard_time_for(storage, time_axis, ntime),
            resume=resume,
        )
    return ClmtileWriter(
        out_root, grid, metric_id, ntime=ntime, dtype=dtype, storage=storage
    )


def read_metric_tile(
    series_root: str | Path,
    grid: GridSpec,
    metric_id: str,
    tile_r: int,
    tile_c: int,
    storage: dict[str, Any] | None,
) -> np.ndarray:
    """One whole tile, decoded, as the old format returns it.

    (tile, tile) for a scalar metric, (tile, tile, ntime) for a series, NaN
    beyond the grid. Every tile is stored, so FileNotFoundError when it is not
    on disk.
    """
    root = metric_root(series_root, grid, metric_id)
    if storage_format(storage) == "zarr":
        zdir = zarr_tiles.zarr_dir(root)
        if not (zdir / "zarr.json").exists():
            raise FileNotFoundError(f"Missing zarr array: {zdir}")
        if not tile_written(series_root, grid, metric_id, tile_r, tile_c, storage):
            raise FileNotFoundError(
                f"Missing source tile: {metric_id} r{tile_r} c{tile_c} in {zdir}"
            )
        return zarr_tiles.read_tile(root, tile_r, tile_c, tile_size=grid.tile_size)
    p = tile_path(
        series_root,
        grid,
        metric=metric_id,
        tile_r=tile_r,
        tile_c=tile_c,
        ext=clmtile_ext(storage),
    )
    if not p.exists():
        raise FileNotFoundError(f"Missing source tile: {p}")
    _hdr, arr = read_tile_array(p)
    return arr
