from __future__ import annotations

import numpy as np

from climate_api.chat.templated import (
    _axis_month_name,
    _monthly_typical_extreme,
    _seasonal_yearly_means,
    _tok,
    _trend_per_decade,
    generate,
)


class TestTok:
    def test_absolute_conversion(self):
        assert _tok(20.0) == "[[20.0°C|68.0°F]]"

    def test_delta_conversion_scale_only(self):
        assert _tok(0.5, delta=True, nd=2) == "[[0.5°C|0.9°F]]"

    def test_negative_absolute(self):
        assert _tok(-1.6) == "[[-1.6°C|29.1°F]]"

    def test_rounding_precision(self):
        assert _tok(0.213, delta=True, nd=2) == "[[0.21°C|0.38°F]]"


class TestAxisMonthName:
    def test_formats_month_and_year(self):
        assert _axis_month_name("2003-08") == "August 2003"


class TestTrendPerDecade:
    def test_linear_series(self):
        years = np.arange(1979, 2026, dtype=np.float64)
        values = (years - 1979) * 0.02  # 0.02/year = 0.2/decade
        assert abs(_trend_per_decade(years, values) - 0.2) < 1e-9

    def test_ignores_nans(self):
        years = np.arange(2000, 2010, dtype=np.float64)
        values = years * 0.1
        values[3] = np.nan
        assert _trend_per_decade(years, values) is not None

    def test_too_few_points(self):
        assert _trend_per_decade(np.array([2000.0]), np.array([1.0])) is None


class TestMonthlyHelpers:
    def _axis(self, start_year, end_year):
        return [
            f"{y}-{m:02d}"
            for y in range(start_year, end_year + 1)
            for m in range(1, 13)
        ]

    def test_typical_extreme_max_picks_hottest_month(self):
        axis = self._axis(2016, 2025)
        # July (index 6) is always the hottest month
        values = np.array([20.0 + (5.0 if a.endswith("-07") else 0.0) for a in axis])
        result = _monthly_typical_extreme(axis, values, extreme="max")
        assert result is not None
        value, month = result
        assert month == 7
        assert abs(value - 25.0) < 1e-9

    def test_seasonal_means_southern_hemisphere_months(self):
        axis = self._axis(2020, 2021)
        values = np.array(
            [10.0 if int(a.split("-")[1]) in (6, 7, 8) else 0.0 for a in axis]
        )
        years, means = _seasonal_yearly_means(axis, values, [6, 7, 8])
        assert list(years) == [2020.0, 2021.0]
        assert all(abs(m - 10.0) < 1e-9 for m in means)


class TestGenerate:
    def test_unknown_question_id_returns_none(self):
        assert (
            generate("no_such_question", 48.85, 2.35, "Paris", tile_store=None) is None
        )

    def test_non_local_question_returns_none(self):
        # A canned global question must not be templated
        assert (
            generate("global_temp_change", 48.85, 2.35, "Paris", tile_store=None)
            is None
        )

    def test_generator_exception_falls_back_to_none(self):
        # tile_store=None raises inside the generator; generate() must swallow it
        assert (
            generate("local_temp_trend", 48.85, 2.35, "Paris", tile_store=None) is None
        )
