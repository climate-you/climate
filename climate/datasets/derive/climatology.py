import pandas as pd
import xarray as xr
import numpy as np


def _drop_feb29(s: pd.Series) -> pd.Series:
    idx = pd.DatetimeIndex(s.index)
    mask = ~((idx.month == 2) & (idx.day == 29))
    return s.loc[mask]


def daily_mean_p90(
    s_daily: pd.Series, baseline_start: str, baseline_end: str
) -> tuple[pd.Series, pd.Series]:
    s = _drop_feb29(s_daily)
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


def derive_monthly_climatologies(
    ds_daily: xr.Dataset, past_years=10, recent_years=10
) -> tuple[xr.DataArray | None, xr.DataArray | None]:
    """Compute past vs recent monthly climatology for daily mean temperature."""
    da = ds_daily["t2m_daily_mean_c"]
    years = da["time"].dt.year

    min_year = int(years.min().item())
    max_year = int(years.max().item())
    n_years = max_year - min_year + 1

    min_needed = past_years + recent_years
    if n_years < min_needed:
        print(
            f"  [warn] record too short for climatologies: {n_years} years, need at least {min_needed}"
        )
        return None, None

    past_start = min_year
    past_end = min_year + past_years - 1

    recent_end = max_year
    recent_start = max_year - recent_years + 1

    print(
        f"  [info] climatology windows: past={past_start}–{past_end}, recent={recent_start}–{recent_end}"
    )

    # Monthly means from daily – 'ME' to avoid xarray warning
    da_mon = da.resample(time="ME").mean()

    mask_past = (da_mon["time"].dt.year >= past_start) & (
        da_mon["time"].dt.year <= past_end
    )
    mon_past = da_mon.where(mask_past, drop=True)

    if mon_past.time.size == 0:
        past_clim = None
    else:
        past_clim = mon_past.groupby("time.month").mean("time")
        past_clim = past_clim.rename(month="month").assign_coords(
            month=np.arange(1, 13)
        )

    mask_recent = (da_mon["time"].dt.year >= recent_start) & (
        da_mon["time"].dt.year <= recent_end
    )
    mon_recent = da_mon.where(mask_recent, drop=True)

    if mon_recent.time.size == 0:
        recent_clim = None
    else:
        recent_clim = mon_recent.groupby("time.month").mean("time")
        recent_clim = recent_clim.rename(month="month").assign_coords(
            month=np.arange(1, 13)
        )

    return past_clim, recent_clim
