import pandas as pd
import xarray as xr


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
