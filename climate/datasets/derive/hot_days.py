from __future__ import annotations

import warnings

import xarray as xr


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

    # Fully masked cells (e.g., land in SST fields) can trigger
    # "All-NaN slice encountered" from NumPy during grouped quantile.
    # This warning is expected for masked domains and does not change outputs.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="All-NaN slice encountered",
            category=RuntimeWarning,
        )
        p90 = baseline.groupby(f"{tname}.dayofyear").quantile(q, dim=tname, skipna=True)
    if "quantile" in p90.dims:
        p90 = p90.sel(quantile=q, drop=True)

    hot = da.groupby(f"{tname}.dayofyear") > p90
    hotdays = hot.groupby(f"{tname}.year").sum(dim=tname, skipna=True)
    # Preserve missing-domain masks (e.g. land for SST) as NaN instead of 0.
    has_obs = da.notnull().groupby(f"{tname}.year").any(dim=tname)
    hotdays = hotdays.where(has_obs)
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
