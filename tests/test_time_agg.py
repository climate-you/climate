"""Tests for climate/datasets/derive/time_agg.py."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from climate.datasets.derive.time_agg import (
    annual_group,
    climatology_mean_from_monthly,
    find_time_dim,
    max_cdd_per_year,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _daily_da(
    values: np.ndarray,
    start: str = "2000-01-01",
    lat: list[float] | None = None,
    lon: list[float] | None = None,
    time_dim: str = "time",
) -> xr.DataArray:
    """Build a (time, latitude, longitude) DataArray with daily timestamps."""
    lat = lat or [0.0]
    lon = lon or [0.0]
    n = values.shape[0]
    times = pd.date_range(start, periods=n, freq="D")
    return xr.DataArray(
        values,
        dims=(time_dim, "latitude", "longitude"),
        coords={time_dim: times, "latitude": lat, "longitude": lon},
    )


def _single_cell_da(daily_values: list[float], start: str = "2000-01-01") -> xr.DataArray:
    arr = np.array(daily_values, dtype=np.float32).reshape(-1, 1, 1)
    return _daily_da(arr, start=start)


# ---------------------------------------------------------------------------
# annual_group
# ---------------------------------------------------------------------------


class TestAnnualGroup:
    def _series(self) -> pd.Series:
        dates = pd.to_datetime(["2020-01-01", "2020-07-01", "2021-01-01", "2021-07-01"])
        return pd.Series([1.0, 3.0, 5.0, 7.0], index=dates)

    def test_mean(self):
        result = annual_group(self._series(), "mean")
        assert result[2020] == pytest.approx(2.0)
        assert result[2021] == pytest.approx(6.0)

    def test_sum(self):
        result = annual_group(self._series(), "sum")
        assert result[2020] == pytest.approx(4.0)
        assert result[2021] == pytest.approx(12.0)

    def test_max(self):
        result = annual_group(self._series(), "max")
        assert result[2020] == pytest.approx(3.0)
        assert result[2021] == pytest.approx(7.0)

    def test_unknown_how_raises(self):
        with pytest.raises(ValueError):
            annual_group(self._series(), "median")

    def test_single_year_single_value(self):
        s = pd.Series([42.0], index=pd.to_datetime(["2020-06-15"]))
        result = annual_group(s, "mean")
        assert result[2020] == pytest.approx(42.0)


# ---------------------------------------------------------------------------
# find_time_dim
# ---------------------------------------------------------------------------


class TestFindTimeDim:
    def _da(self, time_dim: str) -> xr.DataArray:
        times = pd.date_range("2000-01-01", periods=3, freq="D")
        return xr.DataArray(
            np.zeros((3, 2)),
            dims=(time_dim, "x"),
            coords={time_dim: times},
        )

    def test_finds_time(self):
        assert find_time_dim(self._da("time")) == "time"

    def test_finds_valid_time(self):
        assert find_time_dim(self._da("valid_time")) == "valid_time"

    def test_finds_forecast_time(self):
        assert find_time_dim(self._da("forecast_time")) == "forecast_time"

    def test_raises_when_no_time_dim(self):
        da = xr.DataArray(np.zeros((3, 2)), dims=("lat", "lon"))
        with pytest.raises(RuntimeError, match="Could not find a time dimension"):
            find_time_dim(da)


# ---------------------------------------------------------------------------
# max_cdd_per_year
# ---------------------------------------------------------------------------


class TestMaxCddPerYear:
    def test_five_consecutive_dry_days(self):
        # 365-day year: days 10–14 are dry (< 1 mm), rest wet
        vals = np.full(365, 2.0, dtype=np.float32)
        vals[10:15] = 0.0  # 5 dry days
        da = _single_cell_da(vals.tolist())
        result = max_cdd_per_year(da)
        assert result.sizes["year"] == 1
        assert result.values[0, 0, 0] == 5

    def test_dry_run_resets_on_wet_day(self):
        # Pattern: 3 dry, 1 wet, 4 dry → max CDD = 4
        vals = np.full(365, 2.0, dtype=np.float32)
        vals[0:3] = 0.0   # 3 dry
        vals[3] = 5.0     # wet (resets)
        vals[4:8] = 0.0   # 4 dry
        da = _single_cell_da(vals.tolist())
        result = max_cdd_per_year(da)
        assert result.values[0, 0, 0] == 4

    def test_all_wet_gives_zero_cdd(self):
        vals = np.full(365, 5.0, dtype=np.float32)
        da = _single_cell_da(vals.tolist())
        result = max_cdd_per_year(da)
        assert result.values[0, 0, 0] == 0

    def test_all_dry_gives_full_year_cdd(self):
        vals = np.zeros(365, dtype=np.float32)
        da = _single_cell_da(vals.tolist())
        result = max_cdd_per_year(da)
        assert result.values[0, 0, 0] == 365

    def test_all_nan_year_produces_nan(self):
        vals = np.full(365, np.nan, dtype=np.float32)
        da = _single_cell_da(vals.tolist())
        result = max_cdd_per_year(da)
        assert np.isnan(result.values[0, 0, 0])

    def test_dry_run_does_not_carry_across_year_boundary(self):
        # Year 2000 ends with 5 dry days; year 2001 starts with 3 dry days.
        # Each year is processed independently — no carry-over.
        days_2000 = 366  # 2000 is a leap year
        days_2001 = 365
        vals = np.full(days_2000 + days_2001, 5.0, dtype=np.float32)
        vals[days_2000 - 5 : days_2000] = 0.0   # last 5 days of 2000 dry
        vals[days_2000 : days_2000 + 3] = 0.0   # first 3 days of 2001 dry
        arr = vals.reshape(-1, 1, 1).astype(np.float32)
        da = _daily_da(arr, start="2000-01-01")
        result = max_cdd_per_year(da)
        assert result.sizes["year"] == 2
        year_idx = {int(y): i for i, y in enumerate(result["year"].values)}
        assert result.values[year_idx[2000], 0, 0] == 5
        assert result.values[year_idx[2001], 0, 0] == 3

    def test_two_years_processed_separately(self):
        # Year 2000: max CDD = 7; year 2001: max CDD = 2
        days_2000 = 366
        days_2001 = 365
        vals = np.full(days_2000 + days_2001, 5.0, dtype=np.float32)
        vals[50:57] = 0.0    # 7 consecutive dry in 2000
        vals[days_2000 + 10 : days_2000 + 12] = 0.0  # 2 consecutive dry in 2001
        arr = vals.reshape(-1, 1, 1).astype(np.float32)
        da = _daily_da(arr, start="2000-01-01")
        result = max_cdd_per_year(da)
        year_idx = {int(y): i for i, y in enumerate(result["year"].values)}
        assert result.values[year_idx[2000], 0, 0] == 7
        assert result.values[year_idx[2001], 0, 0] == 2

    def test_custom_threshold(self):
        # threshold=5mm: values of 3mm count as dry
        vals = np.full(365, 3.0, dtype=np.float32)
        vals[0:4] = 3.0   # all below threshold=5 → all dry → CDD=365
        da = _single_cell_da(vals.tolist())
        result = max_cdd_per_year(da, dry_day_threshold_mm=5.0)
        assert result.values[0, 0, 0] == 365

    def test_output_coords_include_year_and_lat_lon(self):
        vals = np.zeros(365, dtype=np.float32)
        da = _single_cell_da(vals.tolist())
        result = max_cdd_per_year(da)
        assert "year" in result.dims
        assert "latitude" in result.dims
        assert "longitude" in result.dims

    def test_empty_input_returns_zero_length_year_dim(self):
        # Zero-day array → no years → empty output
        arr = np.empty((0, 1, 1), dtype=np.float32)
        times = pd.DatetimeIndex([])
        da = xr.DataArray(arr, dims=("time", "latitude", "longitude"),
                          coords={"time": times, "latitude": [0.0], "longitude": [0.0]})
        result = max_cdd_per_year(da)
        assert result.sizes["year"] == 0

    def test_alternate_time_dim_name(self):
        # DataArray with "valid_time" instead of "time"
        vals = np.full(365, 0.0, dtype=np.float32).reshape(-1, 1, 1)
        da = _daily_da(vals, time_dim="valid_time")
        result = max_cdd_per_year(da)
        assert result.values[0, 0, 0] == 365


# ---------------------------------------------------------------------------
# climatology_mean_from_monthly
# ---------------------------------------------------------------------------


class TestClimatologyMeanFromMonthly:
    def _monthly_da(self, start: str = "1990-01", periods: int = 120) -> xr.DataArray:
        """Build a (time, lat, lon) monthly DataArray."""
        times = pd.date_range(start, periods=periods, freq="MS")
        vals = np.arange(periods, dtype=np.float32).reshape(periods, 1, 1)
        return xr.DataArray(
            vals,
            dims=("time", "latitude", "longitude"),
            coords={"time": times, "latitude": [0.0], "longitude": [0.0]},
        )

    def test_baseline_mean_covers_selected_years(self):
        # 120 months = 10 years (1990–1999).
        # Baseline 1990–1994 (5 years = 60 months, values 0–59).
        da = self._monthly_da()
        result = climatology_mean_from_monthly(da, start_year=1990, end_year=1994)
        expected_mean = np.mean(np.arange(60, dtype=np.float32))
        assert result.values[0, 0, 0] == pytest.approx(expected_mean, rel=1e-4)

    def test_result_has_single_year_dimension(self):
        da = self._monthly_da()
        result = climatology_mean_from_monthly(da, start_year=1990, end_year=1994)
        assert result.sizes["year"] == 1

    def test_label_year_overrides_end_year(self):
        da = self._monthly_da()
        result = climatology_mean_from_monthly(
            da, start_year=1990, end_year=1994, label_year=1950
        )
        assert int(result["year"].values[0]) == 1950

    def test_default_label_year_is_end_year(self):
        da = self._monthly_da()
        result = climatology_mean_from_monthly(da, start_year=1990, end_year=1994)
        assert int(result["year"].values[0]) == 1994

    def test_raises_when_window_outside_data_range(self):
        da = self._monthly_da(start="1990-01", periods=12)  # only 1990
        with pytest.raises(RuntimeError, match="No monthly data in requested climatology window"):
            climatology_mean_from_monthly(da, start_year=2050, end_year=2060)
