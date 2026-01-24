#!/usr/bin/env python
"""
Precompute coastal/ocean metrics per city slug and cache them to disk.

Outputs:
  data/story_ocean/ocean_<slug>.nc

This is intentionally separate from Streamlit. Network access (ERDDAP) can be slow/fragile
on some networks; precompute isolates that complexity and allows VPN usage + retries.

Metrics (Phase 1):
- OISST v2.1 daily SST (ERDDAP):
    * annual SST anomaly (vs 1981–2010 baseline, daily climatology by DOY)
    * annual count of SST hot-days (above baseline P90 by DOY)
- Coral Reef Watch DHW daily (ERDDAP):
    * annual max DHW
    * annual days with DHW >= 4
    * annual days with DHW >= 8
"""

import os
import argparse
import time
from pathlib import Path
from datetime import date, datetime
from typing import Optional, Tuple
from urllib.parse import quote

import numpy as np
import pandas as pd
import requests
import xarray as xr

from climate.io import discover_locations

# -------------------------
# Paths
# -------------------------

DEFAULT_CLIM_DIR = "data/story_climatology"
DEFAULT_OUT_DIR = "data/story_ocean"
CACHE_DIR = Path("data") / "cache" / "ocean"

# -----------------------------------------------------------------------------
# ERDDAP dataset specs (spike learnings live here, not in our heads)
# -----------------------------------------------------------------------------
ERDDAP_DATASETS = {
    "oisst_sst_v21_daily": {
        "dataset_id": "ncdcOisst21Agg_LonPM180",
        "var": "sst",
        "dataset_start": "1981-09-01",
        # IMPORTANT: OISST sst uses a zlev axis; constrain it explicitly
        "dims": ["time", "zlev", "latitude", "longitude"],
        "fixed": {"zlev": 0.0},
        # OISST time stamps are at 12:00Z
        "time_hms": "12:00:00Z",
        # Longitude convention for this dataset id is [-180, 180]
        "lon_mode": "pm180",
        # Common coord column names returned by ERDDAP CSV
        "lat_col_candidates": ["latitude", "lat"],
        "lon_col_candidates": ["longitude", "lon"],
    },
    "crw_dhw_daily": {
        "dataset_id": "noaacrwdhwDaily",
        "var": "degree_heating_week",
        # CRW DHW uses daily time at 12:00Z (as observed from curl)
        "dims": ["time", "latitude", "longitude"],
        "time_hms": "12:00:00Z",
        "dataset_start": "1985-03-25",
        # Longitude convention: degrees_east (your curl shows 57.375 etc.); keep as-is
        "lon_mode": "east",
        "lat_col_candidates": ["latitude", "lat"],
        "lon_col_candidates": ["longitude", "lon"],
        # Operational note: large multi-year requests often yield 500/502; use yearly chunks
        "recommended_block_years": 1,
    },
}

# -------------------------
# Dataset constants
# -------------------------

# OISST v2.1 daily via ERDDAP
OISST_BASES = [
    "https://coastwatch.pfeg.noaa.gov/erddap",
    "https://upwell.pfeg.noaa.gov/erddap",
]

# CRW DHW daily via ERDDAP
CRW_BASE = "https://coastwatch.noaa.gov/erddap"
CRW_DATASET_ID = "noaacrwdhwDaily"
CRW_VAR = "degree_heating_week"
CRW_START = "1985-03-25"  # dataset axis minimum observed

# Baseline for anomalies / thresholds
BASELINE_START = "1981-01-01"
BASELINE_END = "2010-12-31"

# Default DHW box: half-width degrees (=> 0.1° x 0.1° box when 0.05)
DEFAULT_DHW_BOX_HALF_DEG = 0.05

# SST anomaly map (cached gridded anomaly around the city, for left-side map export)
DEFAULT_SST_MAP_SPAN_DEG = 5.0
DEFAULT_SST_MAP_TIME_STRIDE = 30  # ~monthly sampling (daily index stride)
DEFAULT_SST_MAP_LATLON_STRIDE = 2  # subsample grid
RECENT_START = "2016-01-01"
RECENT_CAP_END = "2025-12-31"

# -------------------------
# Helpers
# -------------------------


def _lon_pm180(lon: float) -> float:
    lon_q = lon
    if lon_q > 180:
        lon_q -= 360
    if lon_q < -180:
        lon_q += 360
    return lon_q


def _ensure_dir(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)


def _sleep_seconds(attempt: int, base: float = 1.0) -> float:
    jitter = 0.25 * np.random.random()
    return base * (2**attempt) + jitter


def download_to(
    url: str,
    path: Path,
    *,
    timeout: Tuple[int, int] = (30, 300),
    retries: int = 6,
    label: str = "",
) -> Path:
    """
    Download URL -> file with caching + retries.
    timeout=(connect_seconds, read_seconds)
    """
    _ensure_dir(path)
    if path.exists() and path.stat().st_size > 0:
        return path

    last_err: Optional[Exception] = None
    for attempt in range(retries):
        try:
            if label:
                print(
                    f"{label} Downloading (attempt {attempt+1}/{retries}) -> {path.name}"
                )
            r = requests.get(url, timeout=timeout)
            r.raise_for_status()
            path.write_bytes(r.content)
            return path

        except requests.HTTPError as e:
            last_err = e
            status = e.response.status_code if e.response is not None else None
            if status == 404 and label and e.response is not None:
                # ERDDAP often includes the real reason in the body
                body = (e.response.text or "").strip().replace("\n", " ")
                print(f"{label} 404 body: {body[:400]}")
            wait = _sleep_seconds(attempt, base=1.0)
            if label:
                print(
                    f"{label} Download failed: HTTPError {status} (sleep {wait:.1f}s)"
                )
            time.sleep(wait)

        except Exception as e:
            last_err = e
            wait = _sleep_seconds(attempt, base=1.0)
            if label:
                print(
                    f"{label} Download failed: {type(e).__name__}: {e} (sleep {wait:.1f}s)"
                )
            time.sleep(wait)

    raise RuntimeError(f"Failed to download after {retries} attempts: {last_err}")


def _pick_first_present(cols: list[str], candidates: list[str]) -> str | None:
    s = set(cols)
    for c in candidates:
        if c in s:
            return c
    return None


def build_erddap_griddap_query_from_spec(
    spec: dict,
    *,
    a_date: str,
    b_date: str,
    lat0: float,
    lat1: float,
    lon0: float,
    lon1: float,
    stride_time: int = 1,
    stride_lat: int = 1,
    stride_lon: int = 1,
) -> str:
    """
    Build a griddap constraint string in the correct dimension order for the variable,
    including any required fixed dimensions (e.g. zlev=0.0).

    a_date/b_date are YYYY-MM-DD (no time part). Spec controls time HH:MM:SSZ.
    """
    var = spec["var"]
    dims = spec["dims"]
    fixed = spec.get("fixed", {})
    time_hms = spec.get("time_hms", "00:00:00Z")

    # Build one bracketed constraint per dim, in order.
    parts: list[str] = []

    for dim in dims:
        if dim == "time":
            parts.append(
                f"[({a_date}T{time_hms}):{int(stride_time)}:({b_date}T{time_hms})]"
            )
        elif dim in fixed:
            parts.append(f"[({fixed[dim]})]")
        elif dim in ("latitude", "lat"):
            parts.append(f"[({lat0}):{int(stride_lat)}:({lat1})]")
        elif dim in ("longitude", "lon"):
            parts.append(f"[({lon0}):{int(stride_lon)}:({lon1})]")
        else:
            # If we ever add a dataset with a new dim, we must encode how to constrain it.
            raise RuntimeError(
                f"Unhandled ERDDAP dim '{dim}' for var '{var}'. Update spec/query builder."
            )

    return var + "".join(parts)


def erddap_griddap_url(base: str, dataset_id: str, query: str, ext: str) -> str:
    """
    Build {base}/griddap/{dataset_id}.{ext}?{query}
    Query is URL-encoded but keeps ERDDAP bracket syntax readable.
    """
    safe = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_[]():,.-TZ"
    q = quote(query, safe=safe)
    return f"{base}/griddap/{dataset_id}.{ext}?{q}"


def _http_status(err: Exception) -> int | None:
    try:
        if isinstance(err, requests.HTTPError) and err.response is not None:
            return int(err.response.status_code)
    except Exception:
        return None
    return None


def read_erddap_csv(path: Path) -> pd.DataFrame:
    """
    ERDDAP CSV: header row, then units row. Skip units row.
    """
    return pd.read_csv(path, skiprows=[1])


def _year_blocks(start: str, end: str, block_years: int):
    y0 = int(start[:4])
    y1 = int(end[:4])
    for y in range(y0, y1 + 1, block_years):
        a = f"{y:04d}-01-01"
        b = f"{min(y + block_years - 1, y1):04d}-12-31"
        a = max(a, start)
        b = min(b, end)
        yield a, b


def _drop_feb29(s: pd.Series) -> pd.Series:
    idx = pd.DatetimeIndex(s.index)
    mask = ~((idx.month == 2) & (idx.day == 29))
    return s.loc[mask]


# -------------------------
# OISST SST fetch + metrics
# -------------------------


def fetch_oisst_daily_sst_point(
    lat: float, lon: float, start: str, end: str
) -> pd.Series:
    """
    Fetch OISST daily SST via ERDDAP (Spike-style robust approach):

    - Request a small bbox around the target point.
    - Then pick the nearest (lat, lon) row per timestamp locally.

    IMPORTANT:
    Some ERDDAP griddap datasets have latitude axis descending.
    ERDDAP expects range constraints to follow the axis order; otherwise it can return
    404 "no matching results". So we try both lat-range orders (and lon-range orders
    as a safeguard) when we hit a 404.
    """
    lon_pm = _lon_pm180(lon)

    half = 0.26
    lat0, lat1 = lat - half, lat + half
    lon0, lon1 = lon_pm - half, lon_pm + half

    spec = ERDDAP_DATASETS["oisst_sst_v21_daily"]

    # Clamp to dataset availability (don’t force callers to remember dataset starts)
    start = max(start, spec.get("dataset_start", start))

    def build_query(
        a: str, b: str, la0: float, la1: float, lo0: float, lo1: float
    ) -> str:
        return build_erddap_griddap_query_from_spec(
            spec,
            a_date=a,
            b_date=b,
            lat0=la0,
            lat1=la1,
            lon0=lo0,
            lon1=lo1,
        )

    series_parts = []
    for a, b in _year_blocks(start, end, block_years=5):
        ok = False
        last_err: Optional[Exception] = None

        # try lat order normal then flipped; lon normal then flipped (lon flip is rarely needed)
        variants = [
            (lat0, lat1, lon0, lon1),
            (lat1, lat0, lon0, lon1),
            (lat0, lat1, lon1, lon0),
            (lat1, lat0, lon1, lon0),
        ]

        dataset_id = spec["dataset_id"]
        for base in OISST_BASES:
            for la0, la1, lo0, lo1 in variants:
                query = build_query(a, b, la0, la1, lo0, lo1)
                url = erddap_griddap_url(base, dataset_id, query, "csv")
                cache_path = (
                    CACHE_DIR
                    / "oisst"
                    / f"oisst_{dataset_id}_{lat:.4f}_{lon:.4f}_{a}_{b}.csv"
                )

                try:
                    download_to(
                        url,
                        cache_path,
                        retries=6,
                        timeout=(30, 300),
                        label=f"[OISST {a[:4]}]",
                    )
                    df = read_erddap_csv(cache_path)

                    tcol = "time" if "time" in df.columns else df.columns[0]
                    df[tcol] = pd.to_datetime(df[tcol], utc=True, errors="coerce")
                    df = df.dropna(subset=[tcol])

                    var = spec["var"]
                    if var not in df.columns:
                        raise RuntimeError(
                            f"OISST CSV missing '{var}' column; columns={list(df.columns)}"
                        )

                    lat_col = _pick_first_present(
                        list(df.columns),
                        spec.get("lat_col_candidates", ["latitude", "lat"]),
                    )
                    lon_col = _pick_first_present(
                        list(df.columns),
                        spec.get("lon_col_candidates", ["longitude", "lon"]),
                    )
                    if lat_col is None or lon_col is None:
                        raise RuntimeError(
                            f"OISST CSV missing lat/lon columns; columns={list(df.columns)}"
                        )

                    df["d2"] = (df[lat_col] - lat) ** 2 + (df[lon_col] - lon_pm) ** 2
                    df = df.sort_values("d2").drop_duplicates(
                        subset=[tcol], keep="first"
                    )

                    s = pd.Series(df[var].values, index=pd.to_datetime(df[tcol].values))
                    s = s.sort_index()
                    s = s[~s.index.duplicated(keep="first")]
                    s.name = "sst_c"
                    series_parts.append(s)

                    ok = True
                    break

                except Exception as e:
                    last_err = e
                    # If it's a 404, try next variant/base; otherwise also try (since PFEL can be flaky).
                    # But 404 is the main signal for "bad constraint ordering / no matches".
                    continue

            if ok:
                break

        if not ok:
            raise RuntimeError(f"OISST failed for {a}..{b}. Last error: {last_err}")

    sst = pd.concat(series_parts).sort_index()
    sst = sst[~sst.index.duplicated(keep="first")]
    sst = sst.dropna()
    return sst


def daily_climatology_mean_p90(
    s_daily: pd.Series, baseline_start: str, baseline_end: str
) -> tuple[pd.Series, pd.Series]:
    s = _drop_feb29(s_daily)
    base = s.loc[
        (s.index >= pd.Timestamp(baseline_start))
        & (s.index <= pd.Timestamp(baseline_end))
    ]
    if len(base) < 365 * 5:
        raise RuntimeError("Not enough baseline data to compute SST climatology.")
    doy = base.index.dayofyear
    df = pd.DataFrame({"v": base.values, "doy": doy})
    clim_mean = df.groupby("doy")["v"].mean()
    clim_p90 = df.groupby("doy")["v"].quantile(0.9)
    return clim_mean, clim_p90


def annual_group(s: pd.Series, how: str) -> pd.Series:
    y = s.index.year
    if how == "mean":
        return s.groupby(y).mean()
    if how == "sum":
        return s.groupby(y).sum()
    if how == "max":
        return s.groupby(y).max()
    raise ValueError(how)


def compute_sst_anom_and_hotdays(sst_daily: pd.Series) -> tuple[pd.Series, pd.Series]:
    sst = _drop_feb29(sst_daily)
    clim_mean, clim_p90 = daily_climatology_mean_p90(sst, BASELINE_START, BASELINE_END)

    doy = sst.index.dayofyear
    anom = sst.values - clim_mean.reindex(doy).values
    anom = pd.Series(anom, index=sst.index, name="sst_anom_c")

    hot = (sst.values > clim_p90.reindex(doy).values).astype("float64")
    hot = pd.Series(hot, index=sst.index, name="sst_hot_flag")

    anom_year = annual_group(anom, how="mean").rename("sst_anom_year_c")
    hotdays_year = annual_group(hot, how="sum").rename("sst_hotdays_p90_year")

    return anom_year, hotdays_year


def fetch_oisst_grid_sst_mean(
    lat: float,
    lon: float,
    start: str,
    end: str,
    *,
    span_deg: float,
    stride_time: int,
    stride_lat: int,
    stride_lon: int,
) -> xr.DataArray:
    """
    Fetch a small OISST gridded subset around (lat, lon) and return time-mean SST (°C).

    This is used to build a cached left-side SST anomaly map (recent mean minus baseline mean).
    We intentionally sample coarsely (stride_time, stride_lat/lon) to keep downloads small.
    """
    spec = ERDDAP_DATASETS["oisst_sst_v21_daily"]
    dataset_id = spec["dataset_id"]
    var = spec["var"]

    lon_pm = _lon_pm180(lon)

    # Clamp to dataset availability
    start = max(start, spec.get("dataset_start", start))

    lat0, lat1 = lat - span_deg, lat + span_deg
    lon0, lon1 = lon_pm - span_deg, lon_pm + span_deg

    # Safeguard against invalid ranges
    lat0 = max(-89.9, float(lat0))
    lat1 = min(89.9, float(lat1))

    variants = [
        (lat0, lat1, lon0, lon1),
        (lat1, lat0, lon0, lon1),
        (lat0, lat1, lon1, lon0),
        (lat1, lat0, lon1, lon0),
    ]

    last_err: Optional[Exception] = None

    for base in OISST_BASES:
        for la0, la1, lo0, lo1 in variants:
            query = build_erddap_griddap_query_from_spec(
                spec,
                a_date=start,
                b_date=end,
                lat0=la0,
                lat1=la1,
                lon0=lo0,
                lon1=lo1,
                stride_time=stride_time,
                stride_lat=stride_lat,
                stride_lon=stride_lon,
            )
            url = erddap_griddap_url(base, dataset_id, query, "nc")

            cache_path = (
                CACHE_DIR
                / "oisst_grid"
                / f"oisst_grid_{dataset_id}_{lat:.4f}_{lon:.4f}_span{span_deg:.2f}"
                / f"{start}_{end}_t{int(stride_time)}_xy{int(stride_lat)}.nc"
            )

            try:
                download_to(
                    url,
                    cache_path,
                    retries=6,
                    timeout=(30, 300),
                    label=f"[OISST-GRID {start[:4]}]",
                )
                ds = xr.open_dataset(cache_path)
                if var not in ds:
                    raise RuntimeError(
                        f"OISST grid nc missing '{var}'. vars={list(ds.data_vars)}"
                    )

                da = ds[var]
                # OISST uses zlev; it should be length-1
                if "zlev" in da.dims:
                    da = da.isel(zlev=0)

                # Mean over time; keep lat/lon as provided
                if "time" in da.dims:
                    da = da.mean("time", skipna=True)

                da = da.load()
                ds.close()
                return da

            except Exception as e:
                last_err = e
                continue

    raise RuntimeError(f"OISST grid fetch failed for {start}..{end}: {last_err}")


# -------------------------
# CRW DHW fetch + metrics
# -------------------------


def fetch_crw_dhw_box_mean(
    lat: float, lon: float, box_half_deg: float, start: str, end: str
) -> pd.Series:
    """
    Fetch Coral Reef Watch DHW (degree_heating_week) for a small lat/lon box and return
    daily box-mean (NaNs ignored).

    Uses the ERDDAP dataset spec so we don't forget:
    - dataset id + variable name
    - dataset start date (CRW starts at 1985-03-25)
    - recommended chunking (1-year blocks to avoid 500/502 proxy errors)
    """
    spec = ERDDAP_DATASETS["crw_dhw_daily"]
    dataset_id = spec["dataset_id"]
    var = spec["var"]
    time_hms = spec.get("time_hms", "12:00:00Z")

    # Clamp to dataset availability
    start = max(start, spec.get("dataset_start", start))

    # Chunking rule (spike learning)
    block_years = int(spec.get("recommended_block_years", 1))

    lat0, lat1 = lat - box_half_deg, lat + box_half_deg
    lon0, lon1 = lon - box_half_deg, lon + box_half_deg

    series_parts = []
    for a, b in _year_blocks(start, end, block_years=block_years):
        query = (
            f"{var}[({a}T{time_hms}):1:({b}T{time_hms})]"
            f"[({lat0}):1:({lat1})]"
            f"[({lon0}):1:({lon1})]"
        )
        url = erddap_griddap_url(CRW_BASE, dataset_id, query, "csv")
        cache_path = (
            CACHE_DIR
            / "crw"
            / f"crw_{dataset_id}_{lat:.4f}_{lon:.4f}_{box_half_deg:.3f}_{a}_{b}.csv"
        )

        download_to(
            url, cache_path, retries=10, timeout=(30, 300), label=f"[CRW {a[:4]}]"
        )
        df = read_erddap_csv(cache_path)

        tcol = "time" if "time" in df.columns else df.columns[0]
        df[tcol] = pd.to_datetime(df[tcol], utc=True, errors="coerce")
        df = df.dropna(subset=[tcol])

        if var not in df.columns:
            raise RuntimeError(
                f"CRW CSV missing '{var}' column; columns={list(df.columns)}"
            )

        g = df.groupby(tcol)[var].mean()
        s = pd.Series(g.values, index=pd.to_datetime(g.index.values))
        s = s.sort_index()
        s.name = "dhw"
        series_parts.append(s)

    dhw = pd.concat(series_parts).sort_index()
    dhw = dhw[~dhw.index.duplicated(keep="first")]
    return dhw


def compute_dhw_annual_metrics(
    dhw_daily: pd.Series,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    dhw_max = annual_group(dhw_daily, how="max").rename("dhw_max_year")
    ge4 = annual_group((dhw_daily >= 4.0).astype("float64"), how="sum").rename(
        "dhw_ge4_days_year"
    )
    ge8 = annual_group((dhw_daily >= 8.0).astype("float64"), how="sum").rename(
        "dhw_ge8_days_year"
    )
    return dhw_max, ge4, ge8


# -------------------------
# NetCDF writer
# -------------------------


def write_ocean_cache(
    out_path: Path,
    *,
    slug: str,
    label: str,
    lat: float,
    lon: float,
    end_date: str,
    sst_anom_year_c: pd.Series,
    sst_hotdays_p90_year: pd.Series,
    dhw_daily: pd.Series,
    dhw_max_year: pd.Series,
    dhw_ge4_days_year: pd.Series,
    dhw_ge8_days_year: pd.Series,
    dhw_box_half_deg: float,
    sst_map_baseline_mean_c: xr.DataArray | None = None,
    sst_map_recent_mean_c: xr.DataArray | None = None,
    sst_map_recent_anom_c: xr.DataArray | None = None,
    sst_map_meta: dict | None = None,
) -> None:
    years = sorted(
        set(sst_anom_year_c.index.tolist())
        | set(sst_hotdays_p90_year.index.tolist())
        | set(dhw_max_year.index.tolist())
        | set(dhw_ge4_days_year.index.tolist())
        | set(dhw_ge8_days_year.index.tolist())
    )

    # Daily DHW (box-mean) — store raw daily time series (including Feb 29 if present).
    dhw_daily = dhw_daily.sort_index()
    dhw_time = pd.DatetimeIndex(dhw_daily.index).to_numpy(dtype="datetime64[ns]")
    dhw_vals = dhw_daily.astype("float32").to_numpy()

    ds = xr.Dataset(
        data_vars=dict(
            sst_anom_year_c=(
                "year",
                [float(sst_anom_year_c.get(y, np.nan)) for y in years],
            ),
            sst_hotdays_p90_year=(
                "year",
                [float(sst_hotdays_p90_year.get(y, np.nan)) for y in years],
            ),
            # Daily DHW needed for heatmaps
            dhw_daily=("time", dhw_vals),
            # Annual DHW metrics (already used by current panel)
            dhw_max_year=("year", [float(dhw_max_year.get(y, np.nan)) for y in years]),
            dhw_ge4_days_year=(
                "year",
                [float(dhw_ge4_days_year.get(y, np.nan)) for y in years],
            ),
            dhw_ge8_days_year=(
                "year",
                [float(dhw_ge8_days_year.get(y, np.nan)) for y in years],
            ),
        ),
        coords=dict(
            year=("year", np.asarray(years, dtype=np.int32)),
            time=("time", dhw_time),
        ),
        attrs=dict(
            slug=slug,
            label=label,
            latitude=float(lat),
            longitude=float(lon),
            data_end_date=str(end_date),
            baseline_start=BASELINE_START,
            baseline_end=BASELINE_END,
            oisst_dataset_id=ERDDAP_DATASETS["oisst_sst_v21_daily"]["dataset_id"],
            crw_dataset_id=ERDDAP_DATASETS["crw_dhw_daily"]["dataset_id"],
            crw_variable=ERDDAP_DATASETS["crw_dhw_daily"]["var"],
            dhw_box_half_deg=float(dhw_box_half_deg),
            generated_at=datetime.utcnow().isoformat() + "Z",
        ),
    )

    # Optional cached gridded SST map inputs (for left-side SST anomaly map export)
    if (
        sst_map_baseline_mean_c is not None
        and sst_map_recent_mean_c is not None
        and sst_map_recent_anom_c is not None
    ):
        # Normalize dim names into explicit coords for stable panel code
        lat_name = "latitude" if "latitude" in sst_map_recent_anom_c.dims else "lat"
        lon_name = "longitude" if "longitude" in sst_map_recent_anom_c.dims else "lon"

        ds = ds.assign_coords(
            sst_lat=(
                "sst_lat",
                sst_map_recent_anom_c[lat_name].values.astype("float64"),
            ),
            sst_lon=(
                "sst_lon",
                sst_map_recent_anom_c[lon_name].values.astype("float64"),
            ),
        )

        ds["sst_map_baseline_mean_c"] = (
            ("sst_lat", "sst_lon"),
            sst_map_baseline_mean_c.values.astype("float64"),
        )
        ds["sst_map_recent_mean_c"] = (
            ("sst_lat", "sst_lon"),
            sst_map_recent_mean_c.values.astype("float64"),
        )
        ds["sst_map_recent_anom_c"] = (
            ("sst_lat", "sst_lon"),
            sst_map_recent_anom_c.values.astype("float64"),
        )

        if sst_map_meta:
            for k, v in sst_map_meta.items():
                ds.attrs[f"sst_map_{k}"] = v

    # lightweight compression
    enc = {k: {"zlib": True, "complevel": 4} for k in ds.data_vars.keys()}

    _ensure_dir(out_path)
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    ds.to_netcdf(tmp_path, encoding=enc)
    os.replace(tmp_path, out_path)
    ds.close()


# -------------------------
# Main
# -------------------------


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clim-dir", default=DEFAULT_CLIM_DIR)
    ap.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    ap.add_argument("--slugs", nargs="*", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dhw-box-half-deg", type=float, default=DEFAULT_DHW_BOX_HALF_DEG)

    ap.add_argument("--sst-map-span-deg", type=float, default=DEFAULT_SST_MAP_SPAN_DEG)
    ap.add_argument(
        "--sst-map-time-stride", type=int, default=DEFAULT_SST_MAP_TIME_STRIDE
    )
    ap.add_argument(
        "--sst-map-latlon-stride", type=int, default=DEFAULT_SST_MAP_LATLON_STRIDE
    )
    return ap.parse_args()


def main() -> None:
    args = parse_args()

    locations = discover_locations(args.clim_dir)
    slugs = sorted(locations.keys())

    if args.slugs:
        wanted = set(args.slugs)
        slugs = [s for s in slugs if s in wanted]

    if args.limit is not None and args.limit > 0:
        slugs = slugs[: args.limit]

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for slug in slugs:
        meta = locations[slug]
        lat = float(meta["lat"])
        lon = float(meta["lon"])
        label = str(meta["label"])
        clim_path = Path(meta["path"])

        ds_clim = xr.open_dataset(clim_path)
        end_date = str(ds_clim.attrs.get("data_end_date", ""))
        if not end_date:
            # fallback to last time sample of daily series
            try:
                t = pd.to_datetime(ds_clim["time"].values)
                end_date = pd.Timestamp(t.max()).strftime("%Y-%m-%d")
            except Exception:
                end_date = datetime.utcnow().strftime("%Y-%m-%d")
        ds_clim.close()

        print(f"\n=== {slug} ({label}) ===")

        # SST
        sst_end = min(pd.Timestamp(end_date), pd.Timestamp(date.today())).strftime(
            "%Y-%m-%d"
        )
        sst = fetch_oisst_daily_sst_point(lat, lon, BASELINE_START, sst_end)
        sst_anom_year_c, sst_hotdays_p90_year = compute_sst_anom_and_hotdays(sst)

        # Cached SST anomaly map (regional gridded mean, sampled)
        recent_end = min(pd.Timestamp(sst_end), pd.Timestamp(RECENT_CAP_END)).strftime(
            "%Y-%m-%d"
        )

        sst_map_baseline = fetch_oisst_grid_sst_mean(
            lat,
            lon,
            BASELINE_START,
            BASELINE_END,
            span_deg=float(args.sst_map_span_deg),
            stride_time=int(args.sst_map_time_stride),
            stride_lat=int(args.sst_map_latlon_stride),
            stride_lon=int(args.sst_map_latlon_stride),
        )
        sst_map_recent = fetch_oisst_grid_sst_mean(
            lat,
            lon,
            RECENT_START,
            recent_end,
            span_deg=float(args.sst_map_span_deg),
            stride_time=int(args.sst_map_time_stride),
            stride_lat=int(args.sst_map_latlon_stride),
            stride_lon=int(args.sst_map_latlon_stride),
        )
        sst_map_anom = sst_map_recent - sst_map_baseline

        sst_map_meta = dict(
            span_deg=float(args.sst_map_span_deg),
            baseline_start=BASELINE_START,
            baseline_end=BASELINE_END,
            recent_start=RECENT_START,
            recent_end=str(recent_end),
            stride_time=int(args.sst_map_time_stride),
            stride_latlon=int(args.sst_map_latlon_stride),
        )

        # DHW
        dhw_end = sst_end
        dhw = fetch_crw_dhw_box_mean(
            lat, lon, args.dhw_box_half_deg, BASELINE_START, dhw_end
        )
        dhw_max_year, dhw_ge4_days_year, dhw_ge8_days_year = compute_dhw_annual_metrics(
            dhw
        )

        out_path = out_dir / f"ocean_{slug}.nc"
        write_ocean_cache(
            out_path,
            slug=slug,
            label=label,
            lat=lat,
            lon=lon,
            end_date=sst_end,
            sst_anom_year_c=sst_anom_year_c,
            sst_hotdays_p90_year=sst_hotdays_p90_year,
            dhw_daily=dhw,
            dhw_max_year=dhw_max_year,
            dhw_ge4_days_year=dhw_ge4_days_year,
            dhw_ge8_days_year=dhw_ge8_days_year,
            dhw_box_half_deg=args.dhw_box_half_deg,
            sst_map_baseline_mean_c=sst_map_baseline,
            sst_map_recent_mean_c=sst_map_recent,
            sst_map_recent_anom_c=sst_map_anom,
            sst_map_meta=sst_map_meta,
        )

        print(f"[ok] wrote {out_path}")


if __name__ == "__main__":
    main()
