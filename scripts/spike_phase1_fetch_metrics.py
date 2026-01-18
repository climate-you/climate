# scripts/spike_phase1_fetch_metrics.py
from __future__ import annotations

import os
import math
import json
import pathlib
from dataclasses import dataclass
from typing import Dict, Tuple
import zipfile
import time
import cdsapi
import random

import numpy as np
import pandas as pd
import requests
import xarray as xr
from urllib.parse import urlparse
import matplotlib.pyplot as plt


# ----------------------------
# Config
# ----------------------------
START = "1981-01-01"
END = "2025-12-31"
BASELINE_START = "1981-01-01"
BASELINE_END = "2010-12-31"

CRW_MIN_DATE = "1985-03-25"

DRY_MM = 1.0  # "dry day" threshold in mm/day

CACHE_DIR = pathlib.Path("data/cache/spike_phase1")
OUT_DIR = pathlib.Path("data/spike_phase1_outputs")
OUT_DIR.mkdir(parents=True, exist_ok=True)
(CACHE_DIR / "era5").mkdir(parents=True, exist_ok=True)
(CACHE_DIR / "oisst").mkdir(parents=True, exist_ok=True)
(CACHE_DIR / "crw").mkdir(parents=True, exist_ok=True)

# Slugs + coords (from your cities_index.json extract)
LOCATIONS = {
    "city_mu_tamarin": {"label": "Tamarin, Mauritius", "lat": -20.32556, "lon": 57.37056},
    "city_gb_london": {"label": "London, UK", "lat": 51.50853, "lon": -0.12574},
    "city_fr_troyes": {"label": "Troyes, France", "lat": 48.30073, "lon": 4.08524},
}

# Tamarin DHW box: 0.1° x 0.1° => +/- 0.05
TAMARIN_DHW_BOX_HALF_DEG = 0.05


# ----------------------------
# Helpers
# ----------------------------
def doy_index(dt_index: pd.DatetimeIndex) -> np.ndarray:
    # 1..366
    return dt_index.dayofyear.values

def ensure_datetime_index(df: pd.DataFrame, time_col: str = "time") -> pd.DataFrame:
    df = df.copy()
    df[time_col] = pd.to_datetime(df[time_col], utc=True)
    df = df.sort_values(time_col)
    df = df.set_index(time_col)
    return df

def longest_run(bool_arr: np.ndarray) -> int:
    # longest consecutive True run
    if len(bool_arr) == 0:
        return 0
    max_run = 0
    run = 0
    for v in bool_arr:
        if v:
            run += 1
            max_run = max(max_run, run)
        else:
            run = 0
    return int(max_run)

def yearly_max_run(dates: pd.DatetimeIndex, is_event: np.ndarray) -> pd.Series:
    years = dates.year
    out = {}
    for y in np.unique(years):
        mask = years == y
        out[int(y)] = longest_run(is_event[mask])
    return pd.Series(out).sort_index()

def yearly_count(dates: pd.DatetimeIndex, is_event: np.ndarray) -> pd.Series:
    years = dates.year
    out = {}
    for y in np.unique(years):
        mask = years == y
        out[int(y)] = int(is_event[mask].sum())
    return pd.Series(out).sort_index()

def plot_series(series: pd.Series, title: str, outpath: pathlib.Path) -> None:
    outpath.parent.mkdir(parents=True, exist_ok=True)
    plt.figure()
    series.plot()
    plt.title(title)
    plt.xlabel("Year")
    plt.tight_layout()
    plt.savefig(outpath, dpi=160)
    plt.close()


# ----------------------------
# ERDDAP subset download (OISST + CRW)
# ----------------------------
def erddap_griddap_nc_url(base: str, dataset_id: str, query: str) -> str:
    # Example:
    #   f"{base}/griddap/{dataset_id}.nc?sst[(1981-01-01T00:00:00Z):1:(2025-12-31T00:00:00Z)][(lat0):1:(lat1)][(lon0):1:(lon1)]"
    return f"{base}/griddap/{dataset_id}.nc?{query}"

def _probe_erddap_reachable(url: str, connect_timeout: float = 3.0) -> tuple[bool, str]:
    """
    If url looks like an ERDDAP request, do a quick HEAD/GET probe to help
    distinguish 'host unreachable' from 'bad query (404)'.
    """
    try:
        u = urlparse(url)
        base = f"{u.scheme}://{u.netloc}"
        # A lightweight endpoint that should respond quickly if ERDDAP is reachable.
        probe_urls = [
            f"{base}/erddap/info/index.html",
            f"{base}/erddap/index.html",
        ]
        for p in probe_urls:
            try:
                r = requests.head(p, timeout=(connect_timeout, connect_timeout), allow_redirects=True)
                if r.status_code < 500:
                    return True, base
            except Exception:
                pass

        # HEAD sometimes blocked; try a tiny GET as fallback
        for p in probe_urls:
            try:
                r = requests.get(p, timeout=(connect_timeout, connect_timeout), allow_redirects=True)
                if r.status_code < 500:
                    return True, base
            except Exception:
                pass

        return False, base
    except Exception:
        return True, ""  # don't block download if parsing/probe fails

def probe(
    url: str,
    timeout=(60, 300),
    ):
 # QoL: quick ERDDAP reachability check (helps explain "hangs on this ISP/router")
    if "/erddap/" not in url:
        return
    ok, base = _probe_erddap_reachable(url, connect_timeout=min(3.0, float(timeout[0])))
    if not ok:
        raise RuntimeError(
            f"ERDDAP host appears unreachable from this network ({base}).\n"
            f"- You can verify with: curl -I {base}/erddap/info/index.html\n"
            f"- Workarounds: use a VPN, phone hotspot, or run this from a cloud machine.\n"
            f"Original URL:\n{url}")

_SESSION = requests.Session()

def download_to(
    url: str,
    path: pathlib.Path,
    timeout=(60, 300),
    retries=10,
    label: str | None = None,
    min_delay_s: float = 0.75,
    max_delay_s: float = 2.0,
) -> pathlib.Path:
    """
    Robust download with:
    - requests.Session() reuse
    - exponential backoff + jitter
    - politeness delay between attempts/successes
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 0:
        return path

    tag = f"[{label}] " if label else ""

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            print(f"{tag}Downloading (attempt {attempt}/{retries}) -> {path.name}")
            r = _SESSION.get(url, timeout=timeout)
            r.raise_for_status()
            path.write_bytes(r.content)
            print(f"{tag}Downloaded {path.stat().st_size/1024:.1f} KB")

            # Politeness delay after success (helps ERDDAP not drop you)
            time.sleep(random.uniform(min_delay_s, max_delay_s))
            return path
        except Exception as e:
            last_err = e
            # Backoff with jitter
            backoff = min(30.0, (2 ** (attempt - 1)))
            sleep_s = random.uniform(0.5, 1.5) + backoff * 0.2
            print(f"{tag}Download failed: {type(e).__name__}: {e} (sleep {sleep_s:.1f}s)")
            time.sleep(sleep_s)

    raise RuntimeError(
        f"{tag}Failed to download after {retries} attempts.\nURL: {url}\nLast error: {last_err}"
    )

def open_erddap_subset_as_xr(url: str, cache_path: pathlib.Path) -> xr.Dataset:
    probe(url)
    fpath = download_to(url, cache_path)
    return xr.open_dataset(fpath)


# ----------------------------
# OISST: point series (nearest cell)
# ----------------------------
def erddap_griddap_csv_url(base: str, dataset_id: str, query: str) -> str:
    return f"{base}/griddap/{dataset_id}.csv?{query}"

def year_block_ranges(start: str, end: str, block_years: int = 5):
    y0 = int(start[:4])
    y1 = int(end[:4])
    for y in range(y0, y1 + 1, block_years):
        a = f"{y:04d}-01-01"
        b = f"{min(y + block_years - 1, y1):04d}-12-31"
        a = max(a, start)
        b = min(b, end)
        yield a, b

def fetch_oisst_point_timeseries(lat: float, lon: float) -> pd.Series:
    ERDDAP_BASES = [
        "https://coastwatch.pfeg.noaa.gov/erddap",
        "https://upwell.pfeg.noaa.gov/erddap",
    ]
    DATASET_ID = "ncdcOisst21Agg_LonPM180"

    lon_q = lon
    if lon_q > 180: lon_q -= 360
    if lon_q < -180: lon_q += 360

    # start2 = max(START, "2000-01-01")
    start2 = max(START, "1981-09-01")
    end2 = END

    # tiny spatial box
    lat0, lat1 = lat - 0.01, lat + 0.01
    lon0, lon1 = lon_q - 0.01, lon_q + 0.01

    def year_ranges(start: str, end: str):
        y0 = int(start[:4])
        y1 = int(end[:4])
        for y in range(y0, y1 + 1):
            a = f"{y:04d}-01-01"
            b = f"{y:04d}-12-31"
            a = max(a, start)
            b = min(b, end)
            yield a, b

    parts = []

    for (a, b) in year_block_ranges(start2, end2, block_years=5):
        # OISST time is typically 12:00Z; include zlev dim (0.0) for this dataset
        query = (
            f"sst[({a}T12:00:00Z):1:({b}T12:00:00Z)]"
            f"[(0.0)]"
            f"[({lat0}):1:({lat1})]"
            f"[({lon0}):1:({lon1})]"
        )

        ok = False
        last_err = None

        for base in ERDDAP_BASES:
            url = erddap_griddap_csv_url(base, DATASET_ID, query)
            cache_path = CACHE_DIR / "oisst" / f"oisst_{DATASET_ID}_{lat:.4f}_{lon:.4f}_{a}_{b}.csv"
            try:
                download_to(url, cache_path, timeout=(60, 300), retries=3, label=f"OISST {a[:4]}")
                
                # ERDDAP CSV often includes a 2nd "units" line (e.g. first value "UTC")
                # Skip it via skiprows=1, and also treat lines starting with "#" as comments.
                df = pd.read_csv(cache_path, skiprows=[1], comment="#")

                tcol = "time" if "time" in df.columns else df.columns[0]

                # ERDDAP time strings are typically ISO-like, e.g. "2000-01-01T12:00:00Z"
                # Provide an explicit format to avoid slow/ambiguous parsing warnings.
                df[tcol] = pd.to_datetime(df[tcol], format="%Y-%m-%dT%H:%M:%SZ", utc=True, errors="raise")

                # pick sst column
                sst_col = "sst"
                if sst_col not in df.columns:
                    # sometimes variable is named differently; fall back to last col
                    sst_col = df.columns[-1]

                # choose the row whose lat/lon are closest to requested
                latcol = "latitude" if "latitude" in df.columns else ("lat" if "lat" in df.columns else None)
                loncol = "longitude" if "longitude" in df.columns else ("lon" if "lon" in df.columns else None)

                if latcol and loncol:
                    # group by time and pick nearest spatial row each time
                    def pick_nearest(g):
                        d = (g[latcol] - lat).abs() + (g[loncol] - lon_q).abs()
                        return g.loc[d.idxmin()]
                    picked = df.groupby(tcol, sort=True).apply(pick_nearest)
                    s = pd.Series(picked[sst_col].values, index=picked[tcol].values)
                else:
                    # if no coords in CSV (rare), assume single value per time
                    s = df.set_index(tcol)[sst_col]

                s = s.sort_index()
                s.name = "sst_c"
                parts.append(s)
                ok = True
                break
            except Exception as e:
                last_err = e

        if not ok:
            raise RuntimeError(f"OISST ERDDAP failed for {a}..{b}. Last error: {last_err}")

    sst = pd.concat(parts).sort_index()
    sst = sst[~sst.index.duplicated(keep="first")]
    sst.name = "sst_c"
    return sst


# ----------------------------
# CRW DHW: small-box mean series (Tamarin)
# ----------------------------
def fetch_crw_dhw_boxmean_timeseries(lat: float, lon: float, half_deg: float = 0.05) -> pd.Series:
    """
    CRW DHW daily via NOAA CoastWatch ERDDAP.
    Chunk requests in time to avoid 500s on long ranges.
    """
    ERDDAP_BASES = [
        "https://coastwatch.noaa.gov/erddap",
        # add a second base if you find one that works better for you
        # "https://coastwatch.noaa.gov/erddap" is usually the right one though
    ]
    DATASET_ID = "noaacrwdhwDaily"

    lat0, lat1 = lat - half_deg, lat + half_deg
    lon0, lon1 = lon - half_deg, lon + half_deg

    # CRW DHW ERDDAP axis minimum (per curl error) is 1985-03-25T12:00:00Z
    start2 = max(START, CRW_MIN_DATE)
    end2 = END

    def year_block_ranges(start: str, end: str, block_years: int = 5):
        y0 = int(start[:4])
        y1 = int(end[:4])
        for y in range(y0, y1 + 1, block_years):
            a = f"{y:04d}-01-01"
            b = f"{min(y + block_years - 1, y1):04d}-12-31"
            a = max(a, start)
            b = min(b, end)
            yield a, b

    parts = []

    for (a, b) in year_block_ranges(start2, end2, block_years=1):
        var = "degree_heating_week"
        # CRW DHW time axis is at 12:00Z (as seen in curl output)
        query = (
            f"{var}[({a}T12:00:00Z):1:({b}T12:00:00Z)]"
            f"[({lat0}):1:({lat1})]"
            f"[({lon0}):1:({lon1})]"
        )

        ok = False
        last_err = None

        for base in ERDDAP_BASES:
            # Try CSV first (often avoids 500s for long netcdf responses)
            url_csv = f"{base}/griddap/{DATASET_ID}.csv?{query}"
            cache_csv = CACHE_DIR / "crw" / f"crw_{DATASET_ID}_{lat:.4f}_{lon:.4f}_{half_deg:.3f}_{a}_{b}.csv"
            try:
                download_to(url_csv, cache_csv, timeout=(60, 300), retries=10, label=f"CRW {a[:4]}")
                df = pd.read_csv(cache_csv, skiprows=[1], comment="#")
                # expected cols: time, latitude, longitude, dhw (and maybe others)
                tcol = "time" if "time" in df.columns else df.columns[0]
                df[tcol] = pd.to_datetime(df[tcol], format="%Y-%m-%dT%H:%M:%SZ", utc=True)

                dhw_col = "degree_heating_week" if "degree_heating_week" in df.columns else df.columns[-1]
                latcol = "latitude" if "latitude" in df.columns else ("lat" if "lat" in df.columns else None)
                loncol = "longitude" if "longitude" in df.columns else ("lon" if "lon" in df.columns else None)

                if latcol and loncol:
                    # For each time, average dhw across all spatial rows (box mean)
                    g = df.groupby(tcol)[dhw_col].mean()
                    s = pd.Series(g.values, index=g.index, name="dhw_cweeks")
                else:
                    s = df.set_index(tcol)[dhw_col]
                    s.name = "dhw_cweeks"

                parts.append(s.sort_index())
                ok = True
                break
            except Exception as e:
                last_err = e

            # Fallback to NetCDF if CSV fails
            url_nc = f"{base}/griddap/{DATASET_ID}.nc?{query}"
            cache_nc = CACHE_DIR / "crw" / f"crw_{DATASET_ID}_{lat:.4f}_{lon:.4f}_{half_deg:.3f}_{a}_{b}.nc"
            try:
                download_to(url_nc, cache_nc, timeout=(60, 300), retries=10, label=f"CRWnc {a[:4]}")
                ds = xr.open_dataset(cache_nc)
                da = ds[var]

                spatial_dims = [d for d in da.dims if d.lower() in ("lat", "latitude", "lon", "longitude")]
                da_mean = da.mean(dim=spatial_dims, skipna=True)

                s = da_mean.to_series()
                s.index = pd.to_datetime(s.index, utc=True)
                s.name = "dhw_cweeks"
                parts.append(s.sort_index())
                ok = True
                break
            except Exception as e:
                last_err = e

        if not ok:
            raise RuntimeError(f"CRW DHW failed for {a}..{b}. Last error: {last_err}")

    dhw = pd.concat(parts).sort_index()
    dhw = dhw[~dhw.index.duplicated(keep="first")]
    dhw.name = "dhw_cweeks"
    return dhw


# ----------------------------
# ERA5 daily precip via CDS derived daily statistics
# ----------------------------
def fetch_era5_hourly_tp_timeseries(lat: float, lon: float) -> pd.Series:
    """
    Fetch ERA5 hourly total_precipitation as a point time-series (nearest ERA5 grid point),
    then return an hourly pandas Series (meters). We'll convert to mm and daily-sum later.

    Uses dataset: reanalysis-era5-single-levels-timeseries (designed for fast point time-series).
    """
    dataset = "reanalysis-era5-single-levels-timeseries"
    cache_csv = CACHE_DIR / "era5" / f"era5_tp_hourly_timeseries_{lat:.4f}_{lon:.4f}_{START}_{END}.csv"

    if not cache_csv.exists():
        client = cdsapi.Client()
        request = {
            "variable": ["total_precipitation"],
            "location": {"latitude": float(lat), "longitude": float(lon)},
            "date": [f"{START}/{END}"],
            "data_format": "csv",
        }
        # CDSAPI v0/legacy sometimes wants a target file via retrieve(..., target)
        client.retrieve(dataset, request, str(cache_csv))

    raw_path = cache_csv

    # Some CDS "csv" responses arrive as a ZIP (binary) even if you name it .csv.
    # Detect and extract if needed.
    with open(raw_path, "rb") as f:
        sig = f.read(4)

    if sig == b"PK\x03\x04":
        zpath = raw_path
        out_csv = raw_path.with_suffix(".extracted.csv")
        if not out_csv.exists():
            with zipfile.ZipFile(zpath, "r") as zf:
                # pick the first csv-like member
                members = [m for m in zf.namelist() if m.lower().endswith(".csv")]
                if not members:
                    members = zf.namelist()
                target = members[0]
                zf.extract(target, path=raw_path.parent)
                extracted = raw_path.parent / target
                extracted.replace(out_csv)
        csv_path = out_csv
    else:
        csv_path = raw_path

    # Read CSV with a fallback encoding
    try:
        df = pd.read_csv(csv_path)
    except UnicodeDecodeError:
        df = pd.read_csv(csv_path, encoding="latin-1")

    time_col = "time" if "time" in df.columns else df.columns[0]
    df = ensure_datetime_index(df, time_col=time_col)

    if "total_precipitation" in df.columns:
        col = "total_precipitation"
    elif "tp" in df.columns:
        col = "tp"
    else:
        # fallback: assume the only non-time column is the variable
        cols = [c for c in df.columns if c != time_col]
        if len(cols) != 1:
            raise ValueError(f"Could not identify precip column in CSV. Columns={list(df.columns)}")
        col = cols[0]

    s = df[col].astype(float)
    s.name = "tp_m_hourly"
    return s


# ----------------------------
# Metric computations (Phase 1 subset)
# ----------------------------
def compute_dryspell_maxlen(pr_mm: pd.Series) -> pd.Series:
    pr_mm = pr_mm.dropna()
    dates = pr_mm.index
    is_dry = (pr_mm.values < DRY_MM)
    return yearly_max_run(dates, is_dry)

def compute_sst_anom_and_hotdays(sst_c: pd.Series) -> Tuple[pd.Series, pd.Series]:
    sst_c = sst_c.dropna()
    # baseline climatology by doy (mean) and p90 by doy (using all baseline years)
    baseline = sst_c.loc[BASELINE_START:BASELINE_END]
    b_doy = baseline.index.dayofyear

    clim_mean = baseline.groupby(b_doy).mean()
    clim_p90 = baseline.groupby(b_doy).quantile(0.90)

    doy_all = sst_c.index.dayofyear
    anom = sst_c.values - clim_mean.reindex(doy_all).values

    anom_s = pd.Series(anom, index=sst_c.index, name="sst_anom_c")
    annual_mean_anom = anom_s.resample("YS").mean()
    annual_mean_anom.index = annual_mean_anom.index.year

    hot = sst_c.values > clim_p90.reindex(doy_all).values
    hotdays = yearly_count(sst_c.index, hot)
    hotdays.name = "sst_hotdays_p90_count"
    return annual_mean_anom, hotdays

def compute_dhw_metrics(
        dhw: pd.Series,
        thresholds: tuple[float, ...] = (4.0, 8.0),
    ) -> tuple[pd.Series, dict[float, pd.Series]]:
    dhw = dhw.dropna()
    annual_max = dhw.resample("YS").max()
    annual_max.index = annual_max.index.year
    annual_max.name = "dhw_max"

    counts: dict[float, pd.Series] = {}
    for thr in thresholds:
        s = yearly_count(dhw.index, dhw.values >= float(thr))
        # keep filenames/keys stable & readable (4 -> dhw_ge4_days, 8 -> dhw_ge8_days)
        thr_int = int(thr) if float(thr).is_integer() else thr
        s.name = f"dhw_ge{thr_int}_days"
        counts[float(thr)] = s

    return annual_max, counts

# ----------------------------
# Helpers
# ----------------------------

def warm_season_mask(dti: pd.DatetimeIndex, lat: float) -> np.ndarray:
    # NH: May-Sep, SH: Nov-Mar
    m = dti.month.values
    if lat >= 0:
        return (m >= 5) & (m <= 9)
    else:
        return (m >= 11) | (m <= 3)

# ----------------------------
# Main
# ----------------------------
def main() -> None:
    summary = {}

    # ERA5 precip metrics for Troyes & London
    for slug in ["city_fr_troyes", "city_gb_london"]:
        lat = LOCATIONS[slug]["lat"]
        lon = LOCATIONS[slug]["lon"]
        print(f"\n[ERA5] Fetching daily precip bbox for {slug} ({lat},{lon}) ...")

        tp_hourly_m = fetch_era5_hourly_tp_timeseries(lat, lon)

        # Convert meters -> mm
        tp_hourly_mm = tp_hourly_m * 1000.0
        tp_hourly_mm.name = "pr_mm_hourly"

        # Daily total (UTC) from hourly accumulations
        pr_daily_mm = tp_hourly_mm.resample("D").sum(min_count=1)
        pr_daily_mm.name = "pr_mm_day"

        # Summer-only (May-Sep in North) to reduce noise
        mask = warm_season_mask(pr_daily_mm.index, lat)
        season = pr_daily_mm[mask]
        dryspell = compute_dryspell_maxlen(season.loc[START:END])

        plot_series(
            dryspell,
            f"{slug} dryspell_maxlen (ERA5, pr< {DRY_MM} mm/day)",
            OUT_DIR / "plots" / f"{slug}_dryspell_maxlen.png",
        )

        summary.setdefault(slug, {})["dryspell_maxlen"] = {
            "baseline_1981_1990": float(dryspell.loc[1981:1990].mean()),
            "recent_2016_2025": float(dryspell.loc[2016:2025].mean()),
        }

    # OISST + CRW for Tamarin
    slug = "city_mu_tamarin"
    lat = LOCATIONS[slug]["lat"]
    lon = LOCATIONS[slug]["lon"]

    print(f"\n[OISST] Fetching SST point series for {slug} ({lat},{lon}) ...")
    sst = fetch_oisst_point_timeseries(lat, lon)
    sst_anom, sst_hotdays = compute_sst_anom_and_hotdays(sst.loc[START:END])
    plot_series(sst_anom, f"{slug} SST annual mean anomaly (vs 1981-2010)", OUT_DIR / "plots" / f"{slug}_sst_anom.png")
    plot_series(sst_hotdays, f"{slug} SST hotdays (above baseline P90)", OUT_DIR / "plots" / f"{slug}_sst_hotdays_p90.png")

    print(f"\n[CRW] Fetching DHW box-mean series for {slug} ...")
    dhw = fetch_crw_dhw_boxmean_timeseries(lat, lon, half_deg=TAMARIN_DHW_BOX_HALF_DEG)
    dhw_max, dhw_counts = compute_dhw_metrics(dhw, thresholds=(4.0, 8.0))
    dhw_ge4 = dhw_counts[4.0]
    dhw_ge8 = dhw_counts[8.0]
    plot_series(dhw_max, f"{slug} DHW annual max", OUT_DIR / "plots" / f"{slug}_dhw_max.png")
    plot_series(dhw_ge4, f"{slug} DHW days >= 4", OUT_DIR / "plots" / f"{slug}_dhw_ge4_days.png")
    plot_series(dhw_ge8, f"{slug} DHW days >= 8", OUT_DIR / "plots" / f"{slug}_dhw_ge8_days.png")

    summary.setdefault(slug, {})["sst"] = {
        "anom_1981_1990_mean": float(sst_anom.loc[1981:1990].mean()),
        "anom_2016_2025_mean": float(sst_anom.loc[2016:2025].mean()),
    }
    summary[slug]["dhw"] = {
        "dhw_max_1985_1994_mean": float(dhw_max.loc[1985:1994].mean()) if 1985 in dhw_max.index else None,
        "dhw_max_2016_2025_mean": float(dhw_max.loc[2016:2025].mean()) if 2016 in dhw_max.index else None,
        "dhw_ge4_days_2016_2025_mean": float(dhw_ge4.loc[2016:2025].mean()) if 2016 in dhw_ge4.index else None,
        "dhw_ge8_days_2016_2025_mean": float(dhw_ge8.loc[2016:2025].mean()) if 2016 in dhw_ge8.index else None,
    }

    out_json = OUT_DIR / "summary.json"
    out_json.write_text(json.dumps(summary, indent=2))
    print(f"\nWrote {out_json}")
    print(f"Wrote plots to {OUT_DIR / 'plots'}")


if __name__ == "__main__":
    main()
