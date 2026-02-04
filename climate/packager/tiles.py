from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

import numpy as np

from climate.tiles.layout import GridSpec, tile_counts, tile_path
from climate.tiles.spec import write_tile


def normalize_missing_value(missing: object, dtype: np.dtype) -> object:
    """Normalize missing value for tile padding based on dtype."""
    dtype = np.dtype(dtype)
    if missing is None:
        if np.issubdtype(dtype, np.floating):
            return np.nan
        return dtype.type(0)
    if isinstance(missing, str):
        if missing.lower() == "nan":
            return np.nan
        raise ValueError(f"Unsupported string missing value: {missing}")
    return dtype.type(missing)


def write_axis_json(
    out_root: Path,
    grid: GridSpec,
    metric_id: str,
    axis_name: str,
    axis_values: Sequence[object],
) -> Path:
    path = out_root / grid.grid_id / metric_id / "time" / f"{axis_name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(list(axis_values), indent=2) + "\n", encoding="utf-8")
    return path


def _series_to_grid_time(
    series: np.ndarray, grid: GridSpec, axis_len: int
) -> np.ndarray:
    arr = np.asarray(series)
    if axis_len == 0:
        if arr.shape != (grid.nlat, grid.nlon):
            raise ValueError(
                f"Expected scalar series shape {(grid.nlat, grid.nlon)}, got {arr.shape}"
            )
        return arr

    if arr.shape == (grid.nlat, grid.nlon, axis_len):
        return arr
    if arr.shape == (axis_len, grid.nlat, grid.nlon):
        return np.transpose(arr, (1, 2, 0))

    raise ValueError(
        "Expected series shape (nlat, nlon, ntime) or (ntime, nlat, nlon), "
        f"got {arr.shape}"
    )


def write_series_tiles(
    *,
    out_root: Path,
    grid: GridSpec,
    metric_id: str,
    axis_values: Sequence[object],
    series: np.ndarray,
    dtype: np.dtype | str,
    missing: object,
    compression: dict | None = None,
    resume: bool = False,
) -> int:
    """Write a full series into tiled files using climate.tiles.spec.write_tile."""
    dtype = np.dtype(dtype)
    axis_len = len(axis_values)
    arr = _series_to_grid_time(series, grid, axis_len)
    fill_value = normalize_missing_value(missing, dtype)

    codec = "zstd"
    level = 10
    if compression is not None:
        codec = compression.get("codec", codec)
        level = int(compression.get("level", level))

    if codec == "zstd":
        ext = ".bin.zst"
    elif codec == "none":
        ext = ".bin"
    else:
        raise ValueError(f"Unsupported compression codec: {codec}")

    ntr, ntc = tile_counts(grid)
    written = 0
    for tr in range(ntr):
        i_lat0 = tr * grid.tile_size
        valid_h = min(grid.tile_size, grid.nlat - i_lat0)
        for tc in range(ntc):
            i_lon0 = tc * grid.tile_size
            valid_w = min(grid.tile_size, grid.nlon - i_lon0)

            if axis_len == 0:
                tile = np.full(
                    (grid.tile_size, grid.tile_size), fill_value, dtype=dtype
                )
                tile[:valid_h, :valid_w] = np.asarray(
                    arr[i_lat0 : i_lat0 + valid_h, i_lon0 : i_lon0 + valid_w],
                    dtype=dtype,
                )
            else:
                tile = np.full(
                    (grid.tile_size, grid.tile_size, axis_len),
                    fill_value,
                    dtype=dtype,
                )
                tile[:valid_h, :valid_w, :] = np.asarray(
                    arr[
                        i_lat0 : i_lat0 + valid_h,
                        i_lon0 : i_lon0 + valid_w,
                        :,
                    ],
                    dtype=dtype,
                )

            out_path = tile_path(
                out_root, grid, metric=metric_id, tile_r=tr, tile_c=tc, ext=ext
            )
            if resume and out_path.exists():
                continue

            write_tile(
                out_path,
                tile,
                dtype=dtype,
                nyears=axis_len,
                tile_h=grid.tile_size,
                tile_w=grid.tile_size,
                compress_level=level,
            )
            written += 1

    return written
