from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr

from climate.datasets.derive.time_agg import annual_sum_from_daily
from climate.packager.registry import _apply_postprocess


def test_annual_sum_from_daily_uses_valid_time_and_preserves_nan_cells() -> None:
    time = pd.to_datetime([
        "2024-01-01",
        "2024-01-02",
        "2025-01-01",
        "2025-01-02",
    ])

    data = np.array(
        [
            [[1.0, np.nan]],
            [[2.0, np.nan]],
            [[3.0, np.nan]],
            [[4.0, np.nan]],
        ],
        dtype=np.float32,
    )

    da = xr.DataArray(
        data,
        dims=("valid_time", "latitude", "longitude"),
        coords={
            "valid_time": time,
            "latitude": [0.0],
            "longitude": [10.0, 20.0],
        },
        name="tp",
    )

    out = annual_sum_from_daily(da)

    assert out.dims == ("year", "latitude", "longitude")
    assert out.dtype == np.float32
    assert out.sel(year=2024, latitude=0.0, longitude=10.0).item() == 3.0
    assert out.sel(year=2025, latitude=0.0, longitude=10.0).item() == 7.0
    assert np.isnan(out.sel(year=2024, latitude=0.0, longitude=20.0).item())
    assert np.isnan(out.sel(year=2025, latitude=0.0, longitude=20.0).item())


def test_apply_postprocess_m_to_mm() -> None:
    da = xr.DataArray(np.array([0.0, 0.0015], dtype=np.float32), dims=("x",))
    out = _apply_postprocess(da, [{"fn": "m_to_mm"}])
    np.testing.assert_allclose(out.values, np.array([0.0, 1.5], dtype=np.float32))
