#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import xarray as xr

from climate.datasets.products.erddap_specs import ERDDAP_DATASETS
from climate.datasets.sources.erddap import build_griddap_query, make_griddap_url
from climate.datasets.sources.http import download_to
from climate.registry.metrics import DEFAULT_DATASETS_PATH, load_datasets
from climate.tiles.layout import GridSpec, cell_center_latlon

REPO_ROOT = Path(__file__).resolve().parents[2]


def _grid_from_id(grid_id: str, tile_size: int) -> GridSpec:
    if grid_id == "global_0p25":
        return GridSpec.global_0p25(tile_size=tile_size)
    if grid_id == "global_0p05":
        return GridSpec.global_0p05(tile_size=tile_size)
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


def _compute_full_grid_area(grid: GridSpec) -> tuple[float, float, float, float]:
    # Request cell-center bounds; using the last synthetic row on our grids can
    # go slightly below -90 (e.g. -90.025 at 0.05 deg), which ERDDAP rejects.
    half = float(grid.deg) * 0.5
    north = float(grid.lat_max) - half
    south = -float(grid.lat_max) + half
    west = float(grid.lon_min) + half
    east = float(grid.lon_max) - half
    return (float(north), float(west), float(south), float(east))


def _expected_coords(grid: GridSpec) -> tuple[np.ndarray, np.ndarray]:
    lat_vals = np.asarray(
        [cell_center_latlon(i, 0, grid)[0] for i in range(grid.nlat)], dtype=np.float64
    )
    lon_vals = np.asarray(
        [cell_center_latlon(0, j, grid)[1] for j in range(grid.nlon)], dtype=np.float64
    )
    return lat_vals, lon_vals


def _normalize_lon_to_pm180(da: xr.DataArray, lon_name: str) -> xr.DataArray:
    lon_raw = np.asarray(da[lon_name].values, dtype=np.float64)
    lon_norm = ((lon_raw + 180.0) % 360.0) - 180.0
    if np.any(np.abs(lon_raw - lon_norm) > 1e-10):
        da = da.assign_coords({lon_name: lon_norm})
    return da.sortby(lon_name)


def _pick_data_var(ds: xr.Dataset, preferred: str | None) -> str:
    if preferred and preferred in ds.data_vars:
        return preferred
    data_vars = list(ds.data_vars)
    if len(data_vars) == 1:
        return data_vars[0]
    if preferred:
        for name in data_vars:
            if preferred.lower() in name.lower():
                return name
    raise RuntimeError(
        f"Could not infer data variable (preferred={preferred}); data_vars={data_vars}"
    )


def _download_erddap_full_grid(
    *,
    dataset_key: str,
    dataset_id: str,
    variable: str,
    start_date: str,
    end_date: str,
    cache_dir: Path,
    grid: GridSpec,
    stride_time: int,
    stride_lat: int,
    stride_lon: int,
) -> Path:
    spec = dict(ERDDAP_DATASETS[dataset_key])
    spec["dataset_id"] = dataset_id
    spec["var"] = variable
    bases = spec.get("bases") or []
    if not bases:
        raise ValueError(f"ERDDAP dataset {dataset_key} has no base URLs")

    north, west, south, east = _compute_full_grid_area(grid)
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_path = (
        cache_dir
        / f"mask_seed_{dataset_key}_{grid.grid_id}_{start_date}_{end_date}.nc"
    )
    if out_path.exists() and out_path.stat().st_size > 0:
        print(f"Using cached seed download: {out_path}")
        return out_path

    lat_variants = [(north, south), (south, north)]
    lon_variants = [(west, east), (east, west)]
    last_err: Exception | None = None
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
                stride_time=max(1, int(stride_time)),
                stride_lat=max(1, int(stride_lat)),
                stride_lon=max(1, int(stride_lon)),
            )
            for base in bases:
                url = make_griddap_url(base, dataset_id, query, "nc")
                try:
                    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
                    if tmp.exists():
                        tmp.unlink()
                    download_to(
                        url,
                        tmp,
                        retries=3,
                        timeout=(30, 300),
                        label=f"[mask:{dataset_key}]",
                        base_label=base,
                    )
                    tmp.replace(out_path)
                    print(f"Downloaded: {out_path}")
                    return out_path
                except Exception as exc:
                    last_err = exc
                    continue

    raise RuntimeError(f"Failed to download ERDDAP seed file for {dataset_key}: {last_err}")


def _build_mask_from_seed(
    *,
    nc_path: Path,
    grid: GridSpec,
    variable_hint: str | None,
    min_finite_days: int,
) -> np.ndarray:
    tol = float(grid.deg) * 0.51
    lat_expected, lon_expected = _expected_coords(grid)

    with xr.open_dataset(nc_path) as ds:
        var_name = _pick_data_var(ds, preferred=variable_hint)
        da = ds[var_name]
        if "zlev" in da.dims:
            da = da.sel(zlev=0.0, drop=True)

        lat_name, lon_name = _find_lat_lon_names(da.to_dataset(name="v"))
        da = da.sortby(lat_name)
        da = _normalize_lon_to_pm180(da, lon_name)
        da = da.reindex(
            {lat_name: lat_expected, lon_name: lon_expected},
            method="nearest",
            tolerance=tol,
        )

        vals = np.asarray(da.values)
        if vals.ndim == 2:
            finite_count = np.isfinite(vals).astype(np.int16)
        else:
            finite_count = np.sum(np.isfinite(vals), axis=0).astype(np.int16)

    return finite_count >= max(1, int(min_finite_days))


def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Build a reusable sparse-data mask for an ERDDAP dataset from one seed "
            "download window."
        )
    )
    ap.add_argument("--dataset-id", required=True, help="Dataset id from registry/datasets.json")
    ap.add_argument("--datasets-path", type=Path, default=DEFAULT_DATASETS_PATH)
    ap.add_argument("--output", type=Path, default=None, help="Output NPZ path (defaults to source.mask_file)")
    ap.add_argument("--cache-dir", type=Path, default=Path("data/cache/erddap_masks"))
    ap.add_argument("--start-date", required=True, help="Seed period start date YYYY-MM-DD")
    ap.add_argument("--end-date", required=True, help="Seed period end date YYYY-MM-DD")
    ap.add_argument("--min-finite-days", type=int, default=1)
    ap.add_argument("--stride-time", type=int, default=1)
    ap.add_argument("--stride-lat", type=int, default=1)
    ap.add_argument("--stride-lon", type=int, default=1)
    args = ap.parse_args()

    datasets = load_datasets(path=args.datasets_path, validate=True)
    ds_spec = datasets.get(args.dataset_id)
    if not isinstance(ds_spec, dict):
        raise SystemExit(f"Unknown dataset id: {args.dataset_id}")

    source = ds_spec.get("source", {})
    if source.get("type") != "erddap":
        raise SystemExit("Mask builder currently supports only source.type=erddap")

    dataset_key = source.get("dataset_key")
    if not isinstance(dataset_key, str) or dataset_key not in ERDDAP_DATASETS:
        raise SystemExit(f"Invalid/unknown dataset_key for {args.dataset_id}: {dataset_key}")

    grid_id = str(ds_spec.get("grid_id"))
    tile_size = int(ds_spec.get("tile_size", 64))
    grid = _grid_from_id(grid_id, tile_size)

    dataset_spec = ERDDAP_DATASETS[dataset_key]
    dataset_id = str(source.get("dataset_id") or dataset_spec["dataset_id"])
    variable = str(source.get("variable") or dataset_spec["var"])

    out_path = args.output
    if out_path is None:
        mask_file = source.get("mask_file")
        if not isinstance(mask_file, str) or not mask_file:
            raise SystemExit(
                "No --output provided and source.mask_file is missing in dataset registry"
            )
        out_path = Path(mask_file)
    if not out_path.is_absolute():
        out_path = REPO_ROOT / out_path

    nc_path = _download_erddap_full_grid(
        dataset_key=dataset_key,
        dataset_id=dataset_id,
        variable=variable,
        start_date=args.start_date,
        end_date=args.end_date,
        cache_dir=args.cache_dir,
        grid=grid,
        stride_time=args.stride_time,
        stride_lat=args.stride_lat,
        stride_lon=args.stride_lon,
    )
    mask = _build_mask_from_seed(
        nc_path=nc_path,
        grid=grid,
        variable_hint=variable,
        min_finite_days=args.min_finite_days,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out_path,
        data=mask.astype(np.uint8, copy=False),
        deg=np.float64(grid.deg),
        lat_max=np.float64(grid.lat_max),
        lon_min=np.float64(grid.lon_min),
    )

    valid = int(np.count_nonzero(mask))
    total = int(mask.size)
    print(
        f"[ok] wrote mask: {out_path} shape={mask.shape} valid={valid}/{total} ({(valid/total)*100:.4f}%)"
    )


if __name__ == "__main__":
    main()
