import pandas as pd

from .calendar import drop_feb29


def daily_mean_p90(
    s_daily: pd.Series, baseline_start: str, baseline_end: str
) -> tuple[pd.Series, pd.Series]:
    s = drop_feb29(s_daily)
    base = s.loc[
        (s.index >= pd.Timestamp(baseline_start))
        & (s.index <= pd.Timestamp(baseline_end))
    ]
    if len(base) < 365 * 5:
        raise RuntimeError("Not enough baseline data to compute SST climatology.")
    doy = base.index.dayofyear
    df = pd.DataFrame({"v": base.values, "doy": doy})
    clim_mean = df.groupby("doy")["v"].mean()
    clim_p90 = df.groupby("doy")["v"].quantile(0.9)
    return clim_mean, clim_p90


