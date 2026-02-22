from __future__ import annotations

import numpy as np
import xarray as xr

from climate.datasets.derive.metrics.dhw_metrics import (
    dhw_no_risk_days_per_year_xr,
    dhw_moderate_risk_days_per_year_xr,
    dhw_severe_risk_days_per_year_xr,
    dhw_risk_score_per_year_xr,
    dhw_max_per_year_xr,
)


def _sample_dhw_daily() -> xr.DataArray:
    time = np.array(
        ["1985-01-01", "1985-01-02", "1986-01-01", "1986-01-02"],
        dtype="datetime64[ns]",
    )
    # shape: (time, lat, lon)
    values = np.array(
        [
            [[0.0, np.nan], [np.nan, 2.0]],
            [[5.0, np.nan], [6.0, 2.0]],
            [[9.0, np.nan], [np.nan, 2.0]],
            [[3.0, np.nan], [8.0, 2.0]],
        ],
        dtype=np.float32,
    )
    return xr.DataArray(
        values,
        dims=("time", "latitude", "longitude"),
        coords={
            "time": time,
            "latitude": [0.0, 1.0],
            "longitude": [10.0, 11.0],
        },
        name="degree_heating_week",
    )


def test_dhw_yearly_risk_counts_and_score() -> None:
    da = _sample_dhw_daily()

    no_risk = dhw_no_risk_days_per_year_xr(da)
    moderate = dhw_moderate_risk_days_per_year_xr(da)
    severe = dhw_severe_risk_days_per_year_xr(da)
    score = dhw_risk_score_per_year_xr(da)

    assert list(no_risk["year"].values.tolist()) == [1985, 1986]

    # (lat=0, lon=10): [0,5] then [9,3]
    assert float(no_risk.sel(year=1985, latitude=0.0, longitude=10.0)) == 1.0
    assert float(moderate.sel(year=1985, latitude=0.0, longitude=10.0)) == 1.0
    assert float(severe.sel(year=1985, latitude=0.0, longitude=10.0)) == 0.0
    assert float(score.sel(year=1985, latitude=0.0, longitude=10.0)) == 1.0

    assert float(no_risk.sel(year=1986, latitude=0.0, longitude=10.0)) == 1.0
    assert float(moderate.sel(year=1986, latitude=0.0, longitude=10.0)) == 0.0
    assert float(severe.sel(year=1986, latitude=0.0, longitude=10.0)) == 1.0
    assert float(score.sel(year=1986, latitude=0.0, longitude=10.0)) == 2.0

    # (lat=1, lon=10): [nan,6] then [nan,8]
    assert float(no_risk.sel(year=1985, latitude=1.0, longitude=10.0)) == 0.0
    assert float(moderate.sel(year=1985, latitude=1.0, longitude=10.0)) == 1.0
    assert float(severe.sel(year=1985, latitude=1.0, longitude=10.0)) == 0.0
    assert float(score.sel(year=1985, latitude=1.0, longitude=10.0)) == 1.0

    assert float(no_risk.sel(year=1986, latitude=1.0, longitude=10.0)) == 0.0
    assert float(moderate.sel(year=1986, latitude=1.0, longitude=10.0)) == 0.0
    assert float(severe.sel(year=1986, latitude=1.0, longitude=10.0)) == 1.0
    assert float(score.sel(year=1986, latitude=1.0, longitude=10.0)) == 2.0

    # (lat=0, lon=11): all NaN => all yearly outputs must stay NaN
    for arr in (no_risk, moderate, severe, score):
        assert np.isnan(float(arr.sel(year=1985, latitude=0.0, longitude=11.0)))
        assert np.isnan(float(arr.sel(year=1986, latitude=0.0, longitude=11.0)))


def test_dhw_max_per_year_preserves_mask() -> None:
    da = _sample_dhw_daily()
    dhw_max = dhw_max_per_year_xr(da)

    assert float(dhw_max.sel(year=1985, latitude=0.0, longitude=10.0)) == 5.0
    assert float(dhw_max.sel(year=1986, latitude=0.0, longitude=10.0)) == 9.0
    assert np.isnan(float(dhw_max.sel(year=1985, latitude=0.0, longitude=11.0)))
