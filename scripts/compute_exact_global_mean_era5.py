#!/usr/bin/env python3
"""
Compute exact area-weighted global mean near-surface (2m) air temperature
from local ERA5 daily mean NetCDFs (per-year files), and the exact delta
between two eras.

Expected inputs (per-year):
  data/mc/era5_daily_t2m_<YEAR>_grid<GRID>.nc

Example:
  python scripts/compute_exact_global_mean_era5.py --grid-deg 1.0 \
    --in-dir data/mc --past 1979-1988 --recent 2016-2025 --out data/mc/exact_global_mean_grid1.0.json
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

import numpy as np
import xarray as xr


@dataclass
class EraResult:
    era: str
    start_year: int
    end_year: int
    grid_deg: float
    n_days: int
    mean_c: float


def _parse_era(s: str) -> tuple[int, int]:
    s = s.strip()
    if "-" not in s:
        y = int(s)
        return y, y
    a, b = s.split("-", 1)
    return int(a), int(b)


def _find_var_and_dims(ds: xr.Dataset) -> tuple[xr.DataArray, str]:
    """
    Your downloaded files look like:
      dims: (valid_time, latitude, longitude)
      var:  t2m
    But we make this robust.
    """
    # Prefer common names
    for name in ("t2m", "2t", "temperature_2m", "t"):
        if name in ds.data_vars:
            return ds[name], name

    # Fallback: pick first 3D variable
    for name, da in ds.data_vars.items():
        if set(da.dims) >= {"latitude", "longitude"} and len(da.dims) == 3:
            return da, name

    raise RuntimeError(
        f"Could not find a suitable 3D temperature variable. data_vars={list(ds.data_vars)}"
    )


def _detect_time_dim(da: xr.DataArray) -> str:
    # Your file uses valid_time
    for cand in ("valid_time", "time", "date"):
        if cand in da.dims:
            return cand
    # fallback: first dim that's not lat/lon
    for d in da.dims:
        if d not in ("latitude", "longitude"):
            return d
    raise RuntimeError(f"Could not detect time dim from dims={da.dims}")


def _to_celsius(da: xr.DataArray) -> xr.DataArray:
    units = str(da.attrs.get("units", "")).strip().lower()
    if "degc" in units or "c" == units:
        return da
    if "k" in units or "kelvin" in units:
        return da - 273.15

    # If units missing, infer from typical magnitude
    # Kelvin daily mean will almost always be > 150.
    v = float(da.isel({da.dims[0]: 0, "latitude": 0, "longitude": 0}).values)
    if v > 150.0:
        return da - 273.15
    return da


def _iter_year_files(in_dir: Path, years: Iterable[int], grid_deg: float) -> list[Path]:
    files = []
    for y in years:
        fp = in_dir / f"era5_daily_t2m_{y}_grid{grid_deg}.nc"
        if not fp.exists():
            raise FileNotFoundError(f"Missing input file: {fp}")
        files.append(fp)
    return files


def compute_exact_era_mean(in_dir: Path, era_label: str, grid_deg: float) -> EraResult:
    y0, y1 = _parse_era(era_label)
    years = list(range(y0, y1 + 1))
    files = _iter_year_files(in_dir, years, grid_deg)

    total_sum = 0.0  # sum of daily global means over all days
    total_days = 0

    # We'll compute global mean per day: weighted mean over lat/lon,
    # then accumulate over time. Each day counts equally (daily mean dataset).
    for fp in files:
        ds = xr.open_dataset(fp)

        da, varname = _find_var_and_dims(ds)
        da_c = _to_celsius(da)

        time_dim = _detect_time_dim(da_c)

        lat = ds["latitude"].astype("float64")
        w = np.cos(np.deg2rad(lat))
        w = xr.DataArray(w, coords={"latitude": lat}, dims=("latitude",))

        # daily global mean time series
        gm = da_c.weighted(w).mean(("latitude", "longitude"))

        # Accumulate in float64
        total_sum += float(gm.sum(dtype=np.float64).values)
        total_days += int(gm.sizes[time_dim])

        ds.close()

    mean_c = total_sum / total_days
    return EraResult(
        era=era_label,
        start_year=y0,
        end_year=y1,
        grid_deg=float(grid_deg),
        n_days=int(total_days),
        mean_c=float(mean_c),
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in-dir", type=Path, default=Path("data/mc"))
    ap.add_argument("--grid-deg", type=float, default=1.0)
    ap.add_argument("--past", type=str, default="1979-1988")
    ap.add_argument("--recent", type=str, default="2016-2025")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    in_dir = args.in_dir
    grid = float(args.grid_deg)

    past = compute_exact_era_mean(in_dir, args.past, grid)
    recent = compute_exact_era_mean(in_dir, args.recent, grid)

    out = {
        "grid_deg": grid,
        "past": asdict(past),
        "recent": asdict(recent),
        "delta_c": float(recent.mean_c - past.mean_c),
    }

    print(json.dumps(out, indent=2))

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(f"[write] {args.out}")


if __name__ == "__main__":
    main()
