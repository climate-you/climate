from __future__ import annotations

import json

import numpy as np
import pytest

from climate.packager.maps import (
    _load_metric_axis,
    compute_monthly_climatology_anomaly,
)
from climate.tiles.layout import grid_from_id


class TestLoadMetricAxis:
    """Regression: monthly/daily axes must not be coerced to int (the anomaly
    metric loads a monthly input, which previously crashed on int("1979-01"))."""

    def _write_axis(self, tmp_path, metric_id, axis_name, values):
        grid = grid_from_id("global_0p25", tile_size=64)
        d = tmp_path / grid.grid_id / metric_id / "time"
        d.mkdir(parents=True)
        (d / f"{axis_name}.json").write_text(json.dumps(values))
        return grid

    def test_yearly_axis_returns_ints(self, tmp_path):
        grid = self._write_axis(tmp_path, "m_year", "yearly", [2024, 2025])
        axis = _load_metric_axis(tmp_path, grid, "m_year", "yearly")
        assert axis == [2024, 2025]
        assert all(isinstance(v, int) for v in axis)

    def test_monthly_axis_returns_strings(self, tmp_path):
        grid = self._write_axis(
            tmp_path, "m_month", "monthly", ["1979-01", "2026-06"]
        )
        axis = _load_metric_axis(tmp_path, grid, "m_month", "monthly")
        assert axis == ["1979-01", "2026-06"]
        assert all(isinstance(v, str) for v in axis)

    def test_missing_axis_returns_empty(self, tmp_path):
        grid = grid_from_id("global_0p25", tile_size=64)
        assert _load_metric_axis(tmp_path, grid, "absent", "monthly") == []


def _synthetic_series():
    """2x2 grid, monthly axis 1991-01 .. 2026-06."""
    axis = [f"{y:04d}-{m:02d}" for y in range(1991, 2026) for m in range(1, 13)]
    axis += [f"2026-{m:02d}" for m in range(1, 7)]
    series = np.zeros((2, 2, len(axis)), dtype=np.float64)
    for i, label in enumerate(axis):
        y, mo = int(label[:4]), int(label[5:7])
        # Cell (0,0): every June is 20 except June 2026 which is 24 -> +4.
        if mo == 6:
            series[0, 0, i] = 24.0 if y == 2026 else 20.0
    return series, axis


def test_known_anomaly():
    series, axis = _synthetic_series()
    anom = compute_monthly_climatology_anomaly(
        series, axis, target_year=2026, target_month=6,
        clim_start_year=1991, clim_end_year=2020,
    )
    assert anom.shape == (2, 2)
    assert anom[0, 0] == pytest.approx(4.0)


def test_climatology_window_is_respected():
    series, axis = _synthetic_series()
    # Make 2021-2025 Junes hot; they must NOT enter a 1991-2020 climatology.
    for i, label in enumerate(axis):
        y, mo = int(label[:4]), int(label[5:7])
        if mo == 6 and 2021 <= y <= 2025:
            series[0, 0, i] = 100.0
    anom = compute_monthly_climatology_anomaly(
        series, axis, target_year=2026, target_month=6,
        clim_start_year=1991, clim_end_year=2020,
    )
    assert anom[0, 0] == pytest.approx(4.0)


def test_all_nan_cell_is_nan():
    series, axis = _synthetic_series()
    series[1, 1, :] = np.nan
    anom = compute_monthly_climatology_anomaly(
        series, axis, target_year=2026, target_month=6,
        clim_start_year=1991, clim_end_year=2020,
    )
    assert np.isnan(anom[1, 1])


def test_missing_target_month_raises():
    series, axis = _synthetic_series()
    with pytest.raises(ValueError):
        compute_monthly_climatology_anomaly(
            series, axis, target_year=2027, target_month=6,
            clim_start_year=1991, clim_end_year=2020,
        )


def test_missing_climatology_raises():
    series, axis = _synthetic_series()
    with pytest.raises(ValueError):
        compute_monthly_climatology_anomaly(
            series, axis, target_year=2026, target_month=6,
            clim_start_year=1800, clim_end_year=1850,
        )
