#!/usr/bin/env python
"""
Precompute multi-decade climate time series for a small set of locations
using the Open-Meteo ERA5 archive API.

For each location we create a NetCDF file:

    story_climatology/clim_<slug>_<START_YEAR>_<END_YEAR>.nc

Example:

    clim_city_mu_port_louis_1979_2024.nc
    clim_city_gb_london_1979_2024.nc
    clim_city_us_new_york_1979_2024.nc

Each file contains:

    - Daily series (time: daily)
        * t2m_daily_mean_c
        * t2m_daily_min_c
        * t2m_daily_max_c

    - Monthly series (time_monthly: monthly)
        * t2m_monthly_mean_c  (mean of daily mean)
        * t2m_monthly_min_c   (mean of daily min)
        * t2m_monthly_max_c   (mean of daily max)

    - Yearly series (time_yearly: yearly)
        * t2m_yearly_mean_c   (mean of daily mean)

    - Monthly climatologies for two periods (month: 1..12):
        * t2m_monthly_clim_past_mean_c   (past period)
        * t2m_monthly_clim_recent_mean_c (recent period)

Temperatures are in °C (Open-Meteo ERA5 archive already returns °C,
we just keep that and make it explicit in the variable names).
"""

import os
import time
from datetime import datetime, date
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import xarray as xr

# -----------------------
# Configuration
# -----------------------

OUT_DIR = Path("story_climatology")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ERA5 is conventionally used from 1979 onwards
START_YEAR = 1979
END_YEAR = 2024  # fix to a specific year for reproducibility

# Climatology windows (make sure they are inside [START_YEAR, END_YEAR])
# You can tweak these later if you like.
PAST_START, PAST_END = 1980, 1999
RECENT_START, RECENT_END = 2005, 2024

# Locations registry
# slug is used in file names and as a stable identifier
LOCATIONS = [
    {
        "slug": "city_mu_port_louis",
        "name_short": "Port Louis",
        "name_long": "Port Louis, Mauritius",
        "country": "Mauritius",
        "country_code": "MU",
        "lat": -20.16,
        "lon": 57.50,
        "kind": "city",
    },
    {
        "slug": "city_gb_london",
        "name_short": "London",
        "name_long": "London, United Kingdom",
        "country": "United Kingdom",
        "country_code": "GB",
        "lat": 51.5074,
        "lon": -0.1278,
        "kind": "city",
    },
    {
        "slug": "city_us_new_york",
        "name_short": "New York",
        "name_long": "New York City, United States",
        "country": "United States",
        "country_code": "US",
        "lat": 40.7128,
        "lon": -74.0060,
        "kind": "city",
    },
]


# -----------------------
# Open-Meteo helper
# -----------------------

def fetch_openmeteo_daily_block(
    lat: float,
    lon: float,
    start_date: date,
    end_date: date,
    retries: int = 5,
    sleep: int = 5,
) -> xr.Dataset:
    """
    Fetch a daily block (mean/min/max 2m temperature) from the Open-Meteo ERA5 archive.

    Parameters
    ----------
    lat, lon : float
        Location coordinates.
    start_date, end_date : datetime.date
        Inclusive block boundaries.
    retries : int
        Number of retries on errors.
    sleep : int
        Base sleep in seconds for simple backoff.

    Returns
    -------
    xarray.Dataset
        Dataset with variables:
            - t2m_daily_mean_c
            - t2m_daily_min_c
            - t2m_daily_max_c
        and 'time' coordinate (daily).
    """
    base_url = "https://archive-api.open-meteo.com/v1/era5"
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
        "daily": "temperature_2m_mean,temperature_2m_min,temperature_2m_max",
        "timezone": "UTC",
    }

    last_err = None
    for k in range(retries):
        try:
            r = requests.get(base_url, params=params, timeout=60)
            if r.status_code == 429:
                # Rate limit: simple exponential backoff
                wait = sleep * (k + 1)
                print(f"    [warn] 429 Too Many Requests, backing off {wait}s...")
                time.sleep(wait)
                last_err = RuntimeError("429 Too Many Requests")
                continue

            r.raise_for_status()
            j = r.json()

            daily = j.get("daily")
            if daily is None or "time" not in daily:
                raise RuntimeError("Unexpected Open-Meteo response structure (no 'daily' key)")

            dates = pd.to_datetime(daily["time"])
            # Open-Meteo ERA5 already returns °C
            mean_vals = np.array(daily["temperature_2m_mean"], dtype=float)
            min_vals = np.array(daily["temperature_2m_min"], dtype=float)
            max_vals = np.array(daily["temperature_2m_max"], dtype=float)

            da_mean = xr.DataArray(
                mean_vals,
                coords={"time": dates},
                dims=["time"],
                name="t2m_daily_mean_c",
            )
            da_min = xr.DataArray(
                min_vals,
                coords={"time": dates},
                dims=["time"],
                name="t2m_daily_min_c",
            )
            da_max = xr.DataArray(
                max_vals,
                coords={"time": dates},
                dims=["time"],
                name="t2m_daily_max_c",
            )

            ds = xr.Dataset(
                {
                    "t2m_daily_mean_c": da_mean,
                    "t2m_daily_min_c": da_min,
                    "t2m_daily_max_c": da_max,
                }
            )
            return ds

        except Exception as e:
            last_err = e
            wait = sleep * (k + 1)
            print(f"    [warn] Error fetching {start_date}–{end_date}: {e} (retrying in {wait}s)")
            time.sleep(wait)

    raise last_err


def fetch_city_daily_history(
    lat: float,
    lon: float,
    start_year: int = START_YEAR,
    end_year: int = END_YEAR,
    block_size: int = 5,
) -> xr.Dataset:
    """
    Fetch daily ERA5 (via Open-Meteo) for a location for all years in [start_year, end_year],
    in multi-year blocks to keep responses small and be kinder to the API.
    """
    blocks = []
    for y0 in range(start_year, end_year + 1, block_size):
        y1 = min(y0 + block_size - 1, end_year)
        start_date = date(y0, 1, 1)
        end_date = date(y1, 12, 31)
        print(f"  - fetching {y0}-{y1}")
        ds_block = fetch_openmeteo_daily_block(lat, lon, start_date, end_date)
        blocks.append(ds_block)

    ds_all = xr.concat(blocks, dim="time").sortby("time")
    # Drop any duplicate timestamps (just in case)
    ds_all = ds_all.sel(time=~ds_all.indexes["time"].duplicated())
    return ds_all


# -----------------------
# Derived series & climatologies
# -----------------------

def derive_monthly_and_yearly(ds_daily: xr.Dataset):
    """
    From daily dataset, derive monthly and yearly mean series
    (based on t2m_daily_mean_c, t2m_daily_min_c, t2m_daily_max_c).
    """

    # Monthly aggregation (calendar months, at month start)
    monthly_mean = ds_daily["t2m_daily_mean_c"].resample(time="MS").mean()
    monthly_min = ds_daily["t2m_daily_min_c"].resample(time="MS").mean()
    monthly_max = ds_daily["t2m_daily_max_c"].resample(time="MS").mean()

    # Rename dimension so monthly data uses time_monthly
    monthly_mean = monthly_mean.rename(time="time_monthly")
    monthly_min = monthly_min.rename(time="time_monthly")
    monthly_max = monthly_max.rename(time="time_monthly")

    # Yearly aggregation (calendar years, at year start)
    yearly_mean = ds_daily["t2m_daily_mean_c"].resample(time="YS").mean()
    yearly_mean = yearly_mean.rename(time="time_yearly")

    return monthly_mean, monthly_min, monthly_max, yearly_mean


def derive_monthly_climatologies(ds_daily: xr.Dataset):
    """
    Compute monthly climatologies (per calendar month) for two periods:
        - PAST_START..PAST_END
        - RECENT_START..RECENT_END

    Returns two DataArrays with dimension 'month' (1..12):
        past_clim_mean, recent_clim_mean
    """
    years = ds_daily["time"].dt.year

    def climatology_for_period(start, end):
        mask = (years >= start) & (years <= end)
        if not bool(mask.any()):
            return None
        return (
            ds_daily["t2m_daily_mean_c"]
            .sel(time=mask)
            .groupby("time.month")
            .mean("time")
            .rename(month="month")
        )

    past_clim = climatology_for_period(PAST_START, PAST_END)
    recent_clim = climatology_for_period(RECENT_START, RECENT_END)
    return past_clim, recent_clim


# -----------------------
# Precompute per location
# -----------------------

def precompute_for_location(loc: dict):
    slug = loc["slug"]
    lat = float(loc["lat"])
    lon = float(loc["lon"])

    out_path = OUT_DIR / f"clim_{slug}_{START_YEAR}_{END_YEAR}.nc"
    if out_path.exists():
        print(f"[skip] {slug}: {out_path} already exists")
        return

    print(f"[city] {loc['name_long']} ({slug}) at lat={lat}, lon={lon}")

    # 1. Fetch daily history
    ds_daily = fetch_city_daily_history(lat, lon, START_YEAR, END_YEAR)

    # 2. Derive monthly / yearly
    m_mean, m_min, m_max, y_mean = derive_monthly_and_yearly(ds_daily)

    # 3. Climatologies
    past_clim, recent_clim = derive_monthly_climatologies(ds_daily)

    # 4. Build output dataset
    ds_out = xr.Dataset()

    # Daily variables
    ds_out["t2m_daily_mean_c"] = ds_daily["t2m_daily_mean_c"]
    ds_out["t2m_daily_min_c"] = ds_daily["t2m_daily_min_c"]
    ds_out["t2m_daily_max_c"] = ds_daily["t2m_daily_max_c"]

    # Monthly variables (time_monthly dimension)
    ds_out["t2m_monthly_mean_c"] = m_mean
    ds_out["t2m_monthly_min_c"] = m_min
    ds_out["t2m_monthly_max_c"] = m_max

    # Yearly variables (time_yearly dimension)
    ds_out["t2m_yearly_mean_c"] = y_mean

    # Monthly climatologies
    # Only add if they exist (e.g. if window fully or partly inside [START_YEAR, END_YEAR])
    if past_clim is not None:
        ds_out["t2m_monthly_clim_past_mean_c"] = past_clim
    if recent_clim is not None:
        ds_out["t2m_monthly_clim_recent_mean_c"] = recent_clim

    # Metadata / attributes
    ds_out.attrs.update(
        location_slug=slug,
        name_short=loc["name_short"],
        name_long=loc["name_long"],
        country=loc["country"],
        country_code=loc["country_code"],
        latitude=lat,
        longitude=lon,
        kind=loc["kind"],
        source="Open-Meteo ERA5 archive (daily mean/min/max 2m_temperature)",
        created_utc=datetime.utcnow().isoformat() + "Z",
        start_year=START_YEAR,
        end_year=END_YEAR,
        past_period=f"{PAST_START}-{PAST_END}",
        recent_period=f"{RECENT_START}-{RECENT_END}",
    )

    print(f"  -> writing {out_path}")
    ds_out.to_netcdf(out_path, mode="w")
    print(f"  -> done {slug}\n")


def main():
    print(f"Output directory: {OUT_DIR.resolve()}")
    print(f"Years: {START_YEAR}-{END_YEAR}")
    print(f"Past climatology window:   {PAST_START}-{PAST_END}")
    print(f"Recent climatology window: {RECENT_START}-{RECENT_END}")
    print()

    for loc in LOCATIONS:
        precompute_for_location(loc)


if __name__ == "__main__":
    main()
