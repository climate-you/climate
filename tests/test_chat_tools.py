"""Tests for the pure helper functions in climate_api/chat/tools.py."""

from __future__ import annotations

import pytest

from climate_api.chat.tools import (
    _convert_temp,
    _is_delta_metric,
    _output_unit,
    _resolve_region_id,
)


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
        regions = {"continent:north_america": {"name": "North America", "type": "continent", "values": []}}
        ts = _make_ts(regions)
        assert _resolve_region_id("north america", ts, "t2m", "mean") == "continent:north_america"

    def test_continent_slug_europe(self):
        regions = {"continent:europe": {"name": "Europe", "type": "continent", "values": []}}
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
        regions = {"ocean:indian_ocean": {"name": "Indian Ocean", "type": "ocean", "values": []}}
        ts = _make_ts(regions)
        # "indian ocean" → slug "indian_ocean" → "ocean:indian_ocean"
        assert _resolve_region_id("indian ocean", ts, "t2m", "mean") == "ocean:indian_ocean"
