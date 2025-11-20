#!/usr/bin/env python
"""
precompute.py

Precompute ERA5 monthly 2m temperature for a region and year range,
using earthkit + CDS, and save as NetCDF.

Example:
    python precompute.py \
        --area "60 -20 20 40" \
        --year-start 1975 --year-end 2024 \
        --out data/era5_t2m_monthly_1975_2024_box.nc
"""

import argparse
from pathlib import Path

import numpy as np
import xarray as xr
import earthkit.data as ekd


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument(
        "--area",
        type=str,
        default="90 -180 -90 180",
        help="Bounding box [N W S E] in degrees, e.g. '60 -20 20 40' (default: global)",
    )
    p.add_argument(
        "--year-start",
        type=int,
        required=True,
        help="First year to include, e.g. 1975",
    )
    p.add_argument(
        "--year-end",
        type=int,
        required=True,
        help="Last year to include, e.g. 2024",
    )
    p.add_argument(
        "--out",
        type=str,
        required=True,
        help="Output NetCDF path, e.g. data/era5_t2m_monthly_1975_2024_box.nc",
    )
    return p.parse_args()


def main():
    args = parse_args()

    N, W, S, E = map(float, args.area.split())
    years = list(range(args.year_start, args.year_end + 1))

    print(f"Precomputing ERA5 monthly 2m temperature")
    print(f"  Area: N={N}, W={W}, S={S}, E={E}")
    print(f"  Years: {years[0]}–{years[-1]}")
    print(f"  Output: {args.out}")

    # You need a working CDS account + ~/.cdsapirc or equivalent
    # earthkit will use your configured cache (EARTHKIT_CACHE_HOME) automatically.
    request = {
        "product_type": "monthly_averaged_reanalysis",
        "variable": "2m_temperature",
        "year": [str(y) for y in years],
        "month": [f"{m:02d}" for m in range(1, 13)],
        "time": "00:00",
        "area": [N, W, S, E],
        "format": "netcdf",
    }

    print("Requesting data from CDS via earthkit...")
    ds = ekd.from_source("cds", "reanalysis-era5-single-levels-monthly-means", request)

    # Convert to xarray Dataset
    print("Converting to xarray...")
    xr_ds = ds.to_xarray()

    # xr_ds should contain t2m in Kelvin; convert to °C and rename
    if "t2m" not in xr_ds.data_vars:
        raise KeyError(f"'t2m' variable not found in dataset data_vars={list(xr_ds.data_vars)}")

    t2m_K = xr_ds["t2m"]
    t2m_C = t2m_K - 273.15
    t2m_C = t2m_C.rename("t2m_mon_mean_c")
    t2m_C.attrs["units"] = "degC"
    t2m_C.attrs["long_name"] = "2m temperature monthly mean (°C)"

    # Build a clean output dataset with just what we need
    out_ds = xr.Dataset({"t2m_mon_mean_c": t2m_C})
    # Keep coordinates: time, latitude, longitude
    # You can optionally drop unused variables like 'expver' if present:
    for v in list(out_ds.data_vars):
        if v not in ("t2m_mon_mean_c",):
            out_ds = out_ds.drop_vars(v)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Writing NetCDF to {out_path} ...")
    out_ds.to_netcdf(out_path)

    print("Done.")


if __name__ == "__main__":
    main()
