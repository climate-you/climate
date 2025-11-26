#!/usr/bin/env python
"""
precompute_extremes_openmeteo.py

Offline script to build, for a given location:

- Daily mean / max / min temperature (°C) for a "past" and "recent" window
- Simple heatwave / cold-snap statistics
- "Typical" summer & winter weeks as 7-day patterns (daily max) for past vs recent

Data source:
    Open-Meteo ERA5 archive API:
      https://archive-api.open-meteo.com/v1/era5

The NetCDF schema is designed to match what we planned for ERA5/CDS so the
front-end/story code does not need to care whether data came from CDS or
Open-Meteo.

Example usage (3 past + 3 recent years):

    python precompute_extremes_openmeteo.py \
        --name mauritius \
        --lat -20.2 --lon 57.5 \
        --past-start 1970 --past-end 1972 \
        --recent-start 2019 --recent-end 2021 \
        --out extremes_mauritius.nc
"""

import argparse
from datetime import datetime
import time

import numpy as np
import pandas as pd
import xarray as xr
import requests


# ---------------------------------------------------------
# 1. Open-Meteo archive helpers
# ---------------------------------------------------------

OPENMETEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/era5"


def http_json(url, params, timeout=60, retries=4, backoff_seconds=5.0):
    """
    Simple HTTP GET with JSON response, retrying on 429 and some transient errors.

    - Retries up to `retries` times.
    - On HTTP 429, sleeps with linear backoff: backoff_seconds * (attempt_index+1).
    """
    last_err = None
    for i in range(retries):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            # Handle rate limiting explicitly
            if r.status_code == 429:
                last_err = requests.HTTPError(f"429 Too Many Requests: {r.text}")
                # don't sleep after the last attempt
                if i < retries - 1:
                    sleep_for = backoff_seconds * (i + 1)
                    print(f"[openmeteo] 429 Too Many Requests, sleeping {sleep_for:.1f}s before retry {i+2}/{retries} ...")
                    time.sleep(sleep_for)
                    continue
                else:
                    break

            r.raise_for_status()
            return r.json()

        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
            last_err = e
            if i < retries - 1:
                sleep_for = backoff_seconds * (i + 1)
                print(f"[openmeteo] HTTP error on attempt {i+1}/{retries}: {e}. Sleeping {sleep_for:.1f}s ...")
                time.sleep(sleep_for)
                continue
            else:
                break

    raise last_err if last_err is not None else RuntimeError("Unknown HTTP error")


def fetch_openmeteo_daily_year(lat, lon, year):
    """
    Fetch daily mean, max and min 2m temperature for a single year and location
    using the Open-Meteo ERA5 archive API.

    Returns three pandas Series (tmean, tmax, tmin) in °C, indexed by daily datetime.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": f"{year}-01-01",
        "end_date": f"{year}-12-31",
        "daily": [
            "temperature_2m_mean",
            "temperature_2m_max",
            "temperature_2m_min",
        ],
        # Keep UTC to stay consistent; we can shift later if needed.
        "timezone": "UTC",
    }

    print(f"[openmeteo] Fetching daily ERA5 for {year} at ({lat:.3f}, {lon:.3f}) ...")
    j = http_json(OPENMETEO_ARCHIVE_URL, params=params, timeout=60, retries=4, backoff_seconds=5.0)

    daily = j.get("daily", {})
    if not daily or "time" not in daily:
        raise RuntimeError(f"Open-Meteo daily response missing 'daily' or 'time' for year={year}: {j}")

    time_vals = pd.to_datetime(daily["time"])
    # Open-Meteo already returns °C for these fields
    tmean_vals = np.array(daily.get("temperature_2m_mean", []), dtype=float)
    tmax_vals = np.array(daily.get("temperature_2m_max", []), dtype=float)
    tmin_vals = np.array(daily.get("temperature_2m_min", []), dtype=float)

    if not (len(time_vals) == len(tmean_vals) == len(tmax_vals) == len(tmin_vals)):
        raise RuntimeError(
            f"Length mismatch in Open-Meteo daily data for year={year}: "
            f"{len(time_vals)} times, {len(tmean_vals)} mean, {len(tmax_vals)} max, {len(tmin_vals)} min"
        )

    tmean = pd.Series(tmean_vals, index=time_vals, name="tmean_c")
    tmax = pd.Series(tmax_vals, index=time_vals, name="tmax_c")
    tmin = pd.Series(tmin_vals, index=time_vals, name="tmin_c")

    # Ensure strictly daily frequency; in practice OM should already do this
    tmean = tmean.groupby(tmean.index.normalize()).mean()
    tmax = tmax.groupby(tmax.index.normalize()).mean()
    tmin = tmin.groupby(tmin.index.normalize()).mean()

    return tmean, tmax, tmin


def fetch_daily_for_period_openmeteo(lat, lon, years):
    """
    For a list of years, fetch Open-Meteo ERA5 daily stats and concatenate
    into three Series: tmean, tmax, tmin (°C), indexed by date.
    """
    all_mean = []
    all_max = []
    all_min = []

    for y in years:
        smean, smax, smin = fetch_openmeteo_daily_year(lat, lon, y)
        all_mean.append(smean)
        all_max.append(smax)
        all_min.append(smin)

    tmean = pd.concat(all_mean).sort_index()
    tmax = pd.concat(all_max).sort_index()
    tmin = pd.concat(all_min).sort_index()

    # Defensive: ensure one value per day
    tmean = tmean.groupby(tmean.index.normalize()).mean()
    tmax = tmax.groupby(tmax.index.normalize()).mean()
    tmin = tmin.groupby(tmin.index.normalize()).mean()

    tmean.name = "tmean_c"
    tmax.name = "tmax_c"
    tmin.name = "tmin_c"
    return tmean, tmax, tmin


# ---------------------------------------------------------
# 2. Heatwave / cold-snap detection on daily data
# ---------------------------------------------------------

def detect_events(tseries, threshold, min_length=3, mode="above"):
    """
    Detect contiguous events on a daily series tseries (indexed by date).

    mode:
      - "above": event where tseries > threshold (heatwaves)
      - "below": event where tseries < threshold (cold snaps)

    Returns a list of (start_date, end_date, length_days).
    """
    if mode not in ("above", "below"):
        raise ValueError("mode must be 'above' or 'below'")

    if mode == "above":
        cond = tseries > threshold
    else:
        cond = tseries < threshold

    events = []
    start = None
    prev_date = None

    for date, flag in cond.items():
        if flag and start is None:
            start = date
        elif not flag and start is not None:
            end = prev_date
            length = (end - start).days + 1
            if length >= min_length:
                events.append((start, end, length))
            start = None
        prev_date = date

    if start is not None and prev_date is not None:
        end = prev_date
        length = (end - start).days + 1
        if length >= min_length:
            events.append((start, end, length))

    return events


def summarize_events(events):
    """
    Return a small dict summarizing a list of (start, end, length) events.
    """
    if not events:
        return {"count": 0, "max_length": 0, "total_days": 0}
    lengths = [e[2] for e in events]
    return {
        "count": len(events),
        "max_length": int(max(lengths)),
        "total_days": int(sum(lengths)),
    }


# ---------------------------------------------------------
# 3. "Typical week" from daily data
# ---------------------------------------------------------

def typical_week_from_daily(tseries, months, years):
    """
    Build a "typical week" as a 7-day pattern (daily values) from a daily time series.

    tseries : pandas Series (daily, indexed by datetime)
    months  : list of int months to include (e.g. [6,7,8] for summer)
    years   : list of years to include (int)

    We:
      - filter by given months & years,
      - group by day-of-week (0=Mon ... 6=Sun),
      - take the median per day-of-week.

    Returns a length-7 numpy array [Mon,...,Sun] or None if not enough data.
    """
    mask = (tseries.index.month.isin(months)) & (tseries.index.year.isin(years))
    ts = tseries[mask]
    if ts.empty:
        return None

    df = ts.to_frame("temp")
    df["dow"] = df.index.dayofweek  # 0..6
    typical = df.groupby("dow")["temp"].median().reindex(range(7))
    return typical.values  # shape (7,)


# ---------------------------------------------------------
# 4. Main precompute workflow (Open-Meteo → daily → extremes)
# ---------------------------------------------------------

def precompute_for_location(name, lat, lon, past_start, past_end, recent_start, recent_end, out_path):
    """
    Fetch Open-Meteo ERA5 daily stats for small "past" and "recent" windows, then:

      - daily mean/max/min (past+recent)
      - heatwave & cold-snap summaries
      - typical summer & winter weeks (7 daily max values)
    and write everything to a small NetCDF.
    """
    years_past = list(range(past_start, past_end + 1))
    years_recent = list(range(recent_start, recent_end + 1))

    print(f"[{name}] Past window   : {past_start}-{past_end}")
    print(f"[{name}] Recent window : {recent_start}-{recent_end}")

    # 1. Daily stats for past & recent
    print(f"[{name}] Fetching Open-Meteo ERA5 daily stats for past years ...")
    tmean_past, tmax_past, tmin_past = fetch_daily_for_period_openmeteo(lat, lon, years_past)

    print(f"[{name}] Fetching Open-Meteo ERA5 daily stats for recent years ...")
    tmean_recent, tmax_recent, tmin_recent = fetch_daily_for_period_openmeteo(lat, lon, years_recent)

    # 2. Heatwaves (daily max) & cold snaps (daily min)
    print(f"[{name}] Detecting heatwaves and cold snaps ...")
    hw_threshold = tmax_past.quantile(0.98)
    cs_threshold = tmin_past.quantile(0.1)

    hw_events_past = detect_events(tmax_past, hw_threshold, min_length=3, mode="above")
    hw_events_recent = detect_events(tmax_recent, hw_threshold, min_length=3, mode="above")

    cs_events_past = detect_events(tmin_past, cs_threshold, min_length=3, mode="below")
    cs_events_recent = detect_events(tmin_recent, cs_threshold, min_length=3, mode="below")

    hw_summary_past = summarize_events(hw_events_past)
    hw_summary_recent = summarize_events(hw_events_recent)
    cs_summary_past = summarize_events(cs_events_past)
    cs_summary_recent = summarize_events(cs_events_recent)

    # 3. Typical summer/winter weeks from daily MEAN (to pick seasons) and MAX (for pattern)
    print(f"[{name}] Building typical summer/winter weeks ...")
    monthly_recent_mean = tmean_recent.resample("MS").mean()
    hottest_month = int(monthly_recent_mean.idxmax().month)
    coldest_month = int(monthly_recent_mean.idxmin().month)
    print(f"[{name}] Hottest month (recent): {hottest_month}, coldest: {coldest_month}")

    def season_months(center):
        # e.g. center=7 → [6,7,8]
        return [((center - 2 - 1) % 12) + 1,
                ((center - 1 - 1) % 12) + 1,
                center]

    summer_months = season_months(hottest_month)
    winter_months = season_months(coldest_month)

    typical_summer_past = typical_week_from_daily(tmax_past, summer_months, years_past)
    typical_summer_recent = typical_week_from_daily(tmax_recent, summer_months, years_recent)
    typical_winter_past = typical_week_from_daily(tmax_past, winter_months, years_past)
    typical_winter_recent = typical_week_from_daily(tmax_recent, winter_months, years_recent)

    # 4. Assemble xarray Dataset and write to NetCDF
    print(f"[{name}] Assembling Dataset and writing {out_path} ...")

    ds_out = xr.Dataset()

    # Daily series (°C)
    ds_out["tmean_past"] = xr.DataArray(
        tmean_past.values,
        coords={"date": tmean_past.index},
        dims=["date"],
        attrs={"units": "degC", "description": "Daily mean 2m temperature (past window, Open-Meteo ERA5 archive)"},
    )
    ds_out["tmax_past"] = xr.DataArray(
        tmax_past.values,
        coords={"date": tmax_past.index},
        dims=["date"],
        attrs={"units": "degC", "description": "Daily max 2m temperature (past window, Open-Meteo ERA5 archive)"},
    )
    ds_out["tmin_past"] = xr.DataArray(
        tmin_past.values,
        coords={"date": tmin_past.index},
        dims=["date"],
        attrs={"units": "degC", "description": "Daily min 2m temperature (past window, Open-Meteo ERA5 archive)"},
    )

    ds_out["tmean_recent"] = xr.DataArray(
        tmean_recent.values,
        coords={"date": tmean_recent.index},
        dims=["date"],
        attrs={"units": "degC", "description": "Daily mean 2m temperature (recent window, Open-Meteo ERA5 archive)"},
    )
    ds_out["tmax_recent"] = xr.DataArray(
        tmax_recent.values,
        coords={"date": tmax_recent.index},
        dims=["date"],
        attrs={"units": "degC", "description": "Daily max 2m temperature (recent window, Open-Meteo ERA5 archive)"},
    )
    ds_out["tmin_recent"] = xr.DataArray(
        tmin_recent.values,
        coords={"date": tmin_recent.index},
        dims=["date"],
        attrs={"units": "degC", "description": "Daily min 2m temperature (recent window, Open-Meteo ERA5 archive)"},
    )

    # Heatwave / cold-snap summary scalars
    def add_summary(prefix, summary_dict):
        for key, val in summary_dict.items():
            ds_out[f"{prefix}_{key}"] = xr.DataArray(val)

    add_summary("heatwave_past", hw_summary_past)
    add_summary("heatwave_recent", hw_summary_recent)
    add_summary("coldsnap_past", cs_summary_past)
    add_summary("coldsnap_recent", cs_summary_recent)

    # Typical weeks: 7 daily max values [Mon..Sun]
    dow = np.arange(7)
    if typical_summer_past is not None:
        ds_out["typical_summer_past"] = xr.DataArray(
            typical_summer_past,
            coords={"dow": dow},
            dims=["dow"],
            attrs={
                "units": "degC",
                "description": (
                    "Median daily max 2m temperature for each day-of-week over a "
                    "typical summer week in the past window (Open-Meteo ERA5)"
                ),
            },
        )
    if typical_summer_recent is not None:
        ds_out["typical_summer_recent"] = xr.DataArray(
            typical_summer_recent,
            coords={"dow": dow},
            dims=["dow"],
            attrs={
                "units": "degC",
                "description": (
                    "Median daily max 2m temperature for each day-of-week over a "
                    "typical summer week in the recent window (Open-Meteo ERA5)"
                ),
            },
        )
    if typical_winter_past is not None:
        ds_out["typical_winter_past"] = xr.DataArray(
            typical_winter_past,
            coords={"dow": dow},
            dims=["dow"],
            attrs={
                "units": "degC",
                "description": (
                    "Median daily max 2m temperature for each day-of-week over a "
                    "typical winter week in the past window (Open-Meteo ERA5)"
                ),
            },
        )
    if typical_winter_recent is not None:
        ds_out["typical_winter_recent"] = xr.DataArray(
            typical_winter_recent,
            coords={"dow": dow},
            dims=["dow"],
            attrs={
                "units": "degC",
                "description": (
                    "Median daily max 2m temperature for each day-of-week over a "
                    "typical winter week in the recent window (Open-Meteo ERA5)"
                ),
            },
        )

    # Metadata
    ds_out.attrs.update(
        dict(
            location_name=name,
            latitude=float(lat),
            longitude=float(lon),
            past_window=f"{past_start}-{past_end}",
            recent_window=f"{recent_start}-{recent_end}",
            hottest_month_recent=int(hottest_month),
            coldest_month_recent=int(coldest_month),
            created=datetime.utcnow().isoformat() + "Z",
            data_source="Open-Meteo ERA5 archive API",
        )
    )

    ds_out.to_netcdf(out_path)
    print(f"[{name}] Done. Wrote {out_path}")


# ---------------------------------------------------------
# 5. CLI
# ---------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="Precompute temperature extremes for one location using Open-Meteo ERA5 archive.")
    p.add_argument("--name", required=True, help="Location name (e.g. mauritius, london)")
    p.add_argument("--lat", type=float, required=True)
    p.add_argument("--lon", type=float, required=True)
    p.add_argument("--past-start", type=int, default=1970)
    p.add_argument("--past-end", type=int, default=1972)
    p.add_argument("--recent-start", type=int, default=2019)
    p.add_argument("--recent-end", type=int, default=2021)
    p.add_argument("--out", required=True, help="Output NetCDF path")
    args = p.parse_args()

    precompute_for_location(
        name=args.name,
        lat=args.lat,
        lon=args.lon,
        past_start=args.past_start,
        past_end=args.past_end,
        recent_start=args.recent_start,
        recent_end=args.recent_end,
        out_path=args.out,
    )


if __name__ == "__main__":
    main()
