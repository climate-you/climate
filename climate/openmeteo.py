import streamlit as st
from datetime import datetime, timedelta
import xarray as xr
import requests
import pandas as pd
import numpy as np

# -----------------------------------------------------------
# Helpers to fetch recent data from OpenMeteo
# -----------------------------------------------------------

OPENMETEO_TIMEOUT = 30  # seconds

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_openmeteo_current_temp_c(lat: float, lon: float) -> tuple[float | None, str | None]:
    """
    Returns (temperature_c, iso_time) or (None, None) if unavailable.
    Cached by location for ~1 hour.
    """
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current_weather": True,
        "temperature_unit": "celsius",
        "timezone": "auto",
    }
    try:
        r = requests.get(url, params=params, timeout=20)
        if r.status_code == 429:
            return None, None
        r.raise_for_status()
        j = r.json()
        cw = j.get("current_weather") or {}
        return cw.get("temperature"), cw.get("time")
    except Exception:
        return None, None

@st.cache_data(show_spinner=False)
def fetch_openmeteo_window(
    kind: str,
    lat: float,
    lon: float,
    start_date : datetime.date,
    end_date: datetime.date,
) -> dict | None:
    """
    Fetch a window of data from Open-Meteo.

    kind: "hourly_7d" or "daily_30d" etc.
    start/end_date: we only keep the *dates* in the cache key,
                    so multiple reruns in the same day reuse the same response.

    Returns parsed JSON dict, or None if we hit 429 / network errors.
    """
    # Build Open-Meteo URL – adapt this to your existing params
    base = "https://archive-api.open-meteo.com/v1/era5"
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "timezone": "auto",
    }

    if kind == "hourly_7d":
        params["hourly"] = ["temperature_2m"]
        params["daily"] = [
            "temperature_2m_mean",
        ]
    elif kind == "daily_30d":
        params["daily"] = [
            "temperature_2m_mean",
        ]
    else:
        raise ValueError(f"Unknown Open-Meteo kind: {kind}")

    try:
        r = requests.get(base, params=params, timeout=OPENMETEO_TIMEOUT)
        if r.status_code == 429:
            # Soft failure: log and return None
            st.warning(
                "Live data from Open-Meteo is temporarily rate-limited "
                "(HTTP 429). Recent-window graphs may not be available right now."
            )
            return None
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        st.warning(f"Could not fetch live data right now ({e}).")
        return None


def fetch_recent_7d(slug: str, lat: float, lon: float, end_date: datetime.date) -> xr.Dataset | None:
    """
    Fetch last 7 full days of hourly + daily temps from Open-Meteo ERA5 archive.
    end_date_str is ISO string of the last full day included (YYYY-MM-DD).
    """
    start_date = end_date - timedelta(days=6)
    j = fetch_openmeteo_window("hourly_7d", lat, lon, start_date, end_date)
    if j is None:
        return None
    
    # Hourly
    h = j["hourly"]
    t_h = pd.to_datetime(h["time"])
    temp_h = np.array(h["temperature_2m"], dtype="float32")

    # Daily
    d = j["daily"]
    t_d = pd.to_datetime(d["time"])
    tmean_d = np.array(d["temperature_2m_mean"], dtype="float32")

    ds = xr.Dataset(
        data_vars=dict(
            t_hourly=("time_hourly", temp_h),
            t_daily_mean=("time_daily", tmean_d),
        ),
        coords=dict(
            time_hourly=("time_hourly", t_h),
            time_daily=("time_daily", t_d),
        ),
        attrs={"range": f"{start_date.isoformat()} to {end_date.isoformat()}"},
    )
    return ds


def fetch_recent_30d(slug: str, lat: float, lon: float, end_date: datetime.date) -> xr.Dataset | None:
    """
    Fetch last 30 full days of daily temps from Open-Meteo ERA5 archive.
    """
    start_date = end_date - timedelta(days=29)
    j = fetch_openmeteo_window("daily_30d", lat, lon, start_date, end_date)
    if j is None:
        return None

    d = j["daily"]
    t_d = pd.to_datetime(d["time"])
    tmean_d = np.array(d["temperature_2m_mean"], dtype="float32")

    ds = xr.Dataset(
        data_vars=dict(
            t_daily_mean=("time_daily", tmean_d),
        ),
        coords=dict(
            time_daily=("time_daily", t_d),
        ),
        attrs={"range": f"{start_date.isoformat()} to {end_date.isoformat()}"},
    )
    return ds
