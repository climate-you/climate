import time
import random
import requests
from datetime import date

import xarray as xr
import numpy as np
import pandas as pd


def fetch_era5_archive_daily_t2m_point(
    lat: float,
    lon: float,
    start_date: date,
    end_date: date,
    *,
    min_backoff_seconds: float = 0.0,
) -> xr.Dataset:
    """Fetch daily mean/min/max 2m temperature from Open-Meteo ERA5 archive
    for a single point and a given date range, with simple retry/backoff.

    min_backoff_seconds acts as a floor for backoff sleeps (useful to align with --min-gap).
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
    max_retries = 5
    base_sleep = 10.0

    def _json_to_ds(j: dict) -> xr.Dataset:
        daily = j["daily"]
        times = pd.to_datetime(daily["time"])

        tmean = np.array(daily["temperature_2m_mean"], dtype="float32")
        tmax = np.array(daily["temperature_2m_max"], dtype="float32")
        tmin = np.array(daily["temperature_2m_min"], dtype="float32")

        return xr.Dataset(
            data_vars=dict(
                t2m_daily_mean_c=(["time"], tmean),
                t2m_daily_max_c=(["time"], tmax),
                t2m_daily_min_c=(["time"], tmin),
            ),
            coords=dict(time=times),
        )

    def _request_json(s: date, e: date) -> dict:
        consecutive_429 = 0
        p = dict(params)
        p["start_date"] = s.isoformat()
        p["end_date"] = e.isoformat()

        base_sleep = 10.0
        backoff_floor = max(
            base_sleep, float(min_backoff_seconds or 0.0)
        )  # used only for 429

        last_err: Exception | None = None
        for attempt in range(max_retries):
            try:
                r = requests.get(url, params=p, timeout=60)
                if r.status_code == 429:
                    consecutive_429 += 1
                    last_err = requests.HTTPError("429 Too Many Requests", response=r)
                    wait = backoff_floor * (2**attempt)
                    jitter = random.uniform(0.0, min(0.4, 0.10 * backoff_floor))
                    time.sleep(wait + jitter)
                    if consecutive_429 >= 3:
                        # global cooldown to let the bucket refill
                        time.sleep(120)  # 2 minutes
                    continue

                r.raise_for_status()

                body = r.text or ""
                # Open-Meteo sometimes returns: "Unexpected error while streaming data: timeoutReached"
                if (
                    "timeoutReached" in body
                    or "Unexpected error while streaming data" in body
                ):
                    raise requests.RequestException(
                        f"Open-Meteo backend timeout: {body[:200]!r}"
                    )

                try:
                    return r.json()
                except ValueError as ve:
                    raise requests.RequestException(
                        f"JSON decode failed: status={r.status_code}, "
                        f"content_type={r.headers.get('Content-Type')!r}, "
                        f"body_preview={body[:200]!r}"
                    ) from ve

            except requests.RequestException as ex:
                last_err = ex
                is_429 = (
                    (r.status_code == 429) if "r" in locals() else False
                )  # or set a flag explicitly
                floor = (
                    backoff_floor if is_429 else base_sleep
                )  # don't use --min-gap floor for non-429
                wait = floor * (2**attempt)
                jitter = random.uniform(0.0, min(0.4, 0.10 * floor))
                time.sleep(wait + jitter)

        raise last_err if last_err is not None else RuntimeError("request failed")

    # IMPORTANT: backoff starts at least at min_backoff_seconds (e.g. --min-gap)
    backoff_floor = max(base_sleep, float(min_backoff_seconds or 0.0))

    last_err: Exception | None = None

    try:
        j = _request_json(start_date, end_date)
        return _json_to_ds(j)
    except Exception as e:
        msg = str(e)
        if ("timeoutReached" not in msg) and ("streaming data" not in msg):
            raise

        print(
            f"  [warn] Open-Meteo timed out for full range {start_date}..{end_date}; "
            f"falling back to chunked fetch..."
        )

        # 5-year chunks are a good compromise: fewer timeouts, not too many requests.
        chunk_years = 5

        ds_parts: list[xr.Dataset] = []
        cur = pd.Timestamp(start_date)
        end_ts = pd.Timestamp(end_date)

        while cur <= end_ts:
            # inclusive chunk end
            nxt = (cur + pd.DateOffset(years=chunk_years)) - pd.Timedelta(days=1)
            if nxt > end_ts:
                nxt = end_ts

            s = cur.date()
            ee = nxt.date()

            print(f"  [chunk] requesting {s}..{ee}")

            j_part = _request_json(s, ee)
            ds_parts.append(_json_to_ds(j_part))

            cur = nxt + pd.Timedelta(days=1)

        ds = xr.concat(ds_parts, dim="time")
        ds = ds.sortby("time")
        # Drop any duplicates at boundaries (defensive)
        _, idx = np.unique(ds["time"].values, return_index=True)
        ds = ds.isel(time=idx)

        return ds
