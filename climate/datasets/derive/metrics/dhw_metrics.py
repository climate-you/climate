from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr

from ..time_agg import annual_group, find_time_dim


def compute_annual_metrics(
    dhw_daily: pd.Series,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Legacy pandas helper kept for local/adhoc analysis scripts.
    """
    dhw_max = annual_group(dhw_daily, how="max").rename("dhw_max_year")
    ge4 = annual_group((dhw_daily >= 4.0).astype("float64"), how="sum").rename(
        "dhw_ge4_days_year"
    )
    ge8 = annual_group((dhw_daily >= 8.0).astype("float64"), how="sum").rename(
        "dhw_ge8_days_year"
    )
    return dhw_max, ge4, ge8


def _prepare_daily_dhw(da_daily: xr.DataArray) -> tuple[xr.DataArray, str]:
    tname = find_time_dim(da_daily)
    da = da_daily.sortby(tname)
    if not np.issubdtype(da[tname].dtype, np.datetime64):
        da = xr.decode_cf(da.to_dataset(name="v"))["v"]
        tname = find_time_dim(da)
    return da, tname


def _yearly_has_obs(da: xr.DataArray, tname: str) -> xr.DataArray:
    # Preserve sparse masks (no-obs cell/year should stay NaN, not 0).
    return da.notnull().groupby(f"{tname}.year").any(dim=tname)


def _yearly_count(
    mask: xr.DataArray, *, tname: str, has_obs: xr.DataArray, name: str
) -> xr.DataArray:
    out = mask.groupby(f"{tname}.year").sum(dim=tname, skipna=True)
    out = out.where(has_obs)
    return out.astype("float32").rename(name)


def dhw_no_risk_days_per_year_xr(da_daily: xr.DataArray) -> xr.DataArray:
    da, tname = _prepare_daily_dhw(da_daily)
    has_obs = _yearly_has_obs(da, tname)
    mask = (da < 4.0) & da.notnull()
    return _yearly_count(
        mask, tname=tname, has_obs=has_obs, name="dhw_no_risk_days_per_year"
    )


def dhw_moderate_risk_days_per_year_xr(da_daily: xr.DataArray) -> xr.DataArray:
    da, tname = _prepare_daily_dhw(da_daily)
    has_obs = _yearly_has_obs(da, tname)
    mask = (da >= 4.0) & (da < 8.0) & da.notnull()
    return _yearly_count(
        mask,
        tname=tname,
        has_obs=has_obs,
        name="dhw_moderate_risk_days_per_year",
    )


def dhw_severe_risk_days_per_year_xr(da_daily: xr.DataArray) -> xr.DataArray:
    da, tname = _prepare_daily_dhw(da_daily)
    has_obs = _yearly_has_obs(da, tname)
    mask = (da >= 8.0) & da.notnull()
    return _yearly_count(
        mask, tname=tname, has_obs=has_obs, name="dhw_severe_risk_days_per_year"
    )


def dhw_risk_score_per_year_xr(da_daily: xr.DataArray) -> xr.DataArray:
    da, tname = _prepare_daily_dhw(da_daily)
    has_obs = _yearly_has_obs(da, tname)
    moderate = _yearly_count(
        (da >= 4.0) & (da < 8.0) & da.notnull(),
        tname=tname,
        has_obs=has_obs,
        name="dhw_moderate_risk_days_per_year",
    )
    severe = _yearly_count(
        (da >= 8.0) & da.notnull(),
        tname=tname,
        has_obs=has_obs,
        name="dhw_severe_risk_days_per_year",
    )
    score = moderate + (2.0 * severe)
    return score.astype("float32").rename("dhw_risk_score_per_year")


def dhw_max_per_year_xr(da_daily: xr.DataArray) -> xr.DataArray:
    da, tname = _prepare_daily_dhw(da_daily)
    has_obs = _yearly_has_obs(da, tname)
    out = da.groupby(f"{tname}.year").max(dim=tname, skipna=True)
    out = out.where(has_obs)
    return out.astype("float32").rename("dhw_max_per_year")
