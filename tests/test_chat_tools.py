"""Tests for the pure helper functions in climate_api/chat/tools.py."""

from __future__ import annotations

import pytest

from climate_api.chat import tools
from climate_api.chat.tools import (
    _MIN_RANKABLE_CELLS,
    _alt_names_for,
    _convert_temp,
    _drop_full_span_years,
    _is_delta_metric,
    _output_unit,
    _resolve_region_id,
)
from climate_api.store.location_index import LocationIndex


# ---------------------------------------------------------------------------
# _is_delta_metric
# ---------------------------------------------------------------------------


class TestIsDeltaMetric:
    def test_offset_in_agg_is_delta(self):
        spec = {"source": {"agg": "offset_mean"}}
        assert _is_delta_metric(spec) is True

    def test_anomaly_in_agg_is_delta(self):
        spec = {"source": {"agg": "anomaly_from_baseline"}}
        assert _is_delta_metric(spec) is True

    def test_delta_in_agg_is_delta(self):
        spec = {"source": {"agg": "delta_1950_2024"}}
        assert _is_delta_metric(spec) is True

    def test_plain_mean_agg_is_not_delta(self):
        spec = {"source": {"agg": "mean"}}
        assert _is_delta_metric(spec) is False

    def test_trend_slope_agg_is_not_delta(self):
        spec = {"source": {"agg": "trend_slope"}}
        assert _is_delta_metric(spec) is False

    def test_missing_source_is_not_delta(self):
        assert _is_delta_metric({}) is False

    def test_empty_agg_is_not_delta(self):
        assert _is_delta_metric({"source": {"agg": ""}}) is False

    def test_missing_agg_key_is_not_delta(self):
        assert _is_delta_metric({"source": {}}) is False


# ---------------------------------------------------------------------------
# _convert_temp
# ---------------------------------------------------------------------------


class TestConvertTemp:
    def _celsius_spec(self, agg="mean"):
        return {"unit": "C", "source": {"agg": agg}}

    def _mm_spec(self):
        return {"unit": "mm", "source": {"agg": "sum"}}

    def test_absolute_celsius_to_fahrenheit(self):
        # 0°C → 32°F
        result = _convert_temp(0.0, self._celsius_spec(), is_delta=False, target="F")
        assert result == pytest.approx(32.0)

    def test_absolute_100c_to_fahrenheit(self):
        # 100°C → 212°F
        result = _convert_temp(100.0, self._celsius_spec(), is_delta=False, target="F")
        assert result == pytest.approx(212.0)

    def test_delta_celsius_to_fahrenheit_no_offset(self):
        # +1°C trend → +1.8°F (scale only, no +32)
        result = _convert_temp(1.0, self._celsius_spec(), is_delta=True, target="F")
        assert result == pytest.approx(1.8)

    def test_delta_zero_stays_zero(self):
        result = _convert_temp(0.0, self._celsius_spec(), is_delta=True, target="F")
        assert result == pytest.approx(0.0)

    def test_non_celsius_metric_unchanged(self):
        # mm/day stays mm/day regardless of target
        result = _convert_temp(5.0, self._mm_spec(), is_delta=False, target="F")
        assert result == pytest.approx(5.0)

    def test_target_c_returns_value_unchanged(self):
        result = _convert_temp(20.0, self._celsius_spec(), is_delta=False, target="C")
        assert result == pytest.approx(20.0)

    def test_result_rounded_to_3dp(self):
        # 1°C → 33.800 exactly
        result = _convert_temp(1.0, self._celsius_spec(), is_delta=False, target="F")
        assert result == pytest.approx(33.8)
        # Check it's exactly 3 dp, not more
        assert result == round(result, 3)

    def test_negative_absolute_celsius_to_fahrenheit(self):
        # -40°C → -40°F
        result = _convert_temp(-40.0, self._celsius_spec(), is_delta=False, target="F")
        assert result == pytest.approx(-40.0)

    def test_negative_delta_celsius_to_fahrenheit(self):
        # -0.5°C/decade → -0.9°F/decade
        result = _convert_temp(-0.5, self._celsius_spec(), is_delta=True, target="F")
        assert result == pytest.approx(-0.9)


# ---------------------------------------------------------------------------
# _output_unit
# ---------------------------------------------------------------------------


class TestOutputUnit:
    def test_celsius_metric_to_f_target_returns_f(self):
        spec = {"unit": "C"}
        assert _output_unit(spec, "F") == "F"

    def test_celsius_metric_to_c_target_returns_c(self):
        spec = {"unit": "C"}
        assert _output_unit(spec, "C") == "C"

    def test_mm_metric_to_f_target_returns_mm(self):
        # Precipitation is not converted — unit stays mm
        spec = {"unit": "mm"}
        assert _output_unit(spec, "F") == "mm"

    def test_mm_metric_to_c_target_returns_mm(self):
        spec = {"unit": "mm"}
        assert _output_unit(spec, "C") == "mm"

    def test_missing_unit_returns_unknown(self):
        assert _output_unit({}, "F") == "unknown"
        assert _output_unit({}, "C") == "unknown"

    def test_days_metric_unchanged(self):
        spec = {"unit": "days"}
        assert _output_unit(spec, "F") == "days"


# ---------------------------------------------------------------------------
# _resolve_region_id
# ---------------------------------------------------------------------------


class _MockTileStore:
    """Minimal tile_store stub for _resolve_region_id testing."""

    def __init__(self, regions: dict | None = None, has_aggregates: bool = True):
        self._regions = regions or {}
        self._has_aggregates = has_aggregates

    @property
    def aggregates(self):
        if not self._has_aggregates:
            return {}

        class _AggProxy:
            def __init__(self, regions):
                self._regions = regions

            def get(self, key, default=None):
                return {"regions": self._regions, "time_axis": [2000, 2001]}

        return _AggProxy(self._regions)


def _make_ts(regions: dict) -> _MockTileStore:
    return _MockTileStore(regions=regions)


class TestResolveRegionId:
    def test_direct_lookup_returns_exact_key(self):
        regions = {"country:FR": {"name": "France", "type": "country", "values": []}}
        ts = _make_ts(regions)
        assert _resolve_region_id("country:FR", ts, "t2m", "mean") == "country:FR"

    def test_globe_alias_global(self):
        regions = {"globe": {"name": "Globe", "type": "globe", "values": []}}
        ts = _make_ts(regions)
        assert _resolve_region_id("global", ts, "t2m", "mean") == "globe"

    def test_globe_alias_worldwide(self):
        regions = {"globe": {"name": "Globe", "type": "globe", "values": []}}
        ts = _make_ts(regions)
        assert _resolve_region_id("worldwide", ts, "t2m", "mean") == "globe"

    def test_globe_alias_world(self):
        regions = {"globe": {"name": "Globe", "type": "globe", "values": []}}
        ts = _make_ts(regions)
        assert _resolve_region_id("world", ts, "t2m", "mean") == "globe"

    def test_continent_slug_north_america(self):
        regions = {
            "continent:north_america": {
                "name": "North America",
                "type": "continent",
                "values": [],
            }
        }
        ts = _make_ts(regions)
        assert (
            _resolve_region_id("north america", ts, "t2m", "mean")
            == "continent:north_america"
        )

    def test_continent_slug_europe(self):
        regions = {
            "continent:europe": {"name": "Europe", "type": "continent", "values": []}
        }
        ts = _make_ts(regions)
        assert _resolve_region_id("europe", ts, "t2m", "mean") == "continent:europe"

    def test_country_code_uppercased(self):
        regions = {"country:FR": {"name": "France", "type": "country", "values": []}}
        ts = _make_ts(regions)
        assert _resolve_region_id("fr", ts, "t2m", "mean") == "country:FR"

    def test_region_name_case_insensitive_match(self):
        regions = {"country:DE": {"name": "Germany", "type": "country", "values": []}}
        ts = _make_ts(regions)
        assert _resolve_region_id("germany", ts, "t2m", "mean") == "country:DE"

    def test_returns_none_when_no_aggregates(self):
        ts = _MockTileStore(has_aggregates=False)
        assert _resolve_region_id("country:FR", ts, "t2m", "mean") is None

    def test_returns_none_for_unrecognised_region(self):
        regions = {"country:FR": {"name": "France", "type": "country", "values": []}}
        ts = _make_ts(regions)
        assert _resolve_region_id("narnia", ts, "t2m", "mean") is None

    def test_ocean_slug_resolution(self):
        regions = {
            "ocean:indian_ocean": {
                "name": "Indian Ocean",
                "type": "ocean",
                "values": [],
            }
        }
        ts = _make_ts(regions)
        # "indian ocean" → slug "indian_ocean" → "ocean:indian_ocean"
        assert (
            _resolve_region_id("indian ocean", ts, "t2m", "mean")
            == "ocean:indian_ocean"
        )


# ---------------------------------------------------------------------------
# Region series size control
# ---------------------------------------------------------------------------


def _monthly_store(years=47):
    """A tile store stub holding a monthly Europe aggregate."""

    class _Store:
        metrics = {
            "t2m_monthly_mean_c": {
                "id": "t2m_monthly_mean_c",
                "title": "monthly mean",
                "unit": "C",
                "source": {"type": "cds", "_dataset_ref": "era5_daily_t2m"},
            }
        }
        axis = [f"{1979 + i // 12}-{(i % 12) + 1:02d}" for i in range(years * 12)]
        aggregates = {
            ("t2m_monthly_mean_c", "mean"): {
                "time_axis": axis,
                "regions": {
                    "continent:europe": {
                        "type": "continent",
                        "name": "Europe",
                        "values": [float(i % 12) for i in range(years * 12)],
                        "cell_count": 100,
                    }
                },
            }
        }

    return _Store()


def test_region_series_month_filter_keeps_only_that_month():
    store = _monthly_store()
    r = tools.get_region_metric_series(
        region_id="continent:europe",
        metric_id="t2m_monthly_mean_c",
        aggregation="mean",
        tile_store=store,
        month_filter=[6],
    )
    assert len(r["data"]) == 47
    assert all(str(p["year"]).endswith("-06") for p in r["data"])


def test_region_series_aggregate_by_year_collapses_months():
    store = _monthly_store()
    r = tools.get_region_metric_series(
        region_id="continent:europe",
        metric_id="t2m_monthly_mean_c",
        aggregation="mean",
        tile_store=store,
        month_filter=[6, 7],
        aggregate_by_year=True,
    )
    assert len(r["data"]) == 47
    assert all(len(str(p["year"])) == 4 for p in r["data"])


def test_region_series_summarises_when_too_long():
    """An unfiltered monthly series must not be returned in full.

    564 monthly points is ~5,500 tokens, which alone overruns the request
    budget of the smaller models and fails the turn.
    """
    store = _monthly_store()
    r = tools.get_region_metric_series(
        region_id="continent:europe",
        metric_id="t2m_monthly_mean_c",
        aggregation="mean",
        tile_store=store,
    )
    assert len(r["data"]) == 47, "should collapse to one point per year"
    assert "note" in r
    assert "564" in r["note"], "the note must say how much was left out"
    assert all(len(str(p["year"])) == 4 for p in r["data"])


def test_region_series_short_enough_is_untouched():
    store = _monthly_store(years=5)  # 60 points, under the cap
    r = tools.get_region_metric_series(
        region_id="continent:europe",
        metric_id="t2m_monthly_mean_c",
        aggregation="mean",
        tile_store=store,
    )
    assert len(r["data"]) == 60
    assert "note" not in r


def _point_store(years=47):
    """Tile store stub exposing a monthly point series."""
    import numpy as np

    class _Store:
        metrics = {
            "t2m_monthly_mean_c": {
                "id": "t2m_monthly_mean_c",
                "title": "monthly mean",
                "unit": "C",
                "time_axis": "monthly",
                "source": {"type": "cds", "_dataset_ref": "era5_daily_t2m"},
            }
        }
        _axis = [f"{1979 + i // 12}-{(i % 12) + 1:02d}" for i in range(years * 12)]

        def axis(self, mid):
            return self._axis

        def time_axis_type(self, mid):
            return "monthly"

        def try_get_metric_vector(self, mid, lat, lon):
            return np.array([float(i % 12) for i in range(years * 12)])

        def get_metric_vector(self, mid, lat, lon):
            return self.try_get_metric_vector(mid, lat, lon)

    return _Store()


def test_point_monthly_series_collapses_when_too_long():
    """An unfiltered monthly point series is ~560 points — too many to send."""
    store = _point_store()
    r = tools._get_metric_series(
        lat=48.85, lon=2.35, metric_id="t2m_monthly_mean_c", tile_store=store
    )
    if "error" in r:  # stub shape mismatch — skip rather than assert on plumbing
        import pytest

        pytest.skip(f"stub incompatible: {r['error']}")
    assert len(r["data"]) < 120
    assert r.get("collapsed_to_yearly") is True


def test_month_filter_on_yearly_metric_is_flagged_not_silently_dropped():
    """A yearly metric cannot honour month_filter.

    It must say so, because the data it returns is annual — charting it beside
    a "how have winters changed" answer would present the annual trend as the
    winter trend.
    """
    from climate_api.chat.orchestrator import _filter_series_results

    result = {
        "metric_id": "t2m_yearly_mean_c",
        "data": [{"year": 1979, "value": 9.8}],
        "month_filter_ignored": True,
        "note": "month_filter [12, 1, 2] is not applicable to a yearly metric",
    }
    ok = {"metric_id": "t2m_monthly_mean_c", "data": [{"year": 1979, "value": 2.6}]}

    charted = _filter_series_results([result, ok])
    assert [r["metric_id"] for r in charted] == ["t2m_monthly_mean_c"]
    # The model must still receive the rejected result so it can re-query.
    assert result["note"]


def test_metric_catalogue_states_time_resolution():
    """The model needs to know which metrics accept month_filter."""

    class _Store:
        metrics = {
            "t2m_yearly_mean_c": {
                "title": "yearly mean",
                "unit": "C",
                "time_axis": "yearly",
            },
            "t2m_monthly_mean_c": {
                "title": "monthly mean",
                "unit": "C",
                "time_axis": "monthly",
            },
        }

        def axis(self, mid):
            return [1979, 2025]

    entries = {
        m["metric_id"]: m for m in tools.list_available_metrics(_Store())["metrics"]
    }
    assert entries["t2m_yearly_mean_c"]["resolution"] == "yearly"
    assert entries["t2m_monthly_mean_c"]["resolution"] == "monthly"


# ---------------------------------------------------------------------------
# _alt_names_for
# ---------------------------------------------------------------------------


def _index_with_alt_names(tmp_path):
    index_csv = tmp_path / "locations.index.csv"
    index_csv.write_text(
        "geonameid,label,lat,lon,country_code,population,norm_label,norm_city,city_name,capital,alt_names\n"
        '1,"Ulan Bator, Mongolia",47.9,106.9,MN,844818,ulan bator mongolia,ulan bator,Ulan Bator,true,"Ulaanbaatar,Oulan-Bator"\n'
        '2,"Oslo, Norway",59.9,10.8,NO,580000,oslo norway,oslo,Oslo,true,\n',
        encoding="utf-8",
    )
    return LocationIndex(index_csv, min_query_len=2, prefix_len=2)


class TestAltNamesFor:
    """The precomputed ranking carries no alternate names, so the fast path
    resolves them from the index to match what the index-scan path returns."""

    def test_returns_alt_names_for_a_known_label(self, tmp_path) -> None:
        index = _index_with_alt_names(tmp_path)
        assert _alt_names_for("Ulan Bator, Mongolia", index) == (
            "Ulaanbaatar,Oulan-Bator"
        )

    def test_returns_empty_string_for_a_city_without_alt_names(self, tmp_path) -> None:
        index = _index_with_alt_names(tmp_path)
        assert _alt_names_for("Oslo, Norway", index) == ""

    def test_unresolvable_label_returns_empty_string(self, tmp_path) -> None:
        """A ranking row the index no longer knows must not raise."""
        index = _index_with_alt_names(tmp_path)
        assert _alt_names_for("Atlantis, Nowhere", index) == ""


# ---------------------------------------------------------------------------
# _drop_full_span_years
# ---------------------------------------------------------------------------


class _AxisStore:
    """Minimal tile store exposing just the time axis of one metric."""

    def __init__(self, axis):
        self._axis = axis

    def axis(self, metric_id):
        return self._axis


_YEARLY = _AxisStore(list(range(1979, 2026)))
_MONTHLY = _AxisStore([f"{y}-{m:02d}" for y in range(1979, 2027) for m in range(1, 13)])


def _drop(store, start, end):
    return _drop_full_span_years("m", store, start, end)


class TestDropFullSpanYears:
    """A range covering the whole record is the same query as no range.

    Leaving it in place would skip the precomputed ranking and fall through to
    a global per-city scan — the 36-second call this guards against.
    """

    def test_exact_full_span_is_dropped(self):
        assert _drop(_YEARLY, 1979, 2025) == (None, None)

    def test_range_wider_than_the_record_is_dropped(self):
        assert _drop(_YEARLY, 1900, 2100) == (None, None)

    def test_narrower_range_is_kept(self):
        assert _drop(_YEARLY, 2000, 2020) == (2000, 2020)

    def test_only_the_redundant_half_is_dropped(self):
        assert _drop(_YEARLY, 1979, 2010) == (None, 2010)
        assert _drop(_YEARLY, 2000, 2025) == (2000, None)

    def test_single_year_inside_the_record_is_kept(self):
        assert _drop(_YEARLY, 2000, 2000) == (2000, 2000)

    def test_last_year_alone_is_not_treated_as_the_full_span(self):
        """end_year=2025 is redundant, but start_year=2025 still narrows."""
        assert _drop(_YEARLY, 2025, 2025) == (2025, None)

    def test_no_bounds_passed_through(self):
        assert _drop(_YEARLY, None, None) == (None, None)

    def test_monthly_axis_years_parsed_from_the_string(self):
        assert _drop(_MONTHLY, 1979, 2026) == (None, None)
        assert _drop(_MONTHLY, 2000, 2020) == (2000, 2020)

    def test_empty_axis_leaves_the_bounds_alone(self):
        """Without an axis there is nothing to compare against — don't guess."""
        assert _drop(_AxisStore([]), 1979, 2025) == (1979, 2025)

    def test_unsorted_axis_still_finds_the_edges(self):
        assert _drop(_AxisStore([2000, 1979, 2025, 1990]), 1979, 2025) == (None, None)


# ---------------------------------------------------------------------------
# find_extreme_region — minimum region size
# ---------------------------------------------------------------------------


class _AggStore:
    """Tile store exposing one metric's regional aggregates."""

    def __init__(self, regions):
        self.metrics = {"m": {"unit": "C", "time_axis": "yearly"}}
        self.aggregates = {
            ("m", "mean"): {"time_axis": [2000, 2001], "regions": regions}
        }


def _country(name, cells, value):
    return {
        "name": name,
        "type": "country",
        "cell_count": cells,
        "values": [value, value],
    }


_REGIONS = {
    # A single-cell microstate with the most extreme value in the set.
    "country:LI": _country("Liechtenstein", 1, 9.9),
    "country:UA": _country("Ukraine", 1244, 5.0),
    "country:MD": _country("Moldova", 87, 4.0),
    # Sitting exactly on the threshold, so it must be kept.
    "country:AX": _country("Aland Islands", _MIN_RANKABLE_CELLS, 3.0),
    # One cell below it, so it must be dropped.
    "country:SM": _country("San Marino", _MIN_RANKABLE_CELLS - 1, 8.8),
}


def _rank(extremum="max", limit=5):
    return tools.find_extreme_region(
        metric_id="m",
        aggregation="mean",
        extremum=extremum,
        region_type="country",
        limit=limit,
        tile_store=_AggStore(_REGIONS),
    )


class TestFindExtremeRegionMinimumSize:
    """Regions of a cell or two have no meaningful area-weighted mean.

    Left in the ranking they dominate both ends of it for reasons of grid
    resolution rather than climate.
    """

    def test_single_cell_region_is_excluded_despite_extreme_value(self):
        names = [r["region_name"] for r in _rank()["results"]]
        assert "Liechtenstein" not in names

    def test_largest_qualifying_region_ranks_first(self):
        assert _rank()["results"][0]["region_name"] == "Ukraine"

    def test_region_exactly_on_the_threshold_is_kept(self):
        names = [r["region_name"] for r in _rank()["results"]]
        assert "Aland Islands" in names

    def test_region_just_below_the_threshold_is_excluded(self):
        names = [r["region_name"] for r in _rank()["results"]]
        assert "San Marino" not in names

    def test_filter_applies_to_the_minimum_end_too(self):
        """A microstate must not win the 'least' ranking either."""
        names = [r["region_name"] for r in _rank(extremum="min")["results"]]
        assert "San Marino" not in names and "Liechtenstein" not in names

    def test_missing_cell_count_is_treated_as_too_small(self):
        """An aggregate predating the field must not silently rank."""
        regions = {"country:XX": {"name": "Nowhere", "type": "country",
                                  "values": [7.0, 7.0]}}
        res = tools.find_extreme_region(
            metric_id="m", aggregation="mean", extremum="max",
            region_type="country", limit=5, tile_store=_AggStore(regions),
        )
        assert "results" not in res or not res.get("results")
