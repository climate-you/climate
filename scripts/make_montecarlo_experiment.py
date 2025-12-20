#!/usr/bin/env python3
"""
Create Monte Carlo sampling experiments from local ERA5 daily mean NetCDFs.

Input NetCDFs:
  data/mc/era5_daily_t2m_1979-1988_gridX.nc
  data/mc/era5_daily_t2m_2016-2025_gridX.nc

Output:
  data/mc/experiment_01_samples.parquet
  data/mc/experiment_01_samples.meta.json
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _guess_var_t2m(ds: xr.Dataset) -> str:
    # CDS often uses "t2m" for 2m temperature; be defensive.
    for cand in ("t2m", "2m_temperature", "t2m_daily_mean", "t2m_mean"):
        if cand in ds.data_vars:
            return cand
    if len(ds.data_vars) == 1:
        return list(ds.data_vars)[0]
    raise RuntimeError(f"Could not guess 2m temp variable. Vars: {list(ds.data_vars)}")


def _to_celsius(da: xr.DataArray) -> xr.DataArray:
    units = (da.attrs.get("units") or "").lower()
    if units in ("k", "kelvin"):
        out = da - 273.15
        out.attrs["units"] = "degC"
        return out
    # Some files might already be degC.
    return da


def _lon_to_180(lon0_360: np.ndarray) -> np.ndarray:
    # -> [-180, 180)
    lon = np.asarray(lon0_360, dtype="float64")
    return ((lon + 180.0) % 360.0) - 180.0


def _sample_lat_indices_area_weighted(rng: np.random.Generator, lats: np.ndarray, n: int) -> np.ndarray:
    # weight proportional to cos(lat)
    w = np.cos(np.deg2rad(lats))
    w = np.clip(w, 0.0, None)
    w = w / w.sum()
    cdf = np.cumsum(w)
    u = rng.random(n)
    return np.searchsorted(cdf, u, side="right").astype(np.int32)


@dataclass(frozen=True)
class EraSpec:
    name: str
    start_year: int
    end_year: int
    nc_path: str


def _sample_from_ds(
    *,
    ds: xr.Dataset,
    era_name: str,
    era_id: int,
    n: int,
    rng: np.random.Generator,
) -> pd.DataFrame:
    var = _guess_var_t2m(ds)
    da = _to_celsius(ds[var])

    # coords
    lats = da["latitude"].values.astype("float64")
    lons0 = da["longitude"].values.astype("float64")
    lons180 = _lon_to_180(lons0)
    times = pd.to_datetime(da["time"].values)

    n_time = times.shape[0]
    n_lat = lats.shape[0]
    n_lon = lons0.shape[0]

    # Indices: time uniform, lon uniform, lat area-weighted
    time_idx = rng.integers(0, n_time, size=n, dtype=np.int32)
    lon_idx = rng.integers(0, n_lon, size=n, dtype=np.int32)
    lat_idx = _sample_lat_indices_area_weighted(rng, lats, n)

    # Efficient-ish IO: group by time, read each day's 2D slice once
    tvals = np.empty(n, dtype=np.float32)

    order = np.argsort(time_idx)
    time_sorted = time_idx[order]
    lat_sorted = lat_idx[order]
    lon_sorted = lon_idx[order]

    unique_t, start_pos = np.unique(time_sorted, return_index=True)
    # compute stop positions
    stop_pos = np.append(start_pos[1:], time_sorted.size)

    for t_i, s0, s1 in zip(unique_t, start_pos, stop_pos):
        slab = da.isel(time=int(t_i)).values  # (lat, lon)
        # gather in this chunk
        li = lat_sorted[s0:s1]
        lo = lon_sorted[s0:s1]
        tvals_sorted = slab[li, lo].astype(np.float32, copy=False)
        tvals[order[s0:s1]] = tvals_sorted

    df = pd.DataFrame(
        {
            "era": era_name,
            "era_id": np.int8(era_id),
            "time": times[time_idx].astype("datetime64[ns]"),
            "cell_lat": lats[lat_idx].astype(np.float32),
            "cell_lon_0_360": lons0[lon_idx].astype(np.float32),
            "lat": lats[lat_idx].astype(np.float32),
            "lon": lons180[lon_idx].astype(np.float32),
            "t_c": tvals,
        }
    )

    return df


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid-deg", type=float, default=1.0)
    ap.add_argument("--n-samples", type=int, default=50_000, help="Total samples (split evenly across eras)")
    ap.add_argument("--experiment-id", type=int, default=1)
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--shuffle-first", type=int, default=200, help="Only shuffle first K rows in playback order (for varying early detail)")
    ap.add_argument("--out-dir", type=Path, default=Path("data/mc"))
    args = ap.parse_args()

    out_dir = args.out_dir
    _ensure_dir(out_dir)

    n_each = args.n_samples // 2
    rng = np.random.default_rng(args.seed)

    nc_past = out_dir / f"era5_daily_t2m_1979-1988_grid{args.grid_deg}.nc"
    nc_recent = out_dir / f"era5_daily_t2m_2016-2025_grid{args.grid_deg}.nc"
    if not nc_past.exists() or not nc_recent.exists():
        raise SystemExit(
            f"Missing inputs.\nExpected:\n  {nc_past}\n  {nc_recent}\nRun download_era5_daily_t2m_cds.py first."
        )

    print(f"[open] {nc_past}")
    ds_past = xr.open_mfdataset(
       [out_dir / f"era5_daily_t2m_{y}_grid{args.grid_deg}.nc" for y in range(1979, 1989)],
        combine="by_coords",
    )
    print(f"[open] {nc_recent}")
    ds_recent = xr.open_mfdataset(
       [out_dir / f"era5_daily_t2m_{y}_grid{args.grid_deg}.nc" for y in range(2016, 2025)],
        combine="by_coords",
    )

    print(f"[sample] {n_each} past + {n_each} recent (seed={args.seed})")
    df_past = _sample_from_ds(ds=ds_past, era_name="past", era_id=0, n=n_each, rng=rng)
    df_recent = _sample_from_ds(ds=ds_recent, era_name="recent", era_id=1, n=n_each, rng=rng)

    # Interleave (past/recent alternating) so both eras appear early in the animation
    df_past["__k"] = np.arange(len(df_past), dtype=np.int32)
    df_recent["__k"] = np.arange(len(df_recent), dtype=np.int32)

    merged = []
    for i in range(max(len(df_past), len(df_recent))):
        if i < len(df_past):
            merged.append(df_past.iloc[i])
        if i < len(df_recent):
            merged.append(df_recent.iloc[i])

    df = pd.DataFrame(merged).reset_index(drop=True)
    df.drop(columns=["__k"], inplace=True, errors="ignore")

    # Playback order: shuffle only first K
    K = int(args.shuffle_first)
    perm = np.arange(len(df), dtype=np.int32)
    if K > 1:
        perm_first = perm[:K].copy()
        rng.shuffle(perm_first)
        perm[:K] = perm_first

    df = df.iloc[perm].reset_index(drop=True)
    df.insert(0, "seq", np.arange(len(df), dtype=np.int32))
    df["detail"] = df["seq"] < K

    out_parquet = out_dir / f"experiment_{args.experiment_id:02d}_samples.parquet"
    out_meta = out_dir / f"experiment_{args.experiment_id:02d}_samples.meta.json"

    print(f"[write] {out_parquet} ({len(df)} rows)")
    df.to_parquet(out_parquet, index=False)

    meta = {
        "experiment_id": args.experiment_id,
        "seed": args.seed,
        "shuffle_first": K,
        "n_samples_total": int(len(df)),
        "grid_deg": float(args.grid_deg),
        "eras": [
            asdict(EraSpec("past", 1979, 1988, str(nc_past))),
            asdict(EraSpec("recent", 2016, 2025, str(nc_recent))),
        ],
        "variable": "2m_temperature",
        "statistic": "daily_mean",
        "units": "degC",
    }
    out_meta.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"[meta]  {out_meta}")


if __name__ == "__main__":
    main()
