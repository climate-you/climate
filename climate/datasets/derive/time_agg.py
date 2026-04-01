import pandas as pd
import xarray as xr
import numpy as np


def annual_group(s: pd.Series, how: str) -> pd.Series:
    y = s.index.year
    if how == "mean":
        return s.groupby(y).mean()
    if how == "sum":
        return s.groupby(y).sum()
    if how == "max":
        return s.groupby(y).max()
    raise ValueError(how)


def daily_to_monthly_and_yearly_t2m(ds_daily: xr.Dataset):
    """From daily dataset, derive monthly and yearly mean series."""
    monthly_mean = ds_daily["t2m_daily_mean_c"].resample(time="MS").mean()
    monthly_min = ds_daily["t2m_daily_min_c"].resample(time="MS").mean()
    monthly_max = ds_daily["t2m_daily_max_c"].resample(time="MS").mean()

    monthly_mean = monthly_mean.rename(time="time_monthly")
    monthly_min = monthly_min.rename(time="time_monthly")
    monthly_max = monthly_max.rename(time="time_monthly")

    yearly_mean = ds_daily["t2m_daily_mean_c"].resample(time="YS").mean()
    yearly_mean = yearly_mean.rename(time="time_yearly")

    return monthly_mean, monthly_min, monthly_max, yearly_mean


def find_time_dim(da: xr.DataArray) -> str:
    for name in ("time", "valid_time", "forecast_time"):
        if name in da.dims:
            return name
    raise RuntimeError(f"Could not find a time dimension in dims={da.dims}")


def annual_mean_from_monthly(da: xr.DataArray) -> xr.DataArray:
    tname = find_time_dim(da)
    if not np.issubdtype(da[tname].dtype, np.datetime64):
        da = xr.decode_cf(da.to_dataset(name="v"))["v"]
    return da.groupby(f"{tname}.year").mean(tname, keep_attrs=False)


def monthly_mean_from_daily(da: xr.DataArray) -> xr.DataArray:
    tname = find_time_dim(da)
    if not np.issubdtype(da[tname].dtype, np.datetime64):
        da = xr.decode_cf(da.to_dataset(name="v"))["v"]
    return da.resample({tname: "1MS"}).mean(keep_attrs=False)


def annual_mean_from_daily(da: xr.DataArray) -> xr.DataArray:
    monthly = monthly_mean_from_daily(da)
    tname = find_time_dim(monthly)
    return monthly.groupby(f"{tname}.year").mean(tname, keep_attrs=False)


def monthly_max_from_daily(da: xr.DataArray) -> xr.DataArray:
    """Monthly maximum of daily values (e.g. hottest day of each month)."""
    tname = find_time_dim(da)
    if not np.issubdtype(da[tname].dtype, np.datetime64):
        da = xr.decode_cf(da.to_dataset(name="v"))["v"]
    return da.resample({tname: "1MS"}).max(keep_attrs=False)


def monthly_min_from_daily(da: xr.DataArray) -> xr.DataArray:
    """Monthly minimum of daily values (e.g. coldest day of each month)."""
    tname = find_time_dim(da)
    if not np.issubdtype(da[tname].dtype, np.datetime64):
        da = xr.decode_cf(da.to_dataset(name="v"))["v"]
    return da.resample({tname: "1MS"}).min(keep_attrs=False)


def climatology_mean_from_monthly(
    da: xr.DataArray,
    *,
    start_year: int,
    end_year: int,
    label_year: int | None = None,
) -> xr.DataArray:
    """
    Mean over a fixed monthly baseline period, returned as a single yearly point.
    """
    tname = find_time_dim(da)
    if not np.issubdtype(da[tname].dtype, np.datetime64):
        da = xr.decode_cf(da.to_dataset(name="v"))["v"]

    years = da[tname].dt.year
    mask = (years >= int(start_year)) & (years <= int(end_year))
    da_sel = da.where(mask, drop=True)
    if da_sel.sizes.get(tname, 0) == 0:
        raise RuntimeError(
            f"No monthly data in requested climatology window {start_year}-{end_year}"
        )

    mean_da = da_sel.mean(tname, keep_attrs=False)
    out_year = int(label_year) if label_year is not None else int(end_year)
    return mean_da.expand_dims(year=[out_year])
