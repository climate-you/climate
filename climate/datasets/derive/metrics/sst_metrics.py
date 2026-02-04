import pandas as pd

from ..time_agg import annual_group
from ..climatology import daily_mean_p90
from ..hot_days import hot_days_per_year
from ..calendar import drop_feb29

# Baseline for anomalies / thresholds
BASELINE_START = "1981-01-01"
BASELINE_END = "2010-12-31"


def compute_anom_and_hotdays(sst_daily: pd.Series) -> tuple[pd.Series, pd.Series]:
    sst = drop_feb29(sst_daily)
    clim_mean, clim_p90 = daily_mean_p90(sst, BASELINE_START, BASELINE_END)

    doy = sst.index.dayofyear
    anom = sst.values - clim_mean.reindex(doy).values
    anom = pd.Series(anom, index=sst.index, name="sst_anom_c")

    anom_year = annual_group(anom, how="mean").rename("sst_anom_year_c")
    hotdays_year = hot_days_per_year(sst, baseline_years=10, percentile=90.0).rename(
        "sst_hotdays_p90_year"
    )

    return anom_year, hotdays_year
