from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
import re
import signal
import shutil
import threading
import zipfile
from pathlib import Path
import time
from typing import Any, Iterable
from concurrent.futures import ProcessPoolExecutor, as_completed, wait, FIRST_COMPLETED

import numpy as np
import xarray as xr

from climate.datasets.products.era5 import (
    ERA5_MONTHLY_MEANS_DATASET,
    ERA5_DAILY_STATS_DATASET,
    build_monthly_means_request,
    build_daily_stats_request,
)
from climate.datasets.sources.cds import retrieve
from climate.packager.maps import package_maps
from climate.packager.tiles import normalize_missing_value, write_axis_json
from climate.registry.maps import (
    DEFAULT_MAPS_PATH,
    DEFAULT_MAPS_SCHEMA_PATH,
    load_maps,
    validate_maps_against_metrics,
)
from climate.registry.metrics import (
    DEFAULT_METRICS_PATH,
    DEFAULT_SCHEMA_PATH,
    DEFAULT_DATASETS_PATH,
    load_metrics,
)
from climate.registry.panels import (
    DEFAULT_PANELS_PATH,
    DEFAULT_PANELS_SCHEMA_PATH,
    load_panels,
    validate_panels_against_maps,
    validate_panels_against_metrics,
)
from climate.tiles.layout import GridSpec, cell_center_latlon, tile_counts, tile_path
from climate.tiles.spec import write_tile
from climate.datasets.products.erddap_specs import ERDDAP_DATASETS
from climate.datasets.sources.erddap import build_griddap_query, make_griddap_url
from climate.datasets.sources.http import download_to
from climate.datasets.derive.hot_days import hot_days_per_year_xr
from climate.datasets.derive.time_agg import (
    find_time_dim,
    annual_mean_from_monthly,
    annual_mean_from_daily,
    monthly_mean_from_daily,
    climatology_mean_from_monthly,
)


@dataclass(frozen=True)
class TileRange:
    tile_r0: int
    tile_r1: int
    tile_c0: int
    tile_c1: int


_REGRID_DEBUG_SEEN: set[str] = set()
_REGRID_DEBUG_SEEN_LOCK = threading.Lock()


def _grid_from_id(grid_id: str, *, tile_size: int) -> GridSpec:
    if grid_id == "global_0p25":
        return GridSpec.global_0p25(tile_size=tile_size)
    raise ValueError(f"Unsupported grid_id: {grid_id}")


def _find_lat_lon_names(ds: xr.Dataset) -> tuple[str, str]:
    for lat_name in ("latitude", "lat", "y"):
        if lat_name in ds.coords:
            break
    else:
        raise RuntimeError(f"Could not find latitude coord in {list(ds.coords)}")

    for lon_name in ("longitude", "lon", "x"):
        if lon_name in ds.coords:
            break
    else:
        raise RuntimeError(f"Could not find longitude coord in {list(ds.coords)}")

    return lat_name, lon_name


def _data_var_aliases(name: str) -> list[str]:
    aliases = {
        "near_surface_air_temperature": ["tas"],
        "2m_temperature": ["t2m"],
    }
    return aliases.get(name, [])


def _pick_data_var(ds: xr.Dataset, *, preferred: str | None = None) -> str:
    vars_ = list(ds.data_vars)
    if not vars_:
        raise RuntimeError("Dataset has no data_vars")

    preferred_name = preferred if isinstance(preferred, str) and preferred else None
    if preferred_name:
        if preferred_name in ds.data_vars:
            return preferred_name
        for alias in _data_var_aliases(preferred_name):
            if alias in ds.data_vars:
                return alias

    non_bounds = [
        v
        for v in vars_
        if not (v.endswith("_bnds") or v.endswith("_bounds") or v == "bounds")
    ]
    if len(non_bounds) == 1:
        return non_bounds[0]
    if len(vars_) == 1:
        return vars_[0]
    raise RuntimeError(
        f"Could not choose a single data var (preferred={preferred_name!r}); got {vars_}"
    )


def _open_dataset_dask(
    path: Path, *, dask_chunk_lat: int, dask_chunk_lon: int
) -> xr.Dataset:
    # Avoid chunks="auto": some CDS/CMIP files expose object/cftime arrays and
    # xarray+dask can fail during auto size estimation/rechunking.
    ds = xr.open_dataset(path, chunks={})
    lat_name, lon_name = _find_lat_lon_names(ds)
    if lat_name in ds.dims and lon_name in ds.dims:
        ds = ds.chunk({lat_name: int(dask_chunk_lat), lon_name: int(dask_chunk_lon)})
    return ds


def _normalize_cds_payload_to_netcdf(path: Path) -> Path:
    """
    CDS can return ZIP payloads even when target filename ends with .nc.
    If so, extract the first .nc member and replace `path` with it.
    """
    if not path.exists():
        return path
    with path.open("rb") as f:
        sig = f.read(4)
    if sig != b"PK\x03\x04":
        return path

    with zipfile.ZipFile(path, "r") as zf:
        members = [m for m in zf.namelist() if m.lower().endswith(".nc")]
        if not members:
            members = zf.namelist()
        if not members:
            raise RuntimeError(f"ZIP payload has no members: {path}")
        member = members[0]
        tmp = path.with_suffix(path.suffix + ".unzipped.tmp")
        with zf.open(member) as src, tmp.open("wb") as dst:
            dst.write(src.read())
    tmp.replace(path)
    return path


def _compute_tiles_from_cds_downloads(
    *,
    dataset: str,
    agg: str,
    postprocess: list[object] | None,
    params: dict[str, Any],
    downloads: list[tuple[list[int], list[Path]]],
    out_root: Path,
    grid: GridSpec,
    metric_id: str,
    tile_range: TileRange,
    dtype: np.dtype,
    missing: object,
    compression: dict | None,
    debug: bool,
    resume: bool,
    dask_enabled: bool,
    dask_chunk_lat: int,
    dask_chunk_lon: int,
    output_years: list[int],
    time_axis: str,
    data_var_hint: str | None = None,
) -> int:
    agg_fn = _agg_map().get(agg)
    if agg_fn is None:
        raise ValueError(f"Unsupported aggregator: {agg}")
    da_parts: list[xr.DataArray] = []

    if dataset == ERA5_DAILY_STATS_DATASET and agg == "hot_days_per_year":
        daily_parts_all: list[xr.DataArray] = []
        for years_part, paths in downloads:
            for dl_path in paths:
                if dask_enabled:
                    ds = _open_dataset_dask(
                        dl_path,
                        dask_chunk_lat=dask_chunk_lat,
                        dask_chunk_lon=dask_chunk_lon,
                    )
                else:
                    ds = xr.open_dataset(dl_path)
                try:
                    var_name = _pick_data_var(ds, preferred=data_var_hint)
                    da = ds[var_name]
                    da = _apply_postprocess(da, postprocess)
                    da = _maybe_regrid_to_metric_grid(
                        da=da,
                        grid=grid,
                        tile_range=tile_range,
                        params=params,
                        debug=debug,
                        label=f"cds:{metric_id}:{dl_path.name}",
                        metric_id=metric_id,
                    )
                    daily_parts_all.append(da)
                finally:
                    ds.close()
        if debug:
            print("[cds] Concatenating daily parts")
        da_daily = xr.concat(daily_parts_all, dim=find_time_dim(daily_parts_all[0]))
        da_daily = da_daily.sortby(find_time_dim(da_daily))
        if debug:
            print(f"[cds] Aggregating {time_axis} (daily source, agg={agg})")
        da_parts.append(agg_fn(da_daily, params))
    else:
        if _is_cds_monthly_dataset(dataset, params) and agg == "cmip_multi_model_offset_from_monthly":
            monthly_parts_all: list[xr.DataArray] = []
            for _years_part, paths in downloads:
                dl_path = paths[0]
                if dask_enabled:
                    ds = _open_dataset_dask(
                        dl_path,
                        dask_chunk_lat=dask_chunk_lat,
                        dask_chunk_lon=dask_chunk_lon,
                    )
                else:
                    ds = xr.open_dataset(dl_path)
                try:
                    var_name = _pick_data_var(ds, preferred=data_var_hint)
                    da = ds[var_name]
                    da = _apply_postprocess(da, postprocess)
                    da = _maybe_regrid_to_metric_grid(
                        da=da,
                        grid=grid,
                        tile_range=tile_range,
                        params=params,
                        debug=debug,
                        label=f"cds:{metric_id}:{dl_path.name}",
                        metric_id=metric_id,
                    )
                    monthly_parts_all.append(da)
                finally:
                    ds.close()
            if debug:
                print("[cds] Concatenating monthly parts for cmip_multi_model_offset_from_monthly")
            da_monthly = xr.concat(
                monthly_parts_all,
                dim=find_time_dim(monthly_parts_all[0]),
            ).sortby(find_time_dim(monthly_parts_all[0]))
            da_parts.append(agg_fn(da_monthly, params))
        else:
            for years_part, paths in downloads:
                if _is_cds_monthly_dataset(dataset, params):
                    dl_path = paths[0]
                    if dask_enabled:
                        ds = _open_dataset_dask(
                            dl_path,
                            dask_chunk_lat=dask_chunk_lat,
                            dask_chunk_lon=dask_chunk_lon,
                        )
                    else:
                        ds = xr.open_dataset(dl_path)
                    try:
                        var_name = _pick_data_var(ds, preferred=data_var_hint)
                        da = ds[var_name]
                        da = _apply_postprocess(da, postprocess)
                        da = _maybe_regrid_to_metric_grid(
                            da=da,
                            grid=grid,
                            tile_range=tile_range,
                            params=params,
                            debug=debug,
                            label=f"cds:{metric_id}:{dl_path.name}",
                            metric_id=metric_id,
                        )
                        if debug:
                            print(
                                f"[cds] Aggregating {time_axis} (monthly source, agg={agg}) "
                                f"for years {years_part[0]}..{years_part[-1]}"
                            )
                        da_out = agg_fn(da, params)
                        da_out = _select_years_if_present(da_out, years_part)
                        da_parts.append(da_out)
                    finally:
                        ds.close()
                else:
                    daily_parts: list[xr.DataArray] = []
                    for dl_path in paths:
                        if dask_enabled:
                            ds = _open_dataset_dask(
                                dl_path,
                                dask_chunk_lat=dask_chunk_lat,
                                dask_chunk_lon=dask_chunk_lon,
                            )
                        else:
                            ds = xr.open_dataset(dl_path)
                        try:
                            var_name = _pick_data_var(ds, preferred=data_var_hint)
                            da = ds[var_name]
                            da = _apply_postprocess(da, postprocess)
                            da = _maybe_regrid_to_metric_grid(
                                da=da,
                                grid=grid,
                                tile_range=tile_range,
                                params=params,
                                debug=debug,
                                label=f"cds:{metric_id}:{dl_path.name}",
                                metric_id=metric_id,
                            )
                            daily_parts.append(da)
                        finally:
                            ds.close()

                    if debug:
                        print(
                            f"[cds] Concatenating daily parts for years {years_part[0]}..{years_part[-1]}"
                        )
                    da_daily = xr.concat(daily_parts, dim=find_time_dim(daily_parts[0]))
                    da_daily = da_daily.sortby(find_time_dim(da_daily))
                    if debug:
                        print(
                            f"[cds] Aggregating {time_axis} (daily source, agg={agg}) "
                            f"for years {years_part[0]}..{years_part[-1]}"
                        )
                    da_out = agg_fn(da_daily, params)
                    da_out = _select_years_if_present(da_out, years_part)
                    da_parts.append(da_out)

    written = _concat_and_write_time_tiles(
        da_parts=da_parts,
        output_years=output_years,
        time_axis=time_axis,
        out_root=out_root,
        grid=grid,
        metric_id=metric_id,
        tile_range=tile_range,
        dtype=dtype,
        missing=missing,
        compression=compression,
        debug=debug,
        resume=resume,
    )
    print(
        f"[cds] Finished writing tiles for metric={metric_id} "
        f"batch r{tile_range.tile_r0}-{tile_range.tile_r1} "
        f"c{tile_range.tile_c0}-{tile_range.tile_c1}"
    )
    return written


def _compute_tiles_from_erddap_downloads(
    *,
    agg: str,
    postprocess: list[object] | None,
    params: dict[str, Any],
    downloads: list[tuple[list[int], list[Path]]],
    out_root: Path,
    grid: GridSpec,
    metric_id: str,
    tile_range: TileRange,
    dtype: np.dtype,
    missing: object,
    compression: dict | None,
    debug: bool,
    resume: bool,
    dask_enabled: bool,
    dask_chunk_lat: int,
    dask_chunk_lon: int,
    output_years: list[int],
    time_axis: str,
    data_var_hint: str | None = None,
) -> int:
    agg_fn = _agg_map().get(agg)
    if agg_fn is None:
        raise ValueError(f"Unsupported aggregator: {agg}")
    da_parts: list[xr.DataArray] = []

    if agg == "hot_days_per_year":
        daily_parts_all: list[xr.DataArray] = []
        for years_part, paths in downloads:
            for dl_path in paths:
                if dask_enabled:
                    ds = _open_dataset_dask(
                        dl_path,
                        dask_chunk_lat=dask_chunk_lat,
                        dask_chunk_lon=dask_chunk_lon,
                    )
                else:
                    ds = xr.open_dataset(dl_path)
                try:
                    var_name = _pick_data_var(ds, preferred=data_var_hint)
                    da = ds[var_name]
                    if "zlev" in da.dims:
                        da = da.sel(zlev=0.0, drop=True)
                    da = _apply_postprocess(da, postprocess)
                    da = _maybe_regrid_to_metric_grid(
                        da=da,
                        grid=grid,
                        tile_range=tile_range,
                        params=params,
                        debug=debug,
                        label=f"erddap:{metric_id}:{dl_path.name}",
                        metric_id=metric_id,
                    )
                    daily_parts_all.append(da)
                finally:
                    ds.close()
        if debug:
            print("[erddap] Concatenating daily parts")
        da_daily = xr.concat(daily_parts_all, dim=find_time_dim(daily_parts_all[0]))
        da_daily = da_daily.sortby(find_time_dim(da_daily))
        if debug:
            print(f"[erddap] Aggregating {time_axis} (agg={agg})")
        da_parts.append(agg_fn(da_daily, params))
    else:
        for years_part, paths in downloads:
            dl_path = paths[0]
            if dask_enabled:
                ds = _open_dataset_dask(
                    dl_path,
                    dask_chunk_lat=dask_chunk_lat,
                    dask_chunk_lon=dask_chunk_lon,
                )
            else:
                ds = xr.open_dataset(dl_path)
            try:
                var_name = _pick_data_var(ds, preferred=data_var_hint)
                da = ds[var_name]
                if "zlev" in da.dims:
                    da = da.sel(zlev=0.0, drop=True)
                da = _apply_postprocess(da, postprocess)
                da = _maybe_regrid_to_metric_grid(
                    da=da,
                    grid=grid,
                    tile_range=tile_range,
                    params=params,
                    debug=debug,
                    label=f"erddap:{metric_id}:{dl_path.name}",
                    metric_id=metric_id,
                )
                if debug:
                    print(
                        f"[erddap] Aggregating {time_axis} (agg={agg}) "
                        f"for years {years_part[0]}..{years_part[-1]}"
                    )
                da_out = agg_fn(da, params)
                da_out = _select_years_if_present(da_out, years_part)
                da_parts.append(da_out)
            finally:
                ds.close()

    written = _concat_and_write_time_tiles(
        da_parts=da_parts,
        output_years=output_years,
        time_axis=time_axis,
        out_root=out_root,
        grid=grid,
        metric_id=metric_id,
        tile_range=tile_range,
        dtype=dtype,
        missing=missing,
        compression=compression,
        debug=debug,
        resume=resume,
    )
    print(
        f"[erddap] Finished writing tiles for metric={metric_id} "
        f"batch r{tile_range.tile_r0}-{tile_range.tile_r1} "
        f"c{tile_range.tile_c0}-{tile_range.tile_c1}"
    )
    return written


def _compute_tile_bbox_clamped(
    grid: GridSpec, tile_r: int, tile_c: int
) -> tuple[list[float], list[float], tuple[float, float, float, float], int, int]:
    ts = grid.tile_size
    i_lat0 = tile_r * ts
    i_lon0 = tile_c * ts

    valid_h = max(0, min(ts, grid.nlat - i_lat0))
    valid_w = max(0, min(ts, grid.nlon - i_lon0))
    if valid_h <= 0 or valid_w <= 0:
        raise RuntimeError(
            f"Tile (r={tile_r}, c={tile_c}) is outside grid: "
            f"i_lat0={i_lat0}, i_lon0={i_lon0}, grid=({grid.nlat},{grid.nlon})"
        )

    lats: list[float] = []
    lons: list[float] = []
    for j in range(valid_h):
        latc, _ = cell_center_latlon(i_lat0 + j, i_lon0, grid)
        lats.append(float(latc))
    for j in range(valid_w):
        _, lonc = cell_center_latlon(i_lat0, i_lon0 + j, grid)
        lons.append(float(lonc))

    north = lats[0]
    south = lats[-1]
    west = lons[0]
    east = lons[-1]
    area = _clamp_area((north, west, south, east))
    return lats, lons, area, valid_h, valid_w


def _compute_batch_bbox(
    grid: GridSpec, tile_r0: int, tile_c0: int, tile_r1: int, tile_c1: int
) -> tuple[tuple[float, float, float, float], int, int]:
    ts = grid.tile_size
    i_lat0 = tile_r0 * ts
    i_lon0 = tile_c0 * ts

    i_lat1 = min((tile_r1 + 1) * ts - 1, grid.nlat - 1)
    i_lon1 = min((tile_c1 + 1) * ts - 1, grid.nlon - 1)

    total_h = i_lat1 - i_lat0 + 1
    total_w = i_lon1 - i_lon0 + 1
    if total_h <= 0 or total_w <= 0:
        raise RuntimeError(
            f"Batch tiles outside grid: r{tile_r0}-{tile_r1}, c{tile_c0}-{tile_c1}"
        )

    north, _ = cell_center_latlon(i_lat0, i_lon0, grid)
    south, _ = cell_center_latlon(i_lat1, i_lon0, grid)
    _, west = cell_center_latlon(i_lat0, i_lon0, grid)
    _, east = cell_center_latlon(i_lat0, i_lon1, grid)

    area = _clamp_area((float(north), float(west), float(south), float(east)))
    return (area, int(total_h), int(total_w))


def _clamp_area(
    area: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    north, west, south, east = area

    north = min(90.0, max(-90.0, float(north)))
    south = min(90.0, max(-90.0, float(south)))

    if south > north:
        south, north = north, south

    west = min(180.0, max(-180.0, float(west)))
    east = min(180.0, max(-180.0, float(east)))

    return (north, west, south, east)


def _iter_batches(tile_range: TileRange, batch_tiles: int) -> Iterable[TileRange]:
    bt = int(batch_tiles)
    if bt <= 0:
        raise ValueError("batch_tiles must be >= 1")
    for rr0 in range(tile_range.tile_r0, tile_range.tile_r1 + 1, bt):
        rr1 = min(rr0 + bt - 1, tile_range.tile_r1)
        for cc0 in range(tile_range.tile_c0, tile_range.tile_c1 + 1, bt):
            cc1 = min(cc0 + bt - 1, tile_range.tile_c1)
            yield TileRange(rr0, rr1, cc0, cc1)


def _apply_postprocess(da: xr.DataArray, steps: list[object] | None) -> xr.DataArray:
    if not steps:
        return da

    for step in steps:
        if isinstance(step, str):
            fn = step
            params = {}
        elif isinstance(step, dict):
            fn = step.get("fn")
            params = step.get("params", {})
        else:
            raise ValueError(f"Unsupported postprocess step: {step}")

        if fn == "k_to_c":
            da = da - 273.15
        else:
            raise ValueError(f"Unsupported postprocess fn: {fn} params={params}")

    return da


def _batch_target_lat_lon(grid: GridSpec, tile_range: TileRange) -> tuple[np.ndarray, np.ndarray]:
    ts = grid.tile_size
    i_lat0 = tile_range.tile_r0 * ts
    i_lon0 = tile_range.tile_c0 * ts
    i_lat1 = min((tile_range.tile_r1 + 1) * ts - 1, grid.nlat - 1)
    i_lon1 = min((tile_range.tile_c1 + 1) * ts - 1, grid.nlon - 1)

    lat_vals = np.asarray(
        [cell_center_latlon(i, i_lon0, grid)[0] for i in range(i_lat0, i_lat1 + 1)],
        dtype=np.float64,
    )
    lon_vals = np.asarray(
        [cell_center_latlon(i_lat0, j, grid)[1] for j in range(i_lon0, i_lon1 + 1)],
        dtype=np.float64,
    )
    return lat_vals, lon_vals


def _normalize_lon_to_180(da: xr.DataArray, lon_name: str) -> xr.DataArray:
    lon_raw = np.asarray(da[lon_name].values, dtype=np.float64)
    lon_norm = ((lon_raw + 180.0) % 360.0) - 180.0
    if np.any(np.abs(lon_raw - lon_norm) > 1e-10):
        da = da.assign_coords({lon_name: lon_norm})
    return da.sortby(lon_name)


def _maybe_regrid_to_metric_grid(
    *,
    da: xr.DataArray,
    grid: GridSpec,
    tile_range: TileRange,
    params: dict[str, Any] | None,
    debug: bool,
    label: str,
    metric_id: str,
) -> xr.DataArray:
    p = params or {}
    if not bool(p.get("regrid_to_metric_grid", False)):
        return da

    method_raw = str(p.get("regrid_method", "bilinear")).lower()
    if method_raw == "bilinear":
        interp_method = "linear"
    elif method_raw == "nearest":
        interp_method = "nearest"
    else:
        raise ValueError(f"Unsupported regrid_method: {method_raw}")

    lat_name, lon_name = _find_lat_lon_names(da.to_dataset(name="v"))
    if lat_name not in da.dims or lon_name not in da.dims:
        raise RuntimeError(
            f"Cannot regrid {label}: expected lat/lon dimensions in {da.dims}"
        )

    da_src = da.sortby(lat_name)
    da_src = _normalize_lon_to_180(da_src, lon_name)
    # Some CMIP files use object/cftime coordinates on time; xarray+dask interpolation can
    # raise on object dtype rechunking. Regridding batch chunks in-memory is robust here.
    if bool((params or {}).get("regrid_in_memory", True)):
        da_src = da_src.load()

    target_lat, target_lon = _batch_target_lat_lon(grid, tile_range)
    if target_lat.size == 0 or target_lon.size == 0:
        raise RuntimeError(
            f"Cannot regrid {label}: empty target coordinates for batch "
            f"r{tile_range.tile_r0}-{tile_range.tile_r1} c{tile_range.tile_c0}-{tile_range.tile_c1}"
        )

    if debug:
        with _REGRID_DEBUG_SEEN_LOCK:
            first_for_metric = metric_id not in _REGRID_DEBUG_SEEN
            if first_for_metric:
                _REGRID_DEBUG_SEEN.add(metric_id)
        if first_for_metric:
            print(
                f"[regrid] metric={metric_id} method={method_raw} "
                f"src_grid=({da_src.sizes.get(lat_name)} lat x {da_src.sizes.get(lon_name)} lon) "
                f"-> dst_grid=({target_lat.size} lat x {target_lon.size} lon)"
            )

    return da_src.interp(
        {lat_name: target_lat, lon_name: target_lon},
        method=interp_method,
    )


def _append_yearly_part(
    *,
    da: xr.DataArray,
    agg_fn: callable,
    params: dict | None,
    years_part: list[int],
    da_parts: list[xr.DataArray],
    years_parts: list[int],
) -> None:
    da_ann = agg_fn(da, params or {})
    da_ann = da_ann.sel(year=years_part)
    da_parts.append(da_ann)
    years_parts.extend(years_part)


def _select_years_if_present(da_out: xr.DataArray, years_part: list[int]) -> xr.DataArray:
    if "year" not in da_out.dims:
        return da_out
    if not years_part:
        return da_out
    try:
        years_avail = [int(v) for v in np.asarray(da_out["year"].values).tolist()]
    except Exception:
        return da_out

    wanted = set(int(y) for y in years_part)
    keep = [y for y in years_avail if y in wanted]
    if not keep:
        # Some aggregators intentionally collapse to one label year (e.g., climatology baseline).
        return da_out
    return da_out.sel(year=keep)


def _concat_and_write_time_tiles(
    *,
    da_parts: list[xr.DataArray],
    output_years: list[int],
    time_axis: str,
    out_root: Path,
    grid: GridSpec,
    metric_id: str,
    tile_range: TileRange,
    dtype: str,
    missing: float,
    compression: dict | None,
    debug: bool,
    resume: bool,
) -> int:
    if not da_parts:
        raise RuntimeError(f"No data blocks for metric={metric_id}")

    if time_axis == "yearly":
        da = xr.concat(da_parts, dim="year").sortby("year")
        da = _select_years_if_present(da, output_years)
        axis_values: list[object] = [int(v) for v in da["year"].values.tolist()]
        return _tiles_from_time_da(
            da=da,
            axis_values=axis_values,
            time_dim="year",
            axis_name="yearly",
            out_root=out_root,
            grid=grid,
            metric_id=metric_id,
            tile_range=tile_range,
            dtype=dtype,
            missing=missing,
            compression=compression,
            debug=debug,
            resume=resume,
        )

    time_dim = find_time_dim(da_parts[0])
    da = xr.concat(da_parts, dim=time_dim).sortby(time_dim)
    years_set = set(int(y) for y in output_years)
    da = da.where(da[time_dim].dt.year.isin(sorted(years_set)), drop=True)
    if da.sizes.get(time_dim, 0) == 0:
        raise RuntimeError(
            f"No data points remain for {metric_id} after applying analysis years "
            f"{output_years[0]}..{output_years[-1]}"
        )

    if time_axis == "monthly":
        axis_values = [
            np.datetime_as_string(np.datetime64(v), unit="D")[:7]
            for v in da[time_dim].values
        ]
        axis_name = "monthly"
    elif time_axis == "daily":
        axis_values = [
            np.datetime_as_string(np.datetime64(v), unit="D")
            for v in da[time_dim].values
        ]
        axis_name = "daily"
    else:
        raise ValueError(f"Unsupported time_axis for writing tiles: {time_axis}")

    return _tiles_from_time_da(
        da=da,
        axis_values=axis_values,
        time_dim=time_dim,
        axis_name=axis_name,
        out_root=out_root,
        grid=grid,
        metric_id=metric_id,
        tile_range=tile_range,
        dtype=dtype,
        missing=missing,
        compression=compression,
        debug=debug,
        resume=resume,
    )


def _agg_map() -> dict[str, callable]:
    return {
        "identity": lambda da, _params: da,
        "annual_mean_from_monthly": lambda da, _params: annual_mean_from_monthly(da),
        "monthly_mean_from_daily": lambda da, _params: monthly_mean_from_daily(da),
        "annual_mean_from_daily": lambda da, _params: annual_mean_from_daily(da),
        "cmip_multi_model_offset_from_monthly": lambda da, params: _cmip_multi_model_offset_from_monthly(
            da,
            params,
        ),
        "climatology_mean_from_monthly": lambda da, params: climatology_mean_from_monthly(
            da,
            start_year=int((params or {}).get("start_year")),
            end_year=int((params or {}).get("end_year")),
            label_year=(
                int((params or {}).get("label_year"))
                if (params or {}).get("label_year") is not None
                else None
            ),
        ),
        "hot_days_per_year": lambda da, params: hot_days_per_year_xr(
            da,
            baseline_years=int((params or {}).get("baseline_years", 10)),
            percentile=float((params or {}).get("percentile", 90)),
            debug=bool((params or {}).get("_debug", False)),
        ),
}


def _cmip_multi_model_offset_from_monthly(
    da: xr.DataArray,
    params: dict[str, Any] | None,
) -> xr.DataArray:
    p = params or {}
    pre_start_year = int(p.get("preindustrial_start_year", 1850))
    pre_end_year = int(p.get("preindustrial_end_year", 1900))
    ref_start_year = int(p.get("ref_start_year", 1979))
    ref_end_year = int(p.get("ref_end_year", 2000))
    label_year = int(p.get("label_year", ref_end_year))

    tname = find_time_dim(da)
    if not np.issubdtype(da[tname].dtype, np.datetime64):
        da = xr.decode_cf(da.to_dataset(name="v"))["v"]

    lat_name, lon_name = _find_lat_lon_names(da.to_dataset(name="v"))
    keep_dims = {tname, lat_name, lon_name}
    extra_dims = [dim for dim in da.dims if dim not in keep_dims]
    if extra_dims:
        da = da.mean(dim=extra_dims, skipna=True, keep_attrs=False)

    preindustrial = climatology_mean_from_monthly(
        da,
        start_year=pre_start_year,
        end_year=pre_end_year,
        label_year=label_year,
    )
    reference = climatology_mean_from_monthly(
        da,
        start_year=ref_start_year,
        end_year=ref_end_year,
        label_year=label_year,
    )
    return reference - preindustrial


def _is_cds_monthly_dataset(dataset: str, params: dict[str, Any] | None) -> bool:
    if dataset == ERA5_MONTHLY_MEANS_DATASET:
        return True
    p = params or {}
    return str(p.get("cds_cadence", "")).lower() == "monthly"


def _year_blocks(
    start_year: int,
    end_year: int,
    block_years: int,
    *,
    dataset_start: str | None,
) -> list[tuple[str, str, list[int]]]:
    blocks: list[tuple[str, str, list[int]]] = []
    y = int(start_year)
    block_years = max(1, int(block_years))
    dataset_start_year = int(dataset_start[:4]) if dataset_start else None

    while y <= end_year:
        y0 = y
        y1 = min(end_year, y + block_years - 1)
        if dataset_start_year is not None and y1 < dataset_start_year:
            y = y1 + 1
            continue
        start_date = f"{y0}-01-01"
        end_date = f"{y1}-12-31"
        if dataset_start:
            start_date = max(start_date, dataset_start)
        years = [yy for yy in range(y0, y1 + 1) if yy >= (dataset_start_year or yy)]
        if years:
            blocks.append((start_date, end_date, years))
        y = y1 + 1
    return blocks


def _cds_year_blocks_for_metric(
    *,
    agg: str,
    source: dict[str, Any],
    download_start_year: int,
    download_end_year: int,
) -> list[tuple[str, str, list[int]]]:
    if agg == "cmip_multi_model_offset_from_monthly":
        params = source.get("params", {}) or {}
        windows = [
            (
                int(params.get("preindustrial_start_year", 1850)),
                int(params.get("preindustrial_end_year", 1900)),
            ),
            (
                int(params.get("ref_start_year", 1979)),
                int(params.get("ref_end_year", 2000)),
            ),
        ]
        blocks: list[tuple[str, str, list[int]]] = []
        seen: set[tuple[int, int]] = set()
        for w_start, w_end in windows:
            start = max(download_start_year, min(w_start, w_end))
            end = min(download_end_year, max(w_start, w_end))
            if start > end:
                continue
            key = (start, end)
            if key in seen:
                continue
            seen.add(key)
            years = list(range(start, end + 1))
            blocks.append((f"{start}-01-01", f"{end}-12-31", years))
        return blocks

    block_years = int(source.get("block_years", 1))
    return _year_blocks(
        download_start_year,
        download_end_year,
        block_years,
        dataset_start=None,
    )


def _month_blocks(block_months: int) -> list[list[str]]:
    block_months = max(1, int(block_months))
    blocks: list[list[str]] = []
    m = 1
    while m <= 12:
        end_m = min(12, m + block_months - 1)
        blocks.append([f"{mm:02d}" for mm in range(m, end_m + 1)])
        m = end_m + 1
    return blocks


def _parse_year_range(raw: Any) -> tuple[int, int] | None:
    if not isinstance(raw, dict):
        return None
    if "start_year" not in raw or "end_year" not in raw:
        return None
    return (int(raw["start_year"]), int(raw["end_year"]))


def _align_to_dataset_blocks(
    *,
    analysis_start: int,
    analysis_end: int,
    dataset_start: int,
    dataset_end: int,
    block_years: int,
) -> tuple[int, int]:
    block_years = max(1, int(block_years))
    analysis_start = max(dataset_start, analysis_start)
    analysis_end = min(dataset_end, analysis_end)
    offset_start = (analysis_start - dataset_start) // block_years
    offset_end = (analysis_end - dataset_start) // block_years
    download_start = dataset_start + offset_start * block_years
    download_end = dataset_start + offset_end * block_years + (block_years - 1)
    download_end = min(download_end, dataset_end)
    return (download_start, download_end)


def _resolve_year_ranges(
    *,
    source: dict[str, Any],
    cli_start_year: int | None,
    cli_end_year: int | None,
) -> tuple[int, int, int, int]:
    download_range = _parse_year_range(source.get("time_range")) or (1979, 2025)
    analysis_range = (
        _parse_year_range(source.get("_analysis_time_range")) or download_range
    )

    analysis_start = int(cli_start_year) if cli_start_year is not None else analysis_range[0]
    analysis_end = int(cli_end_year) if cli_end_year is not None else analysis_range[1]
    if analysis_start > analysis_end:
        raise ValueError(
            f"Invalid analysis year range: {analysis_start}..{analysis_end}"
        )

    analysis_start = max(download_range[0], analysis_start)
    analysis_end = min(download_range[1], analysis_end)
    if analysis_start > analysis_end:
        raise ValueError(
            f"Analysis range {analysis_start}..{analysis_end} is outside download range "
            f"{download_range[0]}..{download_range[1]}"
        )

    if source.get("_dataset_ref"):
        block_years = int(source.get("block_years", 1))
        download_start, download_end = _align_to_dataset_blocks(
            analysis_start=analysis_start,
            analysis_end=analysis_end,
            dataset_start=download_range[0],
            dataset_end=download_range[1],
            block_years=block_years,
        )
    else:
        download_start, download_end = analysis_start, analysis_end

    return (analysis_start, analysis_end, download_start, download_end)


def _tiles_from_time_da(
    *,
    da: xr.DataArray,
    axis_values: list[object],
    time_dim: str,
    axis_name: str,
    out_root: Path,
    grid: GridSpec,
    metric_id: str,
    tile_range: TileRange,
    dtype: np.dtype,
    missing: object,
    compression: dict | None,
    debug: bool,
    resume: bool,
) -> int:
    axis_len = len(axis_values)
    write_axis_json(out_root, grid, metric_id, axis_name, axis_values)
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

    lat_name, lon_name = _find_lat_lon_names(da.to_dataset(name="v"))
    written = 0
    debug_tiles_printed = 0

    for tr in range(tile_range.tile_r0, tile_range.tile_r1 + 1):
        for tc in range(tile_range.tile_c0, tile_range.tile_c1 + 1):
            lats_expected, lons_expected, _area, valid_h, valid_w = (
                _compute_tile_bbox_clamped(grid, tr, tc)
            )

            tol = grid.deg * 0.51
            da_tile = da.reindex(
                {lat_name: lats_expected, lon_name: lons_expected},
                method="nearest",
                tolerance=tol,
            )

            if debug:
                lat_sel = np.asarray(da_tile[lat_name].values, dtype=np.float64)
                lon_sel = np.asarray(da_tile[lon_name].values, dtype=np.float64)
                lat_exp = np.asarray(lats_expected, dtype=np.float64)
                lon_exp = np.asarray(lons_expected, dtype=np.float64)

                max_lat_err = (
                    float(np.max(np.abs(lat_sel - lat_exp))) if lat_sel.size else 0.0
                )
                max_lon_err = (
                    float(np.max(np.abs(lon_sel - lon_exp))) if lon_sel.size else 0.0
                )
                print(
                    f"tile r{tr:03d} c{tc:03d}: max coord error "
                    f"lat={max_lat_err:.6f}, lon={max_lon_err:.6f}"
                )

            arr = da_tile.transpose(lat_name, lon_name, time_dim).values

            tile = np.full(
                (grid.tile_size, grid.tile_size, axis_len),
                fill_value,
                dtype=dtype,
            )
            tile[:valid_h, :valid_w, :] = np.asarray(arr, dtype=dtype)

            if debug and debug_tiles_printed < 3:
                if np.isnan(fill_value):
                    mask = np.isfinite(tile)
                else:
                    mask = tile != fill_value
                finite = int(np.count_nonzero(mask))
                total = int(tile.size)
                if finite > 0:
                    tmin = float(tile[mask].min())
                    tmax = float(tile[mask].max())
                    tmean = float(tile[mask].mean())
                    print(
                        f"tile r{tr:03d} c{tc:03d} stats: "
                        f"finite={finite}/{total} min={tmin:.3f} max={tmax:.3f} mean={tmean:.3f}"
                    )
                else:
                    print(
                        f"tile r{tr:03d} c{tc:03d} stats: finite=0/{total} (all missing)"
                    )
                debug_tiles_printed += 1

            out_path = tile_path(
                out_root, grid, metric=metric_id, tile_r=tr, tile_c=tc, ext=ext
            )
            if resume and out_path.exists():
                if debug:
                    print(f"Skip existing tile: {out_path}")
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
            if debug:
                print(
                    f"Wrote {out_path} (tile r{tr:03d} c{tc:03d} valid={valid_h}x{valid_w})"
                )

    if not debug:
        print(f"Wrote {written} tile(s) for metric={metric_id}")

    return written


def _download_batch_monthly_means(
    *,
    dataset: str,
    grid: GridSpec,
    cache_dir: Path,
    start_year: int,
    end_year: int,
    tile_range: TileRange,
    overwrite_download: bool,
    debug: bool,
    variable: str,
    params: dict[str, Any] | None,
) -> Path:
    p = params or {}
    years_int = list(range(int(start_year), int(end_year) + 1))
    years_str = [str(y) for y in years_int]

    area, total_h, total_w = _compute_batch_bbox(
        grid,
        tile_range.tile_r0,
        tile_range.tile_c0,
        tile_range.tile_r1,
        tile_range.tile_c1,
    )
    area_req = tuple(round(coord, 2) for coord in area)

    dataset_tag = re.sub(r"[^a-z0-9]+", "_", str(dataset).lower()).strip("_")
    prefix = f"cds_monthly_{dataset_tag}_{variable}"
    cache_tag = p.get("cache_tag")
    if isinstance(cache_tag, str) and cache_tag.strip():
        cache_tag_norm = re.sub(r"[^a-z0-9]+", "_", cache_tag.lower()).strip("_")
        if cache_tag_norm:
            prefix = f"{prefix}_{cache_tag_norm}"
    batch_dir = (
        cache_dir
        / f"{prefix}_{grid.grid_id}_r{tile_range.tile_r0:03d}-{tile_range.tile_r1:03d}_c{tile_range.tile_c0:03d}-{tile_range.tile_c1:03d}"
    )
    batch_dir.mkdir(parents=True, exist_ok=True)
    dl_path = batch_dir / (
        f"{prefix}_{grid.grid_id}_r{tile_range.tile_r0:03d}-{tile_range.tile_r1:03d}_c{tile_range.tile_c0:03d}-{tile_range.tile_c1:03d}_{start_year}-{end_year}.nc"
    )
    legacy_prefix = f"era5_monthly_{variable}"
    legacy_batch_dir = (
        cache_dir
        / f"{legacy_prefix}_{grid.grid_id}_r{tile_range.tile_r0:03d}-{tile_range.tile_r1:03d}_c{tile_range.tile_c0:03d}-{tile_range.tile_c1:03d}"
    )
    legacy_dl_path = legacy_batch_dir / (
        f"{legacy_prefix}_{grid.grid_id}_r{tile_range.tile_r0:03d}-{tile_range.tile_r1:03d}_c{tile_range.tile_c0:03d}-{tile_range.tile_c1:03d}_{start_year}-{end_year}.nc"
    )

    if (not overwrite_download) and (not dl_path.exists()) and legacy_dl_path.exists():
        if debug:
            print(f"[cache] Reusing legacy monthly cache path: {legacy_dl_path}")
        dl_path.parent.mkdir(parents=True, exist_ok=True)
        _normalize_cds_payload_to_netcdf(legacy_dl_path)
        legacy_dl_path.replace(dl_path)
        try:
            if legacy_batch_dir.exists() and not any(legacy_batch_dir.iterdir()):
                legacy_batch_dir.rmdir()
        except Exception:
            pass

    if dl_path.exists() and not overwrite_download:
        try:
            _normalize_cds_payload_to_netcdf(dl_path)
            _ = xr.open_dataset(dl_path)
            _.close()
            print(f"Using cached download: {dl_path}")
            return dl_path
        except Exception as exc:
            print(f"[warn] Cached download invalid, deleting: {dl_path} ({exc})")
            try:
                dl_path.unlink()
            except Exception:
                pass

    if debug:
        print(
            f"Downloading CDS monthly batch ({dataset}): years={years_str[0]}..{years_str[-1]} "
            f"tiles r{tile_range.tile_r0}-{tile_range.tile_r1} c{tile_range.tile_c0}-{tile_range.tile_c1} "
            f"area={area_req} expected_points=({total_h} lat x {total_w} lon) grid={grid.deg}"
        )
    else:
        print(
            f"Downloading CDS monthly ({dataset}): years={years_str[0]}..{years_str[-1]} "
            f"area={area} grid={grid.deg}"
        )

    if dataset == ERA5_MONTHLY_MEANS_DATASET:
        req = build_monthly_means_request(
            years=years_str,
            grid_deg=float(grid.deg),
            area=area,
            variable=variable,
        )
    else:
        req = dict(p.get("request_template", {}) or {})
        variable_field = str(p.get("variable_field", "variable"))
        year_field = str(p.get("year_field", "year"))
        month_field = str(p.get("month_field", "month"))
        months = p.get("months")
        if not isinstance(months, list) or not months:
            months = [f"{m:02d}" for m in range(1, 13)]

        req[variable_field] = [variable]
        req[year_field] = years_str
        req[month_field] = months

        format_field = p.get("format_field")
        format_value = p.get("format_value")
        if isinstance(format_field, str) and format_field:
            req[format_field] = format_value if format_value is not None else "netcdf"

        if bool(p.get("include_grid", False)):
            grid_field = str(p.get("grid_field", "grid"))
            req[grid_field] = [float(grid.deg), float(grid.deg)]

        if bool(p.get("include_area", False)) and area is not None:
            area_field = str(p.get("area_field", "area"))
            req[area_field] = [area[0], area[1], area[2], area[3]]

    retrieve(dataset, req, dl_path, overwrite=overwrite_download)
    _normalize_cds_payload_to_netcdf(dl_path)
    print(f"Downloaded: {dl_path}")
    return dl_path


def _download_batch_daily_stats(
    *,
    grid: GridSpec,
    cache_dir: Path,
    start_year: int,
    end_year: int,
    tile_range: TileRange,
    overwrite_download: bool,
    debug: bool,
    variable: str,
    params: dict[str, Any] | None,
    months: list[str] | None,
) -> Path:
    years_int = list(range(int(start_year), int(end_year) + 1))
    years_str = [str(y) for y in years_int]

    area, total_h, total_w = _compute_batch_bbox(
        grid,
        tile_range.tile_r0,
        tile_range.tile_c0,
        tile_range.tile_r1,
        tile_range.tile_c1,
    )

    batch_dir = (
        cache_dir
        / f"era5_daily_{variable}_{grid.grid_id}_r{tile_range.tile_r0:03d}-{tile_range.tile_r1:03d}_c{tile_range.tile_c0:03d}-{tile_range.tile_c1:03d}"
    )
    batch_dir.mkdir(parents=True, exist_ok=True)
    month_tag = ""
    if months:
        month_tag = f"_m{months[0]}-{months[-1]}"

    dl_path = batch_dir / (
        f"era5_daily_{variable}_{grid.grid_id}_r{tile_range.tile_r0:03d}-{tile_range.tile_r1:03d}_c{tile_range.tile_c0:03d}-{tile_range.tile_c1:03d}_{start_year}-{end_year}{month_tag}.nc"
    )

    if dl_path.exists() and not overwrite_download:
        try:
            _normalize_cds_payload_to_netcdf(dl_path)
            _ = xr.open_dataset(dl_path)
            _.close()
            print(f"Using cached download: {dl_path}")
            return dl_path
        except Exception as exc:
            print(f"[warn] Cached download invalid, deleting: {dl_path} ({exc})")
            try:
                dl_path.unlink()
            except Exception:
                pass

    if not overwrite_download:
        covering = _find_covering_daily_cache(
            cache_dir=cache_dir,
            variable=variable,
            grid_id=grid.grid_id,
            tile_range=tile_range,
            start_year=start_year,
            end_year=end_year,
            month_tag=month_tag,
        )
        if covering is not None:
            if debug:
                print(f"[cache] Reusing larger daily cache: {covering}")
            _slice_daily_cache_to_tile_batch(
                src_path=covering,
                dst_path=dl_path,
                grid=grid,
                tile_range=tile_range,
            )
            print(f"[cache] Wrote sliced cache: {dl_path}")
            return dl_path

    area_req = tuple(round(coord, 2) for coord in area)
    months_label = "all" if not months else ",".join(months)
    if debug:
        print(
            f"Downloading ERA5 daily stats: years={years_str[0]}..{years_str[-1]} "
            f"tiles r{tile_range.tile_r0}-{tile_range.tile_r1} c{tile_range.tile_c0}-{tile_range.tile_c1} "
            f"months={months_label} area={area_req} expected_points=({total_h} lat x {total_w} lon) grid={grid.deg}"
        )
    else:
        print(
            f"Downloading ERA5 daily stats: years={years_str[0]}..{years_str[-1]} "
            f"months={months_label} area={area_req} grid={grid.deg}"
        )

    params = params or {}
    req = build_daily_stats_request(
        years=years_str,
        grid_deg=float(grid.deg),
        area=area_req,
        variable=variable,
        daily_statistic=str(params.get("daily_statistic", "daily_mean")),
        time_zone=str(params.get("time_zone", "utc+00:00")),
        frequency=str(params.get("frequency", "1_hourly")),
        months=months,
    )
    try:
        retrieve(ERA5_DAILY_STATS_DATASET, req, dl_path, overwrite=overwrite_download)
        _normalize_cds_payload_to_netcdf(dl_path)
    except Exception:
        req_path = Path(f"{dl_path}.request.json")
        req_path.write_text(json.dumps(req, indent=2, sort_keys=True))
        print(f"Request dump written (error): {req_path}")
        raise
    print(f"Downloaded: {dl_path}")
    return dl_path


_DAILY_BATCH_RE = re.compile(
    r"^era5_daily_(?P<var>.+?)_(?P<grid>[^_]+_[^_]+)_r(?P<r0>\d{3})-(?P<r1>\d{3})_c(?P<c0>\d{3})-(?P<c1>\d{3})$"
)


def _find_covering_daily_cache(
    *,
    cache_dir: Path,
    variable: str,
    grid_id: str,
    tile_range: TileRange,
    start_year: int,
    end_year: int,
    month_tag: str,
) -> Path | None:
    pattern = (
        f"era5_daily_{variable}_{grid_id}_r*-*_c*-*"
        f"/era5_daily_{variable}_{grid_id}_r*-*_c*-*_{start_year}-{end_year}{month_tag}.nc"
    )
    best: tuple[int, Path] | None = None
    for candidate in cache_dir.glob(pattern):
        parent = candidate.parent.name
        m = _DAILY_BATCH_RE.match(parent)
        if m is None:
            continue
        r0 = int(m.group("r0"))
        r1 = int(m.group("r1"))
        c0 = int(m.group("c0"))
        c1 = int(m.group("c1"))
        if (
            r0 <= tile_range.tile_r0 <= tile_range.tile_r1 <= r1
            and c0 <= tile_range.tile_c0 <= tile_range.tile_c1 <= c1
        ):
            area = (r1 - r0 + 1) * (c1 - c0 + 1)
            if best is None or area < best[0]:
                best = (area, candidate)
    return None if best is None else best[1]


def _slice_daily_cache_to_tile_batch(
    *,
    src_path: Path,
    dst_path: Path,
    grid: GridSpec,
    tile_range: TileRange,
) -> None:
    area, _total_h, _total_w = _compute_batch_bbox(
        grid,
        tile_range.tile_r0,
        tile_range.tile_c0,
        tile_range.tile_r1,
        tile_range.tile_c1,
    )
    north, west, south, east = area
    with xr.open_dataset(src_path) as ds:
        lat_name, lon_name = _find_lat_lon_names(ds)
        lat = ds[lat_name]
        lon = ds[lon_name]
        lat_slice = (
            slice(north, south)
            if float(lat.values[0]) >= float(lat.values[-1])
            else slice(south, north)
        )
        lon_slice = (
            slice(west, east)
            if float(lon.values[0]) <= float(lon.values[-1])
            else slice(east, west)
        )
        ds_sub = ds.sel({lat_name: lat_slice, lon_name: lon_slice})
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst_path.with_suffix(dst_path.suffix + ".tmp")
        ds_sub.to_netcdf(tmp)
        tmp.replace(dst_path)


def _download_batch_erddap_daily(
    *,
    dataset_key: str,
    dataset_id_override: str | None,
    variable_override: str | None,
    grid: GridSpec,
    cache_dir: Path,
    start_date: str,
    end_date: str,
    tile_range: TileRange,
    debug: bool,
    stride_time: int | None,
    stride_lat: int | None,
    stride_lon: int | None,
) -> Path:
    spec = ERDDAP_DATASETS.get(dataset_key)
    if spec is None:
        raise ValueError(f"Unknown ERDDAP dataset_key: {dataset_key}")

    dataset_id = dataset_id_override or spec["dataset_id"]
    var = variable_override or spec["var"]
    spec = dict(spec)
    spec["dataset_id"] = dataset_id
    spec["var"] = var

    area, total_h, total_w = _compute_batch_bbox(
        grid,
        tile_range.tile_r0,
        tile_range.tile_c0,
        tile_range.tile_r1,
        tile_range.tile_c1,
    )
    north, west, south, east = area

    cache_dir.mkdir(parents=True, exist_ok=True)
    dl_path = (
        cache_dir
        / f"erddap_{dataset_key}_{grid.grid_id}_r{tile_range.tile_r0:03d}-{tile_range.tile_r1:03d}_c{tile_range.tile_c0:03d}-{tile_range.tile_c1:03d}_{start_date}_{end_date}.nc"
    )

    if dl_path.exists():
        try:
            _ = xr.open_dataset(dl_path)
            _.close()
            print(f"Using cached download: {dl_path}")
            return dl_path
        except Exception as exc:
            print(f"[warn] Cached download invalid, deleting: {dl_path} ({exc})")
            try:
                dl_path.unlink()
            except Exception:
                pass

    if debug:
        print(
            f"Downloading ERDDAP {dataset_key}: {start_date}..{end_date} "
            f"tiles r{tile_range.tile_r0}-{tile_range.tile_r1} c{tile_range.tile_c0}-{tile_range.tile_c1} "
            f"area={area} expected_points=({total_h} lat x {total_w} lon) grid={grid.deg}"
        )
    else:
        print(
            f"Downloading ERDDAP {dataset_key}: {start_date}..{end_date} area={area} grid={grid.deg}"
        )

    lat_variants = [(north, south), (south, north)]
    lon_variants = [(west, east), (east, west)]

    bases = spec.get("bases")
    if not bases:
        raise ValueError(f"ERDDAP dataset missing bases list: {dataset_key}")

    last_err: Exception | None = None
    max_cycles = 50
    backoff_base = 5.0
    backoff_max = 600.0
    for la0, la1 in lat_variants:
        for lo0, lo1 in lon_variants:
            query = build_griddap_query(
                spec,
                a_date=start_date,
                b_date=end_date,
                lat0=la0,
                lat1=la1,
                lon0=lo0,
                lon1=lo1,
                stride_time=stride_time or 1,
                stride_lat=stride_lat or 1,
                stride_lon=stride_lon or 1,
            )
            for cycle in range(max_cycles):
                for base in bases:
                    url = make_griddap_url(base, dataset_id, query, "nc")
                    try:
                        tmp_path = dl_path.with_suffix(dl_path.suffix + ".tmp")
                        if tmp_path.exists():
                            tmp_path.unlink()
                        download_to(
                            url,
                            tmp_path,
                            retries=1,
                            timeout=(30, 300),
                            label=f"[ERDDAP {dataset_key}]",
                            base_label=base,
                        )
                        tmp_path.replace(dl_path)
                        print(f"Downloaded: {dl_path}")
                        return dl_path
                    except Exception as exc:
                        last_err = exc
                        continue
                wait_s = min(backoff_max, backoff_base * (2**cycle))
                print(f"[ERDDAP {dataset_key}] All bases failed (cycle {cycle+1}/{max_cycles}); sleeping {wait_s:.0f}s")
                time.sleep(wait_s)

    raise RuntimeError(f"ERDDAP download failed for {dataset_key}: {last_err}")


def _metric_tile_range(grid: GridSpec, tile_range: TileRange | None) -> TileRange:
    ntr, ntc = tile_counts(grid)
    if tile_range is None:
        return TileRange(0, ntr - 1, 0, ntc - 1)

    if not (
        0 <= tile_range.tile_r0 <= tile_range.tile_r1 < ntr
        and 0 <= tile_range.tile_c0 <= tile_range.tile_c1 < ntc
    ):
        raise ValueError(
            f"Tile range out of bounds for grid {grid.grid_id}: "
            f"r0..r1 within [0,{ntr-1}] and c0..c1 within [0,{ntc-1}], "
            f"got r{tile_range.tile_r0}-{tile_range.tile_r1} "
            f"c{tile_range.tile_c0}-{tile_range.tile_c1}."
        )

    return tile_range


def _snapshot_release_registry(
    *,
    release_root: Path,
    metrics_path: Path,
    datasets_path: Path,
    maps_path: Path,
    panels_path: Path,
) -> dict[str, str]:
    registry_root = release_root / "registry"
    registry_root.mkdir(parents=True, exist_ok=True)

    copied: dict[str, str] = {}
    sources = {
        "metrics.json": metrics_path,
        "datasets.json": datasets_path,
        "maps.json": maps_path,
        "panels.json": panels_path,
    }
    for filename, src in sources.items():
        if not src.exists():
            raise FileNotFoundError(f"Missing registry file for release snapshot: {src}")
        dst = registry_root / filename
        shutil.copy2(src, dst)
        copied[filename] = str(dst.relative_to(release_root))
    return copied


def _write_release_manifest(
    *,
    release_root: Path,
    release: str,
    out_root: Path,
    maps_out_root: Path,
    registry_snapshot: dict[str, str],
) -> None:
    def _path_for_manifest(path: Path) -> str:
        try:
            return str(path.resolve().relative_to(release_root.resolve()))
        except ValueError:
            return str(path)

    payload = {
        "release": release,
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "series_root": _path_for_manifest(out_root),
        "maps_root": _path_for_manifest(maps_out_root),
        "registry": registry_snapshot,
    }
    manifest_path = release_root / "manifest.json"
    manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def package_registry(
    *,
    out_root: Path,
    release: str = "dev",
    metrics_path: Path | str | None = None,
    schema_path: Path | str | None = None,
    datasets_path: Path | str | None = None,
    cache_dir: Path = Path("data/cache"),
    start_year: int | None = None,
    end_year: int | None = None,
    metric_ids: list[str] | None = None,
    tile_range: TileRange | None = None,
    batch_tiles: int | None = None,
    resume: bool = False,
    overwrite_download: bool = False,
    debug: bool = False,
    max_batches: int | None = None,
    max_requests: int | None = None,
    dask_enabled: bool = False,
    dask_chunk_lat: int = 16,
    dask_chunk_lon: int = 16,
    agg_debug: bool = False,
    pipeline: bool = False,
    workers: int | None = None,
    summary_interval_s: int = 30,
    download_only: bool = False,
    maps_path: Path | str | None = None,
    maps_schema_path: Path | str | None = None,
    panels_path: Path | str | None = None,
    panels_schema_path: Path | str | None = None,
    maps_out_root: Path | None = None,
    map_ids: list[str] | None = None,
    all_maps: bool = False,
    skip_maps: bool = False,
) -> int:
    metrics_path = (
        Path(metrics_path) if metrics_path is not None else DEFAULT_METRICS_PATH
    )
    schema_path = Path(schema_path) if schema_path is not None else DEFAULT_SCHEMA_PATH
    datasets_path = (
        Path(datasets_path)
        if datasets_path is not None
        else DEFAULT_DATASETS_PATH
    )
    manifest = load_metrics(
        path=metrics_path,
        schema_path=schema_path,
        datasets_path=datasets_path,
        validate=True,
    )
    if metric_ids:
        known_metric_ids = {
            key for key in manifest.keys() if key != "version" and isinstance(manifest[key], dict)
        }
        unknown_metric_ids = sorted(set(metric_ids) - known_metric_ids)
        if unknown_metric_ids:
            raise ValueError(
                "Unknown metric id(s): "
                + ", ".join(unknown_metric_ids)
                + ". Use ids from registry/metrics.json (not registry/datasets.json)."
            )
    maps_manifest: dict[str, Any] | None = None
    maps_path_eff = Path(maps_path) if maps_path is not None else DEFAULT_MAPS_PATH
    maps_schema_path_eff = (
        Path(maps_schema_path)
        if maps_schema_path is not None
        else DEFAULT_MAPS_SCHEMA_PATH
    )
    if maps_path_eff.exists():
        maps_manifest = load_maps(
            path=maps_path_eff,
            schema_path=maps_schema_path_eff,
            validate=True,
        )
        validate_maps_against_metrics(maps_manifest, manifest)
    elif debug:
        print(f"[maps] No maps registry found at {maps_path_eff}; skipping map packaging.")

    panels_path_eff = (
        Path(panels_path) if panels_path is not None else DEFAULT_PANELS_PATH
    )
    panels_schema_path_eff = (
        Path(panels_schema_path)
        if panels_schema_path is not None
        else DEFAULT_PANELS_SCHEMA_PATH
    )
    if not panels_path_eff.exists():
        raise FileNotFoundError(f"Missing panels registry: {panels_path_eff}")
    panels_manifest = load_panels(
        path=panels_path_eff,
        schema_path=panels_schema_path_eff,
        validate=True,
    )
    validate_panels_against_metrics(panels_manifest, manifest)
    if maps_manifest is not None:
        validate_panels_against_maps(panels_manifest, maps_manifest)

    effective_metric_ids: set[str] | None = set(metric_ids) if metric_ids else None
    if effective_metric_ids is None and maps_manifest is not None and (map_ids or all_maps):
        maps_specs = {
            key: spec
            for key, spec in maps_manifest.items()
            if key != "version" and isinstance(spec, dict)
        }
        selected_map_ids = list(maps_specs.keys()) if all_maps else list(map_ids or [])
        missing_maps = [mid for mid in selected_map_ids if mid not in maps_specs]
        if missing_maps:
            raise ValueError(f"Unknown map id(s): {', '.join(sorted(missing_maps))}")
        effective_metric_ids = set()
        for mid in selected_map_ids:
            spec = maps_specs[mid]
            source_metric = spec.get("source_metric")
            if isinstance(source_metric, str) and source_metric:
                effective_metric_ids.add(str(source_metric))
                continue
            # Constant score maps are virtual maps with no source metric.
            if spec.get("type") == "score" and spec.get("constant_score") is not None:
                continue
            raise ValueError(f"Map '{mid}' is missing source_metric.")
        if debug:
            print(
                "[maps] Restricting metric packaging to selected maps' source metrics: "
                + ", ".join(sorted(effective_metric_ids))
            )

    for metric_id, spec in manifest.items():
        if metric_id == "version":
            continue
        if effective_metric_ids and metric_id not in effective_metric_ids:
            continue

        if dask_enabled:
            try:
                import dask  # noqa: F401
            except Exception as exc:
                raise RuntimeError(
                    "dask is required when --dask is enabled. Please install dask."
                ) from exc

        source = spec.get("source", {})
        storage = spec.get("storage", {})
        if not storage.get("tiled", True):
            continue
        if spec.get("materialize") not in (None, "on_packager"):
            continue

        source_type = source.get("type")

        if source_type == "derived":
            print(
                f"[metric] skip metric={metric_id} source=derived "
                "reason=derived packaging is not supported by packager"
            )
            continue

        agg = source.get("agg")
        if not agg:
            raise ValueError(
                f"Missing aggregator for metric={metric_id} source={source_type}. "
                "Expected source.agg."
            )
        agg_fn = _agg_map().get(agg)
        if agg_fn is None:
            raise ValueError(
                f"Unsupported aggregator for metric={metric_id}: {agg}"
            )

        time_axis = str(spec.get("time_axis", "yearly"))
        if time_axis not in {"yearly", "monthly", "daily"}:
            raise ValueError(f"Unsupported time_axis for packager: {time_axis}")

        tile_size = int(storage.get("tile_size", 64))
        grid = _grid_from_id(spec["grid_id"], tile_size=tile_size)
        metric_tile_range = _metric_tile_range(grid, tile_range)

        dtype = np.dtype(spec.get("dtype", "float32"))
        missing = spec.get("missing", "nan")
        compression = storage.get("compression")

        (
            analysis_start_year,
            analysis_end_year,
            download_start_year,
            download_end_year,
        ) = _resolve_year_ranges(
            source=source,
            cli_start_year=start_year,
            cli_end_year=end_year,
        )
        years_int = list(range(analysis_start_year, analysis_end_year + 1))
        print(
            f"[metric] start metric={metric_id} source={source_type} "
            f"time_axis={time_axis} agg={agg} "
            f"analysis={analysis_start_year}..{analysis_end_year} "
            f"download={download_start_year}..{download_end_year}"
        )
        if debug:
            print(
                f"[range] metric={metric_id} analysis={analysis_start_year}..{analysis_end_year} "
                f"download={download_start_year}..{download_end_year}"
            )

        batch_tiles_eff = (
            int(batch_tiles)
            if batch_tiles is not None
            else int(source.get("batch_tiles", 1))
        )
        n_batches_processed = 0
        download_count = 0
        total_written = 0

        stop_after_current = False
        sigint_count = 0

        def _handle_sigint(_sig: int, _frame: object) -> None:
            nonlocal stop_after_current, sigint_count
            sigint_count += 1
            if sigint_count >= 2:
                raise KeyboardInterrupt
            stop_after_current = True
            print(
                "Interrupt received. Script will stop once active processes are finished. "
                "Press Ctrl+C again to terminate immediately."
            )

        prev_handler = signal.signal(signal.SIGINT, _handle_sigint)

        try:
            if pipeline:
                workers_eff = (
                    int(workers)
                    if workers is not None
                    else max(1, (os.cpu_count() or 2) - 1)
                )
                downloads_done = 0
                batches_completed = 0
                counters_lock = threading.Lock()
                summary_stop = threading.Event()

                batches_to_process: list[TileRange] = []
                for batch in _iter_batches(metric_tile_range, batch_tiles_eff):
                    if resume:
                        missing_tiles = _batch_missing_tiles(
                            out_root, grid, metric_id, batch, compression
                        )
                        if not missing_tiles:
                            continue
                    batches_to_process.append(batch)
                    if max_batches is not None and len(batches_to_process) >= int(
                        max_batches
                    ):
                        break

                batches_total = len(batches_to_process)

                def _downloads_per_batch() -> int:
                    if source_type == "cds":
                        dataset = source.get("dataset")
                        params = source.get("params", {}) or {}
                        if _is_cds_monthly_dataset(str(dataset), params):
                            blocks = _cds_year_blocks_for_metric(
                                agg=agg,
                                source=source,
                                download_start_year=download_start_year,
                                download_end_year=download_end_year,
                            )
                            return len(blocks)
                        block_years = int(source.get("block_years", 1))
                        blocks = _year_blocks(
                            download_start_year,
                            download_end_year,
                            block_years,
                            dataset_start=None,
                        )
                        month_blocks = _month_blocks(int(source.get("block_months", 1)))
                        return len(blocks) * len(month_blocks)
                    if source_type == "erddap":
                        dataset_key = source.get("dataset_key")
                        dataset_spec = ERDDAP_DATASETS.get(dataset_key, {})
                        dataset_start = dataset_spec.get("dataset_start")
                        block_years = int(
                            source.get(
                                "block_years",
                                dataset_spec.get("recommended_block_years", 5),
                            )
                        )
                        blocks = _year_blocks(
                            download_start_year,
                            download_end_year,
                            block_years,
                            dataset_start=dataset_start,
                        )
                        return len(blocks)
                    return 0

                downloads_total = _downloads_per_batch() * batches_total

                def _summary_loop() -> None:
                    interval = max(5, int(summary_interval_s))
                    while not summary_stop.wait(interval):
                        with counters_lock:
                            in_flight = n_batches_processed - batches_completed
                            d_done = downloads_done
                            b_done = batches_completed
                        print(
                            f"[summary] {b_done}/{batches_total} batches - "
                            f"{d_done}/{downloads_total} downloads - "
                            f"{b_done}/{batches_total} post-processes "
                            f"({in_flight} jobs queued)"
                        )

                summary_thread = threading.Thread(target=_summary_loop, daemon=True)
                summary_thread.start()
                print(f"Starting processing pool with {workers_eff} worker(s)")
                with ProcessPoolExecutor(max_workers=workers_eff) as executor:
                    futures = []
                    stop_downloads = False
                    future_errors: list[str] = []
                    def _on_future_done(fut) -> None:
                        nonlocal batches_completed, total_written
                        try:
                            written = int(fut.result())
                        except Exception as exc:
                            written = 0
                            with counters_lock:
                                future_errors.append(repr(exc))
                            print(f"[error] Worker failed for metric={metric_id}: {exc!r}")
                        with counters_lock:
                            total_written += written
                            batches_completed += 1
                    def _collect_done() -> None:
                        done, pending = wait(futures, timeout=0, return_when=FIRST_COMPLETED)
                        if not done:
                            return
                        for fut in done:
                            # already accounted for by callback
                            pass
                        futures[:] = list(pending)
                    for batch in batches_to_process:
                        if stop_after_current:
                            stop_downloads = True
                            break
                        if debug and resume:
                            missing_tiles = _batch_missing_tiles(
                                out_root, grid, metric_id, batch, compression
                            )
                            if missing_tiles:
                                print(
                                    f"Batch missing {len(missing_tiles)} tile(s): {missing_tiles[:8]}"
                                )

                        if source_type == "cds":
                            cache_dir_eff = cache_dir / "cds"
                            dataset = source.get("dataset")
                            params = source.get("params", {}) or {}
                            is_monthly_cds = _is_cds_monthly_dataset(str(dataset), params)
                            if not is_monthly_cds and dataset != ERA5_DAILY_STATS_DATASET:
                                raise ValueError(f"Unsupported CDS dataset: {dataset}")

                            variable = source.get("variable")
                            if isinstance(variable, list):
                                if len(variable) != 1:
                                    raise ValueError(
                                        f"Unsupported variable list: {variable}"
                                    )
                                variable = variable[0]
                            if not isinstance(variable, str):
                                raise ValueError(f"Unsupported variable: {variable}")

                            if dataset == ERA5_DAILY_STATS_DATASET:
                                block_years = int(source.get("block_years", 1))
                                if block_years != 1:
                                    raise ValueError(
                                        "CDS daily stats requires block_years=1 (per-year requests)."
                                    )
                                blocks = _year_blocks(
                                    download_start_year,
                                    download_end_year,
                                    block_years,
                                    dataset_start=None,
                                )
                            else:
                                blocks = _cds_year_blocks_for_metric(
                                    agg=agg,
                                    source=source,
                                    download_start_year=download_start_year,
                                    download_end_year=download_end_year,
                                )
                            if not blocks:
                                raise ValueError(
                                    f"No valid CDS blocks for {download_start_year}-{download_end_year}"
                                )

                            downloads: list[tuple[list[int], list[Path]]] = []
                            for _start_date, _end_date, years_part in blocks:
                                if is_monthly_cds:
                                    if (
                                        max_requests is not None
                                        and download_count >= int(max_requests)
                                    ):
                                        print(
                                            f"Stopping early due to --max-requests={max_requests}"
                                        )
                                        stop_downloads = True
                                        break
                                    dl_path = _download_batch_monthly_means(
                                        dataset=str(dataset),
                                        grid=grid,
                                        cache_dir=cache_dir_eff,
                                        start_year=years_part[0],
                                        end_year=years_part[-1],
                                        tile_range=batch,
                                        overwrite_download=overwrite_download,
                                        debug=debug,
                                        variable=variable,
                                        params=params,
                                    )
                                    download_count += 1
                                    with counters_lock:
                                        downloads_done += 1
                                    downloads.append((years_part, [dl_path]))
                                    if stop_after_current:
                                        stop_downloads = True
                                        break
                                else:
                                    block_months = int(source.get("block_months", 1))
                                    month_blocks = _month_blocks(block_months)
                                    paths: list[Path] = []
                                    for months in month_blocks:
                                        if (
                                            max_requests is not None
                                            and download_count >= int(max_requests)
                                        ):
                                            print(
                                                f"Stopping early due to --max-requests={max_requests}"
                                            )
                                            stop_downloads = True
                                            break
                                        dl_path = _download_batch_daily_stats(
                                            grid=grid,
                                            cache_dir=cache_dir_eff,
                                            start_year=years_part[0],
                                            end_year=years_part[-1],
                                            tile_range=batch,
                                            overwrite_download=overwrite_download,
                                            debug=debug,
                                            variable=variable,
                                            params=params,
                                            months=months,
                                        )
                                        download_count += 1
                                        with counters_lock:
                                            downloads_done += 1
                                        paths.append(dl_path)
                                        if stop_after_current:
                                            stop_downloads = True
                                            break
                                    if stop_downloads:
                                        break
                                    downloads.append((years_part, paths))

                                if stop_downloads:
                                    break

                            if stop_downloads:
                                break

                            expected_years = [yy for _, _, ys in blocks for yy in ys]
                            got_years = [yy for ys, _ in downloads for yy in ys]
                            if expected_years != got_years:
                                if debug:
                                    print(
                                        f"[warn] Incomplete downloads for batch "
                                        f"r{batch.tile_r0}-{batch.tile_r1} c{batch.tile_c0}-{batch.tile_c1}: "
                                        f"got years {got_years[:3]}..{got_years[-3:] if got_years else []} "
                                        f"expected {expected_years[0]}..{expected_years[-1]}"
                                    )
                                stop_downloads = True
                                break

                            if download_only:
                                n_batches_processed += 1
                                _collect_done()
                                continue

                            params_dbg = dict(params)
                            if agg_debug and agg == "hot_days_per_year":
                                params_dbg["_debug"] = True
                            futures.append(
                                executor.submit(
                                    _compute_tiles_from_cds_downloads,
                                    dataset=dataset,
                                    agg=agg,
                                    postprocess=source.get("postprocess"),
                                    params=params_dbg,
                                    downloads=downloads,
                                    out_root=out_root,
                                    grid=grid,
                                    metric_id=metric_id,
                                    tile_range=batch,
                                    dtype=dtype,
                                    missing=missing,
                                    compression=compression,
                                    debug=debug,
                                    resume=resume,
                                    dask_enabled=dask_enabled,
                                    dask_chunk_lat=dask_chunk_lat,
                                    dask_chunk_lon=dask_chunk_lon,
                                    output_years=years_int,
                                    time_axis=time_axis,
                                    data_var_hint=variable,
                                )
                            )
                            futures[-1].add_done_callback(_on_future_done)
                            n_batches_processed += 1
                            _collect_done()
                        elif source_type == "erddap":
                            cache_dir_eff = cache_dir / "erddap"
                            dataset_key = source.get("dataset_key")
                            if not dataset_key:
                                raise ValueError("ERDDAP source missing dataset_key")
                            dataset_spec = ERDDAP_DATASETS.get(dataset_key, {})
                            dataset_start = dataset_spec.get("dataset_start")
                            block_years = int(
                                source.get(
                                    "block_years",
                                    dataset_spec.get("recommended_block_years", 5),
                                )
                            )
                            blocks = _year_blocks(
                                download_start_year,
                                download_end_year,
                                block_years,
                                dataset_start=dataset_start,
                            )
                            if not blocks:
                                raise ValueError(
                                    f"No valid ERDDAP blocks for {dataset_key} {download_start_year}-{download_end_year}"
                                )

                            params = source.get("params", {}) or {}
                            downloads: list[tuple[list[int], list[Path]]] = []
                            for start_date, end_date, years_part in blocks:
                                if (
                                    max_requests is not None
                                    and download_count >= int(max_requests)
                                ):
                                    print(
                                        f"Stopping early due to --max-requests={max_requests}"
                                    )
                                    stop_downloads = True
                                    break
                                dl_path = _download_batch_erddap_daily(
                                    dataset_key=dataset_key,
                                    dataset_id_override=source.get("dataset_id"),
                                    variable_override=source.get("variable"),
                                    grid=grid,
                                    cache_dir=cache_dir_eff,
                                    start_date=start_date,
                                    end_date=end_date,
                                    tile_range=batch,
                                    debug=debug,
                                    stride_time=source.get("stride_time"),
                                    stride_lat=source.get("stride_lat"),
                                    stride_lon=source.get("stride_lon"),
                                )
                                download_count += 1
                                with counters_lock:
                                    downloads_done += 1
                                downloads.append((years_part, [dl_path]))
                                if stop_after_current:
                                    stop_downloads = True
                                    break

                            if stop_downloads:
                                break

                            expected_years = [yy for _, _, ys in blocks for yy in ys]
                            got_years = [yy for ys, _ in downloads for yy in ys]
                            if expected_years != got_years:
                                if debug:
                                    print(
                                        f"[warn] Incomplete downloads for batch "
                                        f"r{batch.tile_r0}-{batch.tile_r1} c{batch.tile_c0}-{batch.tile_c1}: "
                                        f"got years {got_years[:3]}..{got_years[-3:] if got_years else []} "
                                        f"expected {expected_years[0]}..{expected_years[-1]}"
                                    )
                                stop_downloads = True
                                break

                            if download_only:
                                n_batches_processed += 1
                                _collect_done()
                                continue

                            params_dbg = dict(params)
                            if agg_debug and agg == "hot_days_per_year":
                                params_dbg["_debug"] = True
                            futures.append(
                                executor.submit(
                                    _compute_tiles_from_erddap_downloads,
                                    agg=agg,
                                    postprocess=source.get("postprocess"),
                                    params=params_dbg,
                                    downloads=downloads,
                                    out_root=out_root,
                                    grid=grid,
                                    metric_id=metric_id,
                                    tile_range=batch,
                                    dtype=dtype,
                                    missing=missing,
                                    compression=compression,
                                    debug=debug,
                                    resume=resume,
                                    dask_enabled=dask_enabled,
                                    dask_chunk_lat=dask_chunk_lat,
                                    dask_chunk_lon=dask_chunk_lon,
                                    output_years=years_int,
                                    time_axis=time_axis,
                                    data_var_hint=source.get("variable"),
                                )
                            )
                            futures[-1].add_done_callback(_on_future_done)
                            n_batches_processed += 1
                            _collect_done()
                        else:
                            raise ValueError(f"Unsupported source type: {source_type}")

                    for fut in as_completed(futures):
                        try:
                            fut.result()
                        except Exception:
                            # Already tracked and logged by callback.
                            pass
                    summary_stop.set()
                    summary_thread.join(timeout=1)
                    if future_errors:
                        preview = "; ".join(future_errors[:3])
                        raise RuntimeError(
                            f"{len(future_errors)} worker batch(es) failed for metric={metric_id}. "
                            f"First errors: {preview}"
                        )
                    if stop_after_current:
                        in_flight = n_batches_processed - batches_completed
                        print(
                            f"[summary] stopped by user - "
                            f"{batches_completed}/{batches_total} batches - "
                            f"{downloads_done}/{downloads_total} downloads - "
                            f"{batches_completed}/{batches_total} post-processes "
                            f"({in_flight} jobs queued)"
                        )
                    else:
                        in_flight = n_batches_processed - batches_completed
                        print(
                            f"[summary] {batches_completed}/{batches_total} batches - "
                            f"{downloads_done}/{downloads_total} downloads - "
                            f"{batches_completed}/{batches_total} post-processes "
                            f"({in_flight} jobs queued)"
                        )

                print(
                    f"DONE: wrote {total_written} tile(s) for metric={metric_id} "
                    f"tiles r{metric_tile_range.tile_r0}-{metric_tile_range.tile_r1} "
                    f"c{metric_tile_range.tile_c0}-{metric_tile_range.tile_c1} "
                    f"(batch_tiles={batch_tiles_eff})"
                )
                continue

            for batch in _iter_batches(metric_tile_range, batch_tiles_eff):
                if stop_after_current:
                    break
                if resume:
                    missing_tiles = _batch_missing_tiles(
                        out_root, grid, metric_id, batch, compression
                    )
                    if not missing_tiles:
                        if debug:
                            print(
                                f"Skip batch (all tiles exist): r{batch.tile_r0}-{batch.tile_r1} "
                                f"c{batch.tile_c0}-{batch.tile_c1}"
                            )
                        continue
                    if debug:
                        print(
                            f"Batch missing {len(missing_tiles)} tile(s): {missing_tiles[:8]}"
                        )

                if max_batches is not None and n_batches_processed >= int(max_batches):
                    print(f"Stopping early due to --max-batches={max_batches}")
                    break

                if source_type == "cds":
                    cache_dir_eff = cache_dir / "cds"
                    dataset = source.get("dataset")
                    params = source.get("params", {}) or {}
                    is_monthly_cds = _is_cds_monthly_dataset(str(dataset), params)
                    if not is_monthly_cds and dataset != ERA5_DAILY_STATS_DATASET:
                        raise ValueError(f"Unsupported CDS dataset: {dataset}")

                    variable = source.get("variable")
                    if isinstance(variable, list):
                        if len(variable) != 1:
                            raise ValueError(f"Unsupported variable list: {variable}")
                        variable = variable[0]
                    if not isinstance(variable, str):
                        raise ValueError(f"Unsupported variable: {variable}")

                    if dataset == ERA5_DAILY_STATS_DATASET:
                        block_years = int(source.get("block_years", 1))
                        if block_years != 1:
                            raise ValueError(
                                "CDS daily stats requires block_years=1 (per-year requests)."
                            )
                        blocks = _year_blocks(
                            download_start_year,
                            download_end_year,
                            block_years,
                            dataset_start=None,
                        )
                    else:
                        blocks = _cds_year_blocks_for_metric(
                            agg=agg,
                            source=source,
                            download_start_year=download_start_year,
                            download_end_year=download_end_year,
                        )
                    if not blocks:
                        raise ValueError(
                            f"No valid CDS blocks for {download_start_year}-{download_end_year}"
                        )

                    downloads: list[tuple[list[int], list[Path]]] = []
                    for _start_date, _end_date, years_part in blocks:
                        if stop_after_current:
                            break
                        if is_monthly_cds:
                            if (
                                max_requests is not None
                                and download_count >= int(max_requests)
                            ):
                                print(
                                    f"Stopping early due to --max-requests={max_requests}"
                                )
                                return total_written
                            dl_path = _download_batch_monthly_means(
                                dataset=str(dataset),
                                grid=grid,
                                cache_dir=cache_dir_eff,
                                start_year=years_part[0],
                                end_year=years_part[-1],
                                tile_range=batch,
                                overwrite_download=overwrite_download,
                                debug=debug,
                                variable=variable,
                                params=params,
                            )
                            download_count += 1
                            downloads.append((years_part, [dl_path]))
                        else:
                            block_months = int(source.get("block_months", 1))
                            month_blocks = _month_blocks(block_months)
                            paths: list[Path] = []
                            for months in month_blocks:
                                if stop_after_current:
                                    break
                                if (
                                    max_requests is not None
                                    and download_count >= int(max_requests)
                                ):
                                    print(
                                        f"Stopping early due to --max-requests={max_requests}"
                                    )
                                    return total_written
                                dl_path = _download_batch_daily_stats(
                                    grid=grid,
                                    cache_dir=cache_dir_eff,
                                    start_year=years_part[0],
                                    end_year=years_part[-1],
                                    tile_range=batch,
                                    overwrite_download=overwrite_download,
                                    debug=debug,
                                    variable=variable,
                                    params=params,
                                    months=months,
                                )
                                download_count += 1
                                paths.append(dl_path)
                            if stop_after_current:
                                break
                            downloads.append((years_part, paths))

                    params_dbg = dict(params)
                    if agg_debug and agg == "hot_days_per_year":
                        params_dbg["_debug"] = True
                    if download_only:
                        n_batches_processed += 1
                        continue
                    total_written += _compute_tiles_from_cds_downloads(
                        dataset=dataset,
                        agg=agg,
                        postprocess=source.get("postprocess"),
                        params=params_dbg,
                        downloads=downloads,
                        out_root=out_root,
                        grid=grid,
                        metric_id=metric_id,
                        tile_range=batch,
                        dtype=dtype,
                        missing=missing,
                        compression=compression,
                        debug=debug,
                        resume=resume,
                        dask_enabled=dask_enabled,
                        dask_chunk_lat=dask_chunk_lat,
                        dask_chunk_lon=dask_chunk_lon,
                        output_years=years_int,
                        time_axis=time_axis,
                        data_var_hint=variable,
                    )

                    n_batches_processed += 1
                    continue
                elif source_type == "erddap":
                    cache_dir_eff = cache_dir / "erddap"
                    dataset_key = source.get("dataset_key")
                    if not dataset_key:
                        raise ValueError("ERDDAP source missing dataset_key")
                    dataset_spec = ERDDAP_DATASETS.get(dataset_key, {})
                    dataset_start = dataset_spec.get("dataset_start")
                    block_years = int(
                        source.get(
                            "block_years",
                            dataset_spec.get("recommended_block_years", 5),
                        )
                    )

                    blocks = _year_blocks(
                        download_start_year,
                        download_end_year,
                        block_years,
                        dataset_start=dataset_start,
                    )
                    if not blocks:
                        raise ValueError(
                            f"No valid ERDDAP blocks for {dataset_key} {download_start_year}-{download_end_year}"
                        )

                    params = source.get("params", {}) or {}
                    downloads = []
                    for start_date, end_date, years_part in blocks:
                        if stop_after_current:
                            break
                        if (
                            max_requests is not None
                            and download_count >= int(max_requests)
                        ):
                            print(
                                f"Stopping early due to --max-requests={max_requests}"
                            )
                            return total_written
                        dl_path = _download_batch_erddap_daily(
                            dataset_key=dataset_key,
                            dataset_id_override=source.get("dataset_id"),
                            variable_override=source.get("variable"),
                            grid=grid,
                            cache_dir=cache_dir_eff,
                            start_date=start_date,
                            end_date=end_date,
                            tile_range=batch,
                            debug=debug,
                            stride_time=source.get("stride_time"),
                            stride_lat=source.get("stride_lat"),
                            stride_lon=source.get("stride_lon"),
                        )
                        download_count += 1
                        downloads.append((years_part, [dl_path]))

                    params_dbg = dict(params)
                    if agg_debug and agg == "hot_days_per_year":
                        params_dbg["_debug"] = True
                    if download_only:
                        n_batches_processed += 1
                        continue
                    total_written += _compute_tiles_from_erddap_downloads(
                        agg=agg,
                        postprocess=source.get("postprocess"),
                        params=params_dbg,
                        downloads=downloads,
                        out_root=out_root,
                        grid=grid,
                        metric_id=metric_id,
                        tile_range=batch,
                        dtype=dtype,
                        missing=missing,
                        compression=compression,
                        debug=debug,
                        resume=resume,
                        dask_enabled=dask_enabled,
                        dask_chunk_lat=dask_chunk_lat,
                        dask_chunk_lon=dask_chunk_lon,
                        output_years=years_int,
                        time_axis=time_axis,
                        data_var_hint=source.get("variable"),
                    )

                    n_batches_processed += 1
                    continue
                else:
                    raise ValueError(f"Unsupported source type: {source_type}")

                n_batches_processed += 1

            print(
                f"DONE: wrote {total_written} tile(s) for metric={metric_id} "
                f"tiles r{metric_tile_range.tile_r0}-{metric_tile_range.tile_r1} "
                f"c{metric_tile_range.tile_c0}-{metric_tile_range.tile_c1} "
                f"(batch_tiles={batch_tiles_eff})"
            )
        finally:
            signal.signal(signal.SIGINT, prev_handler)

    maps_out_root_eff = (
        Path(maps_out_root)
        if maps_out_root is not None
        else out_root.parent / "maps"
    )
    if not download_only and not skip_maps and maps_manifest is not None:
        maps_written = package_maps(
            series_root=out_root,
            maps_root=maps_out_root_eff,
            maps_manifest=maps_manifest,
            metrics_manifest=manifest,
            map_ids=map_ids,
            metric_ids=sorted(effective_metric_ids) if effective_metric_ids else None,
            resume=resume,
            debug=debug,
        )
        print(f"DONE: wrote {maps_written} map asset(s) into {maps_out_root_eff}")

    if not download_only:
        release_root = out_root.parent
        registry_snapshot = _snapshot_release_registry(
            release_root=release_root,
            metrics_path=metrics_path,
            datasets_path=datasets_path,
            maps_path=maps_path_eff,
            panels_path=panels_path_eff,
        )
        _write_release_manifest(
            release_root=release_root,
            release=release,
            out_root=out_root,
            maps_out_root=maps_out_root_eff,
            registry_snapshot=registry_snapshot,
        )
        print(f"DONE: wrote release manifest: {release_root / 'manifest.json'}")

    return 0


def _compression_ext(compression: dict | None) -> str:
    codec = "zstd"
    if compression is not None:
        codec = compression.get("codec", codec)
    if codec == "zstd":
        return ".bin.zst"
    if codec == "none":
        return ".bin"
    raise ValueError(f"Unsupported compression codec: {codec}")


def _batch_missing_tiles(
    out_root: Path,
    grid: GridSpec,
    metric_id: str,
    tile_range: TileRange,
    compression: dict | None,
) -> list[tuple[int, int]]:
    ext = _compression_ext(compression)
    missing: list[tuple[int, int]] = []
    for tr in range(tile_range.tile_r0, tile_range.tile_r1 + 1):
        for tc in range(tile_range.tile_c0, tile_range.tile_c1 + 1):
            p = tile_path(
                out_root, grid, metric=metric_id, tile_r=tr, tile_c=tc, ext=ext
            )
            if not p.exists():
                missing.append((tr, tc))
    return missing
