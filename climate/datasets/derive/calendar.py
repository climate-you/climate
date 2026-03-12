from __future__ import annotations

import pandas as pd
import xarray as xr


def drop_feb29(s: pd.Series) -> pd.Series:
    idx = pd.DatetimeIndex(s.index)
    mask = ~((idx.month == 2) & (idx.day == 29))
    return s.loc[mask]


def drop_feb29_xr(da: xr.DataArray, time_dim: str = "time") -> xr.DataArray:
    time = da[time_dim]
    is_feb29 = (time.dt.month == 2) & (time.dt.day == 29)
    return da.sel({time_dim: ~is_feb29})
