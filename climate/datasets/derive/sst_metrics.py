import pandas as pd

from .time_agg import annual_group
from .climatology import daily_mean_p90

# Baseline for anomalies / thresholds
BASELINE_START = "1981-01-01"
BASELINE_END = "2010-12-31"


def _drop_feb29(s: pd.Series) -> pd.Series:
    idx = pd.DatetimeIndex(s.index)
    mask = ~((idx.month == 2) & (idx.day == 29))
    return s.loc[mask]


def compute_anom_and_hotdays(sst_daily: pd.Series) -> tuple[pd.Series, pd.Series]:
    sst = _drop_feb29(sst_daily)
    clim_mean, clim_p90 = daily_mean_p90(sst, BASELINE_START, BASELINE_END)

    doy = sst.index.dayofyear
    anom = sst.values - clim_mean.reindex(doy).values
    anom = pd.Series(anom, index=sst.index, name="sst_anom_c")

    hot = (sst.values > clim_p90.reindex(doy).values).astype("float64")
    hot = pd.Series(hot, index=sst.index, name="sst_hot_flag")

    anom_year = annual_group(anom, how="mean").rename("sst_anom_year_c")
    hotdays_year = annual_group(hot, how="sum").rename("sst_hotdays_p90_year")

    return anom_year, hotdays_year
