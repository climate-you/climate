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
from pathlib import Path
from datetime import date, datetime

import numpy as np
import pandas as pd
import xarray as xr

from climate.io import discover_locations
from climate.datasets.products.oisst import (
    fetch_daily_point as fetch_oisst_daily_sst_point,
    fetch_grid_mean as fetch_oisst_grid_sst_mean,
)
from climate.datasets.derive.sst_metrics import (
    compute_anom_and_hotdays as compute_sst_anom_and_hotdays,
)
from climate.datasets.products.crw_dhw import fetch_box_mean as fetch_crw_dhw_box_mean
from climate.datasets.derive.dhw_metrics import (
    compute_annual_metrics as compute_dhw_annual_metrics,
)
from climate.datasets.products.erddap_specs import ERDDAP_DATASETS


# -------------------------
# Paths
# -------------------------

DEFAULT_CLIM_DIR = "data/story_climatology"
DEFAULT_OUT_DIR = "data/story_ocean"
CACHE_DIR = Path("data") / "cache" / "ocean"


def _ensure_dir(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)


# -------------------------
# Dataset constants
# -------------------------

# Baseline for anomalies / thresholds
BASELINE_START = "1981-01-01"
BASELINE_END = "2010-12-31"

# Default DHW box: half-width degrees (=> 0.1° x 0.1° box when 0.05)
DEFAULT_DHW_BOX_HALF_DEG = 0.05

# SST anomaly map (cached gridded anomaly around the city, for left-side map export)
DEFAULT_SST_MAP_SPAN_DEG = 1.5
DEFAULT_SST_MAP_TIME_STRIDE = 30  # ~monthly sampling (daily index stride)
DEFAULT_SST_MAP_LATLON_STRIDE = 2  # subsample grid
RECENT_START = "2016-01-01"
RECENT_CAP_END = "2025-12-31"


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
        sst = fetch_oisst_daily_sst_point(lat, lon, BASELINE_START, sst_end, CACHE_DIR)
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
            cache_dir=CACHE_DIR,
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
            cache_dir=CACHE_DIR,
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
            lat, lon, args.dhw_box_half_deg, BASELINE_START, dhw_end, CACHE_DIR
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
