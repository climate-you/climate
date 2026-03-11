from typing import List, Tuple


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


