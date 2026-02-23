from pathlib import Path
from typing import List, Tuple

import pandas as pd
import zipfile

from climate.datasets.sources.cds import retrieve


ERA5_MONTHLY_MEANS_DATASET = "reanalysis-era5-single-levels-monthly-means"
ERA5_DAILY_STATS_DATASET = "derived-era5-single-levels-daily-statistics"


def build_monthly_means_request(
    *,
    years: List[str],
    grid_deg: float,
    area: Tuple[float, float, float, float] | None,
    variable: str = "2m_temperature",
) -> dict:
    req = {
        "product_type": "monthly_averaged_reanalysis",
        "data_format": "netcdf",
        "variable": [variable],
        "year": years,
        "month": [f"{m:02d}" for m in range(1, 13)],
        "time": ["00:00"],
        # Coarsen the native 0.25° grid to keep files reasonable for a web app.
        "grid": [grid_deg, grid_deg],
    }
    if area is not None:
        # CDS uses [N, W, S, E]
        req["area"] = [area[0], area[1], area[2], area[3]]
    return req


def download_monthly_means(
    out_nc: Path,
    years: List[str],
    grid_deg: float,
    area: Tuple[float, float, float, float] | None,
    *,
    variable: str = "2m_temperature",
    overwrite: bool = False,
) -> dict:
    """Download monthly ERA5 data from CDS and return the request dict."""
    req = build_monthly_means_request(
        years=years,
        grid_deg=grid_deg,
        area=area,
        variable=variable,
    )
    retrieve(ERA5_MONTHLY_MEANS_DATASET, req, out_nc, overwrite=overwrite)
    return req


def build_daily_stats_request(
    *,
    years: List[str],
    grid_deg: float,
    area: Tuple[float, float, float, float] | None,
    variable: str = "2m_temperature",
    daily_statistic: str = "daily_mean",
    time_zone: str | None = "utc+00:00",
    frequency: str | None = "1_hourly",
    months: list[str] | None = None,
    days: list[str] | None = None,
) -> dict:
    if months is not None and days is None:
        if not months:
            raise ValueError("months must contain at least one month")
        year_list = [int(y) for y in years]
        if len(set(year_list)) != 1:
            raise ValueError("years must be a single year when months is set")
        days = [f"{d:02d}" for d in range(1, 32)]
    req = {
        "product_type": "reanalysis",
        "variable": [variable],
        "year": years,
        "month": months if months is not None else [f"{m:02d}" for m in range(1, 13)],
        "day": days if days is not None else [f"{d:02d}" for d in range(1, 32)],
        "daily_statistic": daily_statistic,
        "format": "netcdf",
        "grid": [grid_deg, grid_deg],
    }
    if time_zone is not None:
        req["time_zone"] = time_zone
    if frequency is not None:
        req["frequency"] = frequency
    if area is not None:
        req["area"] = [area[0], area[1], area[2], area[3]]
    return req


def download_daily_stats(
    out_nc: Path,
    years: List[str],
    grid_deg: float,
    area: Tuple[float, float, float, float] | None,
    *,
    variable: str = "2m_temperature",
    daily_statistic: str = "daily_mean",
    time_zone: str = "utc+00:00",
    frequency: str | None = "1_hourly",
    overwrite: bool = False,
) -> dict:
    req = build_daily_stats_request(
        years=years,
        grid_deg=grid_deg,
        area=area,
        variable=variable,
        daily_statistic=daily_statistic,
        time_zone=time_zone,
        frequency=frequency,
    )
    retrieve(ERA5_DAILY_STATS_DATASET, req, out_nc, overwrite=overwrite)
    return req


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
        import cdsapi

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
