from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict
import time

import numpy as np
import pandas as pd
import requests
import xarray as xr


OPENMETEO_ERA5_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/era5"


def openmeteo_era5_archive_request_json(
    lat: float,
    lon: float,
    start_date: date,
    end_date: date,
    *,
    daily_vars: list[str],
    timeout_s: float = 60.0,
    max_retries: int = 5,
    base_sleep_s: float = 10.0,
    min_backoff_seconds: float = 0.0,
) -> Dict[str, Any]:
    """Fetch raw JSON from Open-Meteo ERA5 archive with retry/backoff."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "daily": daily_vars,
        "timezone": "UTC",
    }

    backoff_floor = max(base_sleep_s, float(min_backoff_seconds or 0.0))
    last_err: Exception | None = None

    for attempt in range(max_retries):
        try:
            r = requests.get(
                OPENMETEO_ERA5_ARCHIVE_URL, params=params, timeout=timeout_s
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            # exponential-ish backoff: floor * 2^attempt
            sleep_s = backoff_floor * (2**attempt)
            time.sleep(sleep_s)

    assert last_err is not None
    raise last_err


def openmeteo_era5_archive_json_to_ds(j: Dict[str, Any]) -> xr.Dataset:
    """Convert Open-Meteo archive JSON to an xarray Dataset with your canonical var names."""
    # This is where you replicate your existing _json_to_ds logic.
    # I’m showing the *shape*; keep your real parsing exactly.
    daily = j.get("daily", {})
    times = pd.to_datetime(daily["time"]).tz_localize(None)

    ds = xr.Dataset(coords={"time": times})

    # Map Open-Meteo field names → your canonical names
    # Keep this mapping consistent with your script’s outputs.
    ds["t2m_daily_mean_c"] = xr.DataArray(
        np.asarray(daily["temperature_2m_mean"], dtype=np.float32), dims=("time",)
    )
    ds["t2m_daily_max_c"] = xr.DataArray(
        np.asarray(daily["temperature_2m_max"], dtype=np.float32), dims=("time",)
    )
    ds["t2m_daily_min_c"] = xr.DataArray(
        np.asarray(daily["temperature_2m_min"], dtype=np.float32), dims=("time",)
    )

    return ds


def fetch_era5_archive_daily_t2m_point(
    lat: float,
    lon: float,
    start_date: date,
    end_date: date,
    *,
    min_backoff_seconds: float = 0.0,
    chunk_years: int = 5,
) -> xr.Dataset:
    """Fetch daily mean/min/max 2m temp for one point, with timeout fallback to chunked requests."""
    daily_vars = ["temperature_2m_mean", "temperature_2m_max", "temperature_2m_min"]

    try:
        j = openmeteo_era5_archive_request_json(
            lat,
            lon,
            start_date,
            end_date,
            daily_vars=daily_vars,
            min_backoff_seconds=min_backoff_seconds,
        )
        return openmeteo_era5_archive_json_to_ds(j)

    except Exception as e:
        msg = str(e)
        # Keep your exact heuristic:
        if ("timeoutReached" not in msg) and ("streaming data" not in msg):
            raise

        print(
            f"  [warn] Open-Meteo timed out for full range {start_date}..{end_date}; "
            f"falling back to chunked fetch..."
        )

        ds_parts: list[xr.Dataset] = []
        cur = pd.Timestamp(start_date)
        end_ts = pd.Timestamp(end_date)

        while cur <= end_ts:
            nxt = (cur + pd.DateOffset(years=chunk_years)) - pd.Timedelta(days=1)
            if nxt > end_ts:
                nxt = end_ts

            s = cur.date()
            ee = nxt.date()
            print(f"  [chunk] requesting {s}..{ee}")

            j_part = openmeteo_era5_archive_request_json(
                lat,
                lon,
                s,
                ee,
                daily_vars=daily_vars,
                min_backoff_seconds=min_backoff_seconds,
            )
            ds_parts.append(openmeteo_era5_archive_json_to_ds(j_part))

            cur = nxt + pd.Timedelta(days=1)

        ds = xr.concat(ds_parts, dim="time").sortby("time")
        _, idx = np.unique(ds["time"].values, return_index=True)
        ds = ds.isel(time=idx)
        return ds
