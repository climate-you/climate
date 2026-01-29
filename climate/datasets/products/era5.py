import os
import json
from pathlib import Path
from typing import List, Tuple

import cdsapi
import pandas as pd
import zipfile


def download_monthly_means(
    out_nc: Path,
    years: List[str],
    grid_deg: float,
    area: Tuple[float, float, float, float] | None,
) -> str:
    """Download monthly 2m temperature from CDS into out_nc and return the request dict as JSON string."""

    c = cdsapi.Client()
    req = {
        "product_type": "monthly_averaged_reanalysis",
        "data_format": "netcdf",
        "variable": ["2m_temperature"],
        "year": years,
        "month": [f"{m:02d}" for m in range(1, 13)],
        "time": ["00:00"],
        # Coarsen the native 0.25° grid to keep files reasonable for a web app.
        "grid": [grid_deg, grid_deg],
    }
    if area is not None:
        # CDS uses [N, W, S, E]
        req["area"] = [area[0], area[1], area[2], area[3]]

    out_nc.parent.mkdir(parents=True, exist_ok=True)
    tmp_nc = out_nc.with_suffix(out_nc.suffix + ".tmp")
    if tmp_nc.exists():
        tmp_nc.unlink()
    c.retrieve("reanalysis-era5-single-levels-monthly-means", req, str(tmp_nc))
    os.replace(tmp_nc, out_nc)
    return json.dumps(req, indent=2)


# ----------------------------
# ERA5 daily precip via CDS derived daily statistics
# ----------------------------


def _ensure_datetime_index(df: pd.DataFrame, time_col: str = "time") -> pd.DataFrame:
    df = df.copy()
    df[time_col] = pd.to_datetime(df[time_col], utc=True)
    df = df.sort_values(time_col)
    df = df.set_index(time_col)
    return df


def fetch_hourly_tp_timeseries(
    lat: float, lon: float, start_year: str, end_year: str, cache_dir: Path
) -> pd.Series:
    """
    Fetch ERA5 hourly total_precipitation as a point time-series (nearest ERA5 grid point),
    then return an hourly pandas Series (meters). We'll convert to mm and daily-sum later.

    Uses dataset: reanalysis-era5-single-levels-timeseries (designed for fast point time-series).
    """
    dataset = "reanalysis-era5-single-levels-timeseries"
    cache_csv = (
        cache_dir
        / "era5"
        / f"era5_tp_hourly_timeseries_{lat:.4f}_{lon:.4f}_{start_year}_{end_year}.csv"
    )

    if not cache_csv.exists():
        client = cdsapi.Client()
        request = {
            "variable": ["total_precipitation"],
            "location": {"latitude": float(lat), "longitude": float(lon)},
            "date": [f"{start_year}/{end_year}"],
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
    df = _ensure_datetime_index(df, time_col=time_col)

    if "total_precipitation" in df.columns:
        col = "total_precipitation"
    elif "tp" in df.columns:
        col = "tp"
    else:
        # fallback: assume the only non-time column is the variable
        cols = [c for c in df.columns if c != time_col]
        if len(cols) != 1:
            raise ValueError(
                f"Could not identify precip column in CSV. Columns={list(df.columns)}"
            )
        col = cols[0]

    s = df[col].astype(float)
    s.name = "tp_m_hourly"
    return s
