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

DATA_DIR = Path("story_climatology")

# ERA5 is conventionally used from 1979 onwards
START_YEAR = 1979

# Define window sizes instead of fixed years
PAST_CLIM_YEARS = 10     # e.g. 10 earliest years
RECENT_CLIM_YEARS = 10   # e.g. 10 most recent years

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
# Date helper
# -----------------------

def last_full_quarter_end(today: date | None = None) -> date:
    """Return the last fully completed calendar quarter end date.

    Examples:
      - 2025-12-01 -> 2025-09-30 (Q3 2025)
      - 2026-01-02 -> 2025-12-31 (Q4 2025)
      - 2025-04-10 -> 2025-03-31 (Q1 2025)
    """
    if today is None:
        today = date.today()

    y = today.year
    m = today.month

    if m <= 3:
        # Q1 not finished → last full quarter is Q4 previous year
        return date(y - 1, 12, 31)
    elif m <= 6:
        # Q2 in progress → Q1 complete
        return date(y, 3, 31)
    elif m <= 9:
        # Q3 in progress → Q2 complete
        return date(y, 6, 30)
    else:
        # Q4 in progress → Q3 complete
        return date(y, 9, 30)


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


def fetch_city_daily_history(lat: float, lon: float, start_date: date, end_date: date) -> xr.Dataset:
    """Fetch daily mean/min/max 2m temperature from Open-Meteo ERA5 archive
    for a single point and a given date range.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "daily": ["temperature_2m_mean", "temperature_2m_max", "temperature_2m_min"],
        "timezone": "UTC",
    }

    url = "https://archive-api.open-meteo.com/v1/era5"
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    j = r.json()

    daily = j["daily"]
    times = pd.to_datetime(daily["time"])

    tmean = np.array(daily["temperature_2m_mean"], dtype="float32")
    tmax = np.array(daily["temperature_2m_max"], dtype="float32")
    tmin = np.array(daily["temperature_2m_min"], dtype="float32")

    ds = xr.Dataset(
        data_vars=dict(
            t2m_daily_mean_c=(["time"], tmean),
            t2m_daily_max_c=(["time"], tmax),
            t2m_daily_min_c=(["time"], tmin),
        ),
        coords=dict(time=times),
    )
    return ds


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


def derive_monthly_climatologies(ds_daily: xr.Dataset) -> tuple[xr.DataArray | None, xr.DataArray | None]:
    """Compute past vs recent monthly climatology for daily mean temperature.

    - "Past" = first PAST_CLIM_YEARS years in the record.
    - "Recent" = last RECENT_CLIM_YEARS years in the record.

    If there isn't enough data to form both windows, returns (None, None).
    """
    da = ds_daily["t2m_daily_mean_c"]
    years = da["time"].dt.year

    min_year = int(years.min().item())
    max_year = int(years.max().item())
    n_years = max_year - min_year + 1

    # Require at least PAST + RECENT years + a small buffer (optional)
    min_needed = PAST_CLIM_YEARS + RECENT_CLIM_YEARS
    if n_years < min_needed:
        print(
            f"  [warn] record too short for climatologies: "
            f"{n_years} years, need at least {min_needed}"
        )
        return None, None

    past_start = min_year
    past_end = min_year + PAST_CLIM_YEARS - 1

    recent_end = max_year
    recent_start = max_year - RECENT_CLIM_YEARS + 1

    print(
        f"  [info] climatology windows: "
        f"past={past_start}–{past_end}, recent={recent_start}–{recent_end}"
    )

    # Monthly means from daily
    da_mon = da.resample(time="M").mean()  # monthly means at end-of-month

    # Past climatology: mean by calendar month over the past window
    mask_past = (da_mon["time"].dt.year >= past_start) & (da_mon["time"].dt.year <= past_end)
    mon_past = da_mon.where(mask_past, drop=True)

    if mon_past.time.size == 0:
        past_clim = None
    else:
        past_clim = mon_past.groupby("time.month").mean("time")
        past_clim = past_clim.rename(month="month")
        past_clim = past_clim.assign_coords(month=np.arange(1, 13))

    # Recent climatology
    mask_recent = (da_mon["time"].dt.year >= recent_start) & (da_mon["time"].dt.year <= recent_end)
    mon_recent = da_mon.where(mask_recent, drop=True)

    if mon_recent.time.size == 0:
        recent_clim = None
    else:
        recent_clim = mon_recent.groupby("time.month").mean("time")
        recent_clim = recent_clim.rename(month="month")
        recent_clim = recent_clim.assign_coords(month=np.arange(1, 13))

    return past_clim, recent_clim


# -----------------------
# Check existing files
# -----------------------

def is_existing_file_up_to_date(path: Path, slug: str, target_end: date) -> bool:
    """Return True if an existing NetCDF file is up-to-date for this slug
    and already covers data up to at least target_end.

    Also checks that the required variables are present, and that the
    stored metadata (slug/start_year) matches expectations.
    """
    if not path.exists():
        return False

    try:
        ds = xr.open_dataset(path)
    except Exception as e:
        print(f"  [info] existing file {path} could not be opened: {e}, will recompute")
        return False

    try:
        attrs = ds.attrs

        # 1. Check slug
        if attrs.get("location_slug") != slug:
            print(
                f"  [info] {path} slug mismatch "
                f"(found {attrs.get('location_slug')}, expected {slug})"
            )
            return False

        # 2. Check start_year
        start_year_attr = int(attrs.get("start_year", -1))
        if start_year_attr != START_YEAR:
            print(
                f"  [info] {path} start_year mismatch "
                f"(found {start_year_attr}, expected {START_YEAR})"
            )
            return False

        # 3. Check required variables exist
        required_vars = {
            "t2m_daily_mean_c",
            "t2m_daily_min_c",
            "t2m_daily_max_c",
            "t2m_monthly_mean_c",
            "t2m_monthly_min_c",
            "t2m_monthly_max_c",
            "t2m_yearly_mean_c",
        }
        missing = [v for v in required_vars if v not in ds.variables]
        if missing:
            print(f"  [info] {path} missing required variables: {missing}")
            return False

        # 4. Check coverage up to target_end using attrs["data_end_date"]
        data_end_str = attrs.get("data_end_date")
        if not data_end_str:
            print(f"  [info] {path} missing data_end_date attr")
            return False

        try:
            existing_end = datetime.fromisoformat(data_end_str).date()
        except Exception:
            print(f"  [info] {path} has invalid data_end_date={data_end_str!r}")
            return False

        if existing_end >= target_end:
            print(
                f"  [info] {path} already covers up to {existing_end}, "
                f"which is >= target_end={target_end}, no update needed"
            )
            return True
        else:
            print(
                f"  [info] {path} only covers up to {existing_end}, "
                f"but target_end={target_end}, will recompute"
            )
            return False

    finally:
        ds.close()


# -----------------------
# Precompute per location
# -----------------------

def precompute_for_location(loc: dict, target_end: date):
    slug = loc["slug"]
    lat = float(loc["lat"])
    lon = float(loc["lon"])

    out_path = DATA_DIR / f"clim_{slug}_{START_YEAR}_{target_end.year}.nc"

    if out_path.exists():
        print(f"[check] {slug}: found existing {out_path}")
        if is_existing_file_up_to_date(out_path, slug, target_end):
            print(f"[skip] {slug}: already up-to-date\n")
            return
        else:
            print(f"[recompute] {slug}: existing file is older, will overwrite\n")

    print(
        f"[city] {loc['name_long']} ({slug}) at "
        f"lat={lat}, lon={lon}, target_end={target_end}"
    )

    start_date = date(START_YEAR, 1, 1)
    end_date = target_end

    # 1. Fetch daily history 1979-01-01 → target_end
    ds_daily = fetch_city_daily_history(lat, lon, start_date, end_date)

    # 2. Derive monthly/yearly
    m_mean, m_min, m_max, y_mean = derive_monthly_and_yearly(ds_daily)

    # 3. Dynamic past/recent climatologies
    past_clim, recent_clim = derive_monthly_climatologies(ds_daily)

    # 4. Build output dataset
    ds_out = xr.Dataset()

    ds_out["t2m_daily_mean_c"] = ds_daily["t2m_daily_mean_c"]
    ds_out["t2m_daily_min_c"] = ds_daily["t2m_daily_min_c"]
    ds_out["t2m_daily_max_c"] = ds_daily["t2m_daily_max_c"]

    ds_out["t2m_monthly_mean_c"] = m_mean
    ds_out["t2m_monthly_min_c"] = m_min
    ds_out["t2m_monthly_max_c"] = m_max

    ds_out["t2m_yearly_mean_c"] = y_mean

    if past_clim is not None:
        ds_out["t2m_monthly_clim_past_mean_c"] = past_clim
    if recent_clim is not None:
        ds_out["t2m_monthly_clim_recent_mean_c"] = recent_clim

    # 5. Metadata / attrs
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
        data_end_date=end_date.isoformat(),  # key for up-to-date check
    )

    print(f"  -> writing {out_path}")
    ds_out.to_netcdf(out_path, mode="w")
    print(f"  -> done {slug}\n")


def main():
    print(f"Output directory: {DATA_DIR.resolve()}")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    target_end = last_full_quarter_end()
    print(f"Target end date for this run: {target_end.isoformat()}")
    print()
    for loc in LOCATIONS:
        precompute_for_location(loc, target_end)


if __name__ == "__main__":
    main()
