from __future__ import annotations

import pandas as pd
import xarray as xr

from .climatology import daily_mean_p90


def hot_days_per_year(
    s_daily: pd.Series,
    *,
    baseline_years: int = 10,
    percentile: float = 90.0,
) -> pd.Series:
    if s_daily.empty:
        return pd.Series(dtype=float)

    s_daily = s_daily.sort_index()
    start_year = int(s_daily.index.year.min())
    end_year = start_year + int(baseline_years) - 1
    baseline_start = f"{start_year}-01-01"
    baseline_end = f"{end_year}-12-31"

    clim_mean, clim_p90 = daily_mean_p90(s_daily, baseline_start, baseline_end)
    doy = s_daily.index.dayofyear
    thresh = clim_p90.reindex(doy).values

    hot = (s_daily.values > thresh).astype("float64")
    hot = pd.Series(hot, index=s_daily.index, name="hot_days_flag")
    hotdays_year = hot.resample("YS").sum().rename("hot_days_per_year")
    hotdays_year.index = hotdays_year.index.year
    return hotdays_year


def hot_days_per_year_xr(
    da_daily: xr.DataArray,
    *,
    baseline_years: int = 10,
    percentile: float = 90.0,
    debug: bool = False,
) -> xr.DataArray:
    tname = "time" if "time" in da_daily.dims else da_daily.dims[0]

    da = da_daily.sortby(tname)
    time = da[tname]
    is_feb29 = (time.dt.month == 2) & (time.dt.day == 29)
    da = da.sel({tname: ~is_feb29})

    years = da[tname].dt.year
    start_year = int(years.min().item())
    baseline_end = start_year + int(baseline_years) - 1

    baseline = da.sel({tname: years <= baseline_end})
    q = float(percentile) / 100.0

    p90 = baseline.groupby(f"{tname}.dayofyear").quantile(q, dim=tname, skipna=True)
    if "quantile" in p90.dims:
        p90 = p90.sel(quantile=q, drop=True)

    hot = da.groupby(f"{tname}.dayofyear") > p90
    hotdays = hot.groupby(f"{tname}.year").sum(dim=tname, skipna=True)
    hotdays = hotdays.astype("float32")
    hotdays = hotdays.rename("hot_days_per_year")
    if debug:
        def _scalar(v: xr.DataArray) -> float:
            val = v
            if hasattr(val, "compute"):
                val = val.compute()
            return float(val)

        da_min = _scalar(da.min(skipna=True))
        da_max = _scalar(da.max(skipna=True))
        p90_min = _scalar(p90.min(skipna=True))
        p90_max = _scalar(p90.max(skipna=True))
        hd_min = _scalar(hotdays.min(skipna=True))
        hd_max = _scalar(hotdays.max(skipna=True))
        print(
            "[hot_days_per_year] stats: "
            f"da_min={da_min:.3f} da_max={da_max:.3f} "
            f"p90_min={p90_min:.3f} p90_max={p90_max:.3f} "
            f"hotdays_min={hd_min:.3f} hotdays_max={hd_max:.3f}"
        )
    return hotdays
