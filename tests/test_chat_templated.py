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


# ---------------------------------------------------------------------------
# Region answers (a country or sea selected from search)
# ---------------------------------------------------------------------------


def _region(name, rtype, values):
    return {"name": name, "type": rtype, "cell_count": 10, "values": values}


def _monthly_axis(start=2016, end=2025):
    return [f"{y}-{m:02d}" for y in range(start, end + 1) for m in range(1, 13)]


class _RegionStore:
    """Just the aggregates a region answer reads; no grid cells at all."""

    def __init__(self, with_max=True):
        years = list(range(1979, 2026))
        warming = [20.0 + 0.03 * (y - 1979) for y in years]
        axis = _monthly_axis()
        hot_mean = [30.0 + (5.0 if a.endswith("-07") else 0.0) for a in axis]
        hot_max = [40.0 + (8.0 if a == "2023-07" else 0.0) for a in axis]
        self.aggregates = {
            ("t2m_yearly_mean_c", "mean"): {
                "time_axis": years,
                "regions": {
                    "country:EG": _region("Egypt", "country", warming),
                    "country:US": _region("United States", "country", [12.0] * 47),
                    "country:NO": _region("Norway", "country", [2.0] * 47),
                    "ocean:adriatic_sea": _region("Adriatic Sea", "ocean", warming),
                    "globe": _region(
                        "Global", "globe", [14.0 + 0.02 * (y - 1979) for y in years]
                    ),
                },
            },
            ("t2m_monthly_max_c", "mean"): {
                "time_axis": axis,
                "regions": {"country:EG": _region("Egypt", "country", hot_mean)},
            },
        }
        if with_max:
            self.aggregates[("t2m_monthly_max_c", "max")] = {
                "time_axis": axis,
                "regions": {"country:EG": _region("Egypt", "country", hot_max)},
            }
        self.metrics = {}
        self.rankings = {}

    def try_get_metric_vector(self, *args):
        raise AssertionError("a region answer must not read a grid cell")


def _place(store, region_id, label, lat=26.5):
    from climate_api.chat.templated import _Place

    return _Place(store, lat, 30.0, label, region_id)


class TestRegionTemplates:
    def test_trend_reads_the_region_aggregate(self):
        from climate_api.chat.templated import _gen_local_temp_trend

        answer, spec = _gen_local_temp_trend(
            _place(_RegionStore(), "country:EG", "Egypt")
        )
        assert answer.startswith(
            "**Egypt** has warmed at **[[0.3°C|0.54°F]] per decade**"
        )
        assert "averaged across the country" in answer
        assert spec["metric_id"] == "t2m_yearly_mean_c"

    def test_article_is_added_and_capitalised(self):
        from climate_api.chat.templated import _gen_local_vs_global

        answer, _ = _gen_local_vs_global(
            _place(_RegionStore(), "ocean:adriatic_sea", "Adriatic Sea")
        )
        assert answer.startswith("The **Adriatic Sea** is warming")
        assert "open oceans" in answer

    def test_hottest_days_record_comes_from_the_hottest_cell(self):
        from climate_api.chat.templated import _gen_local_summer_heat

        answer, _ = _gen_local_summer_heat(
            _place(_RegionStore(), "country:EG", "Egypt")
        )
        assert answer.startswith("Averaged across **Egypt**, the hottest days")
        assert "about **[[35.0°C|95.0°F]]** in July" in answer
        assert "anywhere in Egypt in our data is **[[48.0°C|118.4°F]]**" in answer
        assert "July 2023" in answer

    def test_hottest_days_without_a_cell_record_says_averaged(self):
        from climate_api.chat.templated import _gen_local_summer_heat

        answer, _ = _gen_local_summer_heat(
            _place(_RegionStore(with_max=False), "country:EG", "Egypt")
        )
        assert "anywhere" not in answer
        assert "averaged across it in our data" in answer

    def test_country_rank_is_among_countries_only(self):
        from climate_api.chat.templated import _gen_local_rank

        answer, _ = _gen_local_rank(
            _place(_RegionStore(), "country:US", "United States")
        )
        # Egypt is warmer, Norway colder; the sea and the globe are not ranked.
        assert answer.startswith("The **United States** ranks **#2** warmest out of 3")

    def test_unsupported_region_questions_fall_back(self):
        from climate_api.chat.templated import (
            _gen_coral_risk_local,
            _gen_local_rank,
            _gen_sea_temp_local,
        )

        store = _RegionStore()
        assert _gen_sea_temp_local(_place(store, "country:EG", "Egypt")) is None
        assert (
            _gen_coral_risk_local(_place(store, "ocean:adriatic_sea", "Adriatic Sea"))
            is None
        )
        assert (
            _gen_local_rank(_place(store, "ocean:adriatic_sea", "Adriatic Sea")) is None
        )

    def test_generate_charts_the_region_with_no_pin(self, monkeypatch):
        captured = {}

        def fake_charts(locations, chart_spec, tile_store, unit):
            captured["locations"] = locations
            return [{"title": "t", "unit": "C", "series": []}]

        monkeypatch.setattr("climate_api.chat.canned.build_canned_charts", fake_charts)
        result = generate(
            "local_vs_global",
            26.5,
            30.0,
            "Egypt",
            _RegionStore(),
            region_id="country:EG",
        )
        assert result["locations"] == []
        assert captured["locations"] == []
        assert result["chart_spec"]["region_ids"] == ["country:EG", "globe"]
        assert "extra_region_ids" not in result["chart_spec"]

    def test_microstates_are_not_ranked(self):
        from climate_api.chat.templated import _gen_local_rank

        store = _RegionStore()
        regions = store.aggregates[("t2m_yearly_mean_c", "mean")]["regions"]
        regions["country:LI"] = {
            **_region("Liechtenstein", "country", [30.0] * 47),
            "cell_count": 1,
        }
        answer, _ = _gen_local_rank(_place(store, "country:US", "United States"))
        assert "out of 3" in answer  # Liechtenstein is not counted
        assert _gen_local_rank(_place(store, "country:LI", "Liechtenstein")) is None

    def test_antarctica_is_not_ranked(self):
        from climate_api.chat.templated import _gen_local_rank

        store = _RegionStore()
        regions = store.aggregates[("t2m_yearly_mean_c", "mean")]["regions"]
        regions["country:AQ"] = _region("Antarctica", "country", [-35.0] * 47)
        answer, _ = _gen_local_rank(_place(store, "country:NO", "Norway"))
        assert "#3** warmest out of 3" in answer
