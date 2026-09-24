from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from climate_api.chat.orchestrator import (
    _CHARS_PER_TOKEN,
    _COMPLETION_RESERVE_TOKENS,
    _CONVERSATION_TOO_LONG_MSG,
    ChatOrchestrator,
    ProviderTier,
    _build_chart_payloads,
    _compress_series_for_context,
    _compute_fly_to_bbox,
    _extract_locations,
    _filter_series_results,
    _is_context_too_large,
    _is_quota_exhausted,
    _is_tpm_error,
    _parse_retry_after_s,
    _estimate_request_tokens,
    _parse_text_tool_calls,
    _strip_internal_fields,
    _supplement_locations_from_answer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _year_series(metric_id, location, start=2000, end=2024, unit="°C", **extra):
    data = [{"year": y, "value": float(y - 1990)} for y in range(start, end + 1)]
    return {
        "metric_id": metric_id,
        "location": location,
        "unit": unit,
        "data": data,
        "lat": 48.8,
        "lon": 2.3,
        **extra,
    }


def _monthly_series(metric_id, location, n_years=6, unit="°C"):
    data = [
        {"year": 2000 + (i // 12), "month": (i % 12) + 1, "value": float(i)}
        for i in range(n_years * 12)
    ]
    return {
        "metric_id": metric_id,
        "location": location,
        "unit": unit,
        "data": data,
        "lat": 48.8,
        "lon": 2.3,
    }


class _MockTileStore:
    def __init__(self, metrics=None):
        self.metrics = metrics or {}

    def axis(self, metric_id):
        return []


def _make_location_index(hits: dict):
    """hits maps name → (label, lat, lon, alt_names)."""

    class _Index:
        def resolve_by_any_name(self, name):
            hit = hits.get(name)
            if hit is None:
                return None
            label, lat, lon, alt_names = hit
            return SimpleNamespace(label=label, lat=lat, lon=lon, alt_names=alt_names)

    return _Index()


# ---------------------------------------------------------------------------
# _compress_series_for_context
# ---------------------------------------------------------------------------


class TestCompressSeriesForContext:
    def test_invalid_json_returned_unchanged(self):
        bad = "not json {"
        assert _compress_series_for_context(bad) == bad

    def test_missing_data_key_returned_unchanged(self):
        d = json.dumps({"metric_id": "t2m", "unit": "°C"})
        assert _compress_series_for_context(d) == d

    def test_short_yearly_series_unchanged(self):
        data = [{"year": 2000 + i, "value": float(i)} for i in range(25)]
        raw = json.dumps({"metric_id": "t2m", "data": data})
        assert _compress_series_for_context(raw) == raw

    def test_long_monthly_series_compressed_to_summary(self):
        # 72 monthly entries → exceeds the 60-entry threshold and has "month" keys
        data = [
            {"year": 2000 + (i // 12), "month": (i % 12) + 1, "value": float(i)}
            for i in range(72)
        ]
        raw = json.dumps({"metric_id": "t2m", "unit": "°C", "data": data})
        result = json.loads(_compress_series_for_context(raw))
        assert "data" not in result
        assert "summary" in result
        s = result["summary"]
        assert "period" in s
        assert "monthly_climatology" in s
        assert len(s["monthly_climatology"]) == 12
        assert "overall_mean" in s
        assert "record_low" in s
        assert "record_high" in s

    def test_long_yearly_series_without_month_key_unchanged(self):
        # 61 entries but no "month" field — not a monthly series
        data = [{"year": 1950 + i, "value": float(i)} for i in range(61)]
        raw = json.dumps({"metric_id": "t2m", "data": data})
        assert _compress_series_for_context(raw) == raw

    def test_non_data_fields_preserved_in_summary(self):
        data = [
            {"year": 2000 + (i // 12), "month": (i % 12) + 1, "value": float(i)}
            for i in range(72)
        ]
        raw = json.dumps(
            {"metric_id": "prcp", "unit": "mm", "location": "Paris", "data": data}
        )
        result = json.loads(_compress_series_for_context(raw))
        assert result["metric_id"] == "prcp"
        assert result["unit"] == "mm"
        assert result["location"] == "Paris"

    def test_none_values_skipped_without_crashing(self):
        data = [
            {
                "year": 2000 + (i // 12),
                "month": (i % 12) + 1,
                "value": None if i % 5 == 0 else float(i),
            }
            for i in range(72)
        ]
        raw = json.dumps({"metric_id": "t2m", "data": data})
        result = json.loads(_compress_series_for_context(raw))
        assert "summary" in result

    def test_summary_period_matches_data_range(self):
        data = [
            {"year": 2000 + (i // 12), "month": (i % 12) + 1, "value": float(i)}
            for i in range(72)
        ]
        raw = json.dumps({"metric_id": "t2m", "data": data})
        result = json.loads(_compress_series_for_context(raw))
        assert result["summary"]["period"] == "2000-2005"


# ---------------------------------------------------------------------------
# _strip_internal_fields
# ---------------------------------------------------------------------------


class TestStripInternalFields:
    def test_removes_alt_names_from_top_level(self):
        d = json.dumps({"lat": 48.8, "lon": 2.3, "alt_names": "Paris,Lutetia"})
        result = json.loads(_strip_internal_fields(d))
        assert "alt_names" not in result
        assert result["lat"] == 48.8

    def test_removes_alt_names_from_each_result_in_list(self):
        d = json.dumps(
            {
                "results": [
                    {"nearest_city": "Paris", "alt_names": "Lutetia"},
                    {"nearest_city": "Berlin", "alt_names": ""},
                ]
            }
        )
        result = json.loads(_strip_internal_fields(d))
        for r in result["results"]:
            assert "alt_names" not in r

    def test_dict_without_internal_fields_unchanged(self):
        d = json.dumps({"metric_id": "t2m", "value": 15.0})
        assert _strip_internal_fields(d) == d

    def test_invalid_json_returned_unchanged(self):
        bad = "not json"
        assert _strip_internal_fields(bad) == bad

    def test_non_dict_json_returned_unchanged(self):
        d = json.dumps([1, 2, 3])
        assert _strip_internal_fields(d) == d


# ---------------------------------------------------------------------------
# _extract_locations
# ---------------------------------------------------------------------------


class TestExtractLocations:
    def test_get_metric_series_extracts_lat_lon(self):
        result = {"lat": 48.8, "lon": 2.3, "data": []}
        locs = _extract_locations("get_metric_series", {"location": "Paris"}, result)
        assert locs == [{"label": "Paris", "lat": 48.8, "lon": 2.3}]

    def test_get_metric_series_with_error_returns_empty(self):
        assert (
            _extract_locations(
                "get_metric_series", {"location": "Paris"}, {"error": "not found"}
            )
            == []
        )

    def test_find_extreme_location_single_result(self):
        result = {
            "lat": 51.5,
            "lon": -0.1,
            "nearest_city": "London",
            "alt_names": "Londen",
        }
        locs = _extract_locations("find_extreme_location", {}, result)
        assert len(locs) == 1
        assert locs[0]["label"] == "London"
        assert locs[0]["lat"] == 51.5
        assert locs[0]["alt_names"] == "Londen"

    def test_find_extreme_location_results_list(self):
        result = {
            "results": [
                {"lat": 51.5, "lon": -0.1, "nearest_city": "London", "alt_names": ""},
                {"lat": 48.8, "lon": 2.3, "nearest_city": "Paris", "alt_names": ""},
            ]
        }
        locs = _extract_locations("find_extreme_location", {}, result)
        assert len(locs) == 2
        assert locs[0]["label"] == "London"
        assert locs[1]["label"] == "Paris"

    def test_find_extreme_location_results_without_lat_skipped(self):
        result = {
            "results": [
                {"nearest_city": "Unknown"},  # no lat/lon
                {"lat": 48.8, "lon": 2.3, "nearest_city": "Paris", "alt_names": ""},
            ]
        }
        locs = _extract_locations("find_extreme_location", {}, result)
        assert len(locs) == 1
        assert locs[0]["label"] == "Paris"

    def test_find_similar_locations_extracts_reference(self):
        result = {"reference": "Tokyo", "reference_lat": 35.7, "reference_lon": 139.7}
        locs = _extract_locations("find_similar_locations", {}, result)
        assert locs == [{"label": "Tokyo", "lat": 35.7, "lon": 139.7}]

    def test_unknown_tool_returns_empty(self):
        assert _extract_locations("unknown_tool", {}, {"lat": 0, "lon": 0}) == []

    def test_find_extreme_location_with_error_returns_empty(self):
        assert (
            _extract_locations("find_extreme_location", {}, {"error": "no data"}) == []
        )


# ---------------------------------------------------------------------------
# _filter_series_results
# ---------------------------------------------------------------------------


class TestFilterSeriesResults:
    def test_no_explicit_results_returns_all_unchanged(self):
        series = [
            {"metric_id": "t2m", "location": "Paris", "_source": "auto"},
            {"metric_id": "prcp", "location": "Paris", "_source": "auto"},
        ]
        assert _filter_series_results(series) == series

    def test_auto_dropped_when_explicit_exists_for_same_metric(self):
        series = [
            {"metric_id": "t2m", "location": "Paris", "_source": "explicit"},
            {"metric_id": "t2m", "location": "Berlin", "_source": "auto"},
        ]
        result = _filter_series_results(series)
        assert len(result) == 1
        assert result[0]["_source"] == "explicit"
        assert result[0]["location"] == "Paris"

    def test_auto_for_other_metric_retained(self):
        series = [
            {"metric_id": "t2m", "location": "Paris", "_source": "explicit"},
            {"metric_id": "prcp", "location": "Paris", "_source": "auto"},
        ]
        result = _filter_series_results(series)
        assert len(result) == 2

    def test_all_auto_dropped_when_both_metrics_have_explicit(self):
        series = [
            {"metric_id": "t2m", "location": "London", "_source": "explicit"},
            {"metric_id": "t2m", "location": "Tokyo", "_source": "auto"},
            {"metric_id": "prcp", "location": "London", "_source": "explicit"},
            {"metric_id": "prcp", "location": "Sydney", "_source": "auto"},
        ]
        result = _filter_series_results(series)
        assert all(r["_source"] == "explicit" for r in result)
        assert len(result) == 2

    def test_empty_input_returns_empty(self):
        assert _filter_series_results([]) == []


# ---------------------------------------------------------------------------
# _supplement_locations_from_answer
# ---------------------------------------------------------------------------


class TestSupplementLocationsFromAnswer:
    def test_bold_city_appended_when_not_in_locations(self):
        idx = _make_location_index({"Berlin": ("Berlin, Germany", 52.5, 13.4, "")})
        locs = _supplement_locations_from_answer("**Berlin** is a great city.", [], idx)
        assert len(locs) == 1
        assert locs[0]["label"] == "Berlin, Germany"

    def test_city_already_in_locations_not_duplicated(self):
        existing = [{"label": "Berlin, Germany", "lat": 52.5, "lon": 13.4}]
        idx = _make_location_index({"Berlin": ("Berlin, Germany", 52.5, 13.4, "")})
        locs = _supplement_locations_from_answer("**Berlin** is great.", existing, idx)
        assert len(locs) == 1

    def test_city_covered_by_alt_name_not_duplicated(self):
        existing = [
            {
                "label": "Köln, Germany",
                "lat": 50.9,
                "lon": 6.96,
                "alt_names": "Cologne,Koeln",
            }
        ]
        idx = _make_location_index({"Cologne": ("Cologne, Germany", 50.9, 6.96, "")})
        locs = _supplement_locations_from_answer("**Cologne** is warm.", existing, idx)
        assert len(locs) == 1  # not appended, already covered by alt_name

    def test_unknown_city_not_appended(self):
        idx = _make_location_index({})
        locs = _supplement_locations_from_answer("**Atlantis** is mythical.", [], idx)
        assert locs == []

    def test_lowercase_first_char_bold_word_skipped(self):
        idx = _make_location_index({"warming": ("warming", 0.0, 0.0, "")})
        locs = _supplement_locations_from_answer(
            "The **warming** trend continues.", [], idx
        )
        assert locs == []

    def test_multi_word_city_resolved(self):
        # The bold regex excludes commas, so only the bare city name appears between **
        idx = _make_location_index({"New York": ("New York, US", 40.7, -74.0, "")})
        locs = _supplement_locations_from_answer(
            "**New York** recorded record highs.", [], idx
        )
        assert len(locs) == 1
        assert locs[0]["lat"] == 40.7

    def test_duplicate_rounded_coords_not_added_twice(self):
        # Two distinct names that resolve to the same approximate location
        idx = _make_location_index(
            {
                "Berlin": ("Berlin, Germany", 52.51, 13.41, ""),
                "Berlino": ("Berlino", 52.52, 13.42, ""),  # rounds to same (52.5, 13.4)
            }
        )
        locs = _supplement_locations_from_answer(
            "**Berlin** and **Berlino** are similar.", [], idx
        )
        assert len(locs) == 1

    def test_original_locations_always_prepended(self):
        existing = [{"label": "Paris, France", "lat": 48.8, "lon": 2.3}]
        idx = _make_location_index({"Tokyo": ("Tokyo, Japan", 35.7, 139.7, "")})
        locs = _supplement_locations_from_answer("**Tokyo** is hot.", existing, idx)
        assert locs[0]["label"] == "Paris, France"
        assert locs[1]["label"] == "Tokyo, Japan"


# ---------------------------------------------------------------------------
# _build_chart_payloads
# ---------------------------------------------------------------------------


class TestBuildChartPayloads:
    def test_empty_series_returns_empty(self):
        assert _build_chart_payloads([], _MockTileStore()) == []

    def test_single_yearly_series_produces_one_chart(self):
        series = [_year_series("t2m", "Paris", start=2020, end=2024)]
        ts = _MockTileStore({"t2m": {"title": "Temperature", "unit": "°C"}})
        charts = _build_chart_payloads(series, ts)
        assert len(charts) == 1
        assert charts[0]["title"] == "Temperature — Paris"
        assert charts[0]["unit"] == "°C"
        assert len(charts[0]["series"]) == 1
        assert charts[0]["series"][0]["label"] == "Paris"

    def test_two_locations_same_metric_one_chart_two_series(self):
        series = [
            _year_series("t2m", "Paris", start=2020, end=2024),
            _year_series("t2m", "Berlin", start=2020, end=2024),
        ]
        ts = _MockTileStore({"t2m": {"title": "Temperature", "unit": "°C"}})
        charts = _build_chart_payloads(series, ts)
        assert len(charts) == 1
        labels = {s["label"] for s in charts[0]["series"]}
        assert labels == {"Paris", "Berlin"}

    def test_two_different_metrics_two_charts(self):
        series = [
            _year_series("t2m", "Paris", start=2020, end=2024),
            _year_series("prcp", "Paris", start=2020, end=2024, unit="mm"),
        ]
        ts = _MockTileStore(
            {
                "t2m": {"title": "Temperature", "unit": "°C"},
                "prcp": {"title": "Precipitation", "unit": "mm"},
            }
        )
        charts = _build_chart_payloads(series, ts)
        assert len(charts) == 2

    def test_trend_role_preserved_in_output_series(self):
        raw = _year_series("t2m", "Tokyo", start=2020, end=2024)
        trend = {
            "metric_id": "t2m",
            "location": "Tokyo",
            "unit": "°C",
            "role": "trend",
            "data": [{"year": y, "value": float(y)} for y in range(2020, 2025)],
            "lat": 35.7,
            "lon": 139.7,
        }
        ts = _MockTileStore({"t2m": {"title": "Temperature", "unit": "°C"}})
        charts = _build_chart_payloads([raw, trend], ts)
        assert len(charts) == 1
        roles = {s.get("role") for s in charts[0]["series"]}
        assert "trend" in roles

    def test_single_scalar_region_result_suppressed(self):
        series = [
            {
                "metric_id": "t2m",
                "region_id": "country:FR",
                "aggregation": "mean",
                "unit": "°C",
                "location": "France",
                "data": [{"year": 2020, "value": 12.0}],
            }
        ]
        ts = _MockTileStore({"t2m": {"title": "Temperature", "unit": "°C"}})
        assert _build_chart_payloads(series, ts) == []

    def test_scalar_comparison_two_regions_produces_comparison_bar(self):
        series = [
            {
                "metric_id": "t2m",
                "region_id": "country:FR",
                "aggregation": "mean",
                "unit": "°C",
                "location": "France",
                "data": [{"year": 2020, "value": 12.0}],
            },
            {
                "metric_id": "t2m",
                "region_id": "country:DE",
                "aggregation": "mean",
                "unit": "°C",
                "location": "Germany",
                "data": [{"year": 2020, "value": 10.0}],
            },
        ]
        ts = _MockTileStore({"t2m": {"title": "Temperature", "unit": "°C"}})
        charts = _build_chart_payloads(series, ts)
        assert len(charts) == 1
        assert charts[0].get("chart_mode") == "comparison_bar"

    def test_multi_agg_same_region_gets_bauhaus_colors(self):
        def _region_series(agg, offset):
            return {
                "metric_id": "t2m",
                "region_id": "globe",
                "aggregation": agg,
                "unit": "°C",
                "location": "Globe",
                "data": [
                    {"year": y, "value": float(y) + offset} for y in range(2000, 2025)
                ],
            }

        series = [
            _region_series("min", 0),
            _region_series("mean", 5),
            _region_series("max", 10),
        ]
        ts = _MockTileStore({"t2m": {"title": "Temperature", "unit": "°C"}})
        charts = _build_chart_payloads(series, ts)
        assert len(charts) == 1
        colors = {
            s["label"]: s.get("style", {}).get("color") for s in charts[0]["series"]
        }
        assert colors.get("Min") == "#0000FF"
        assert colors.get("Mean") == "#000000"
        assert colors.get("Max") == "#FF0000"

    def test_chart_group_two_metrics_merged_into_one_chart(self):
        cg1 = {
            "id": "dhw",
            "order": 1,
            "label": "DHW 4+",
            "chart_mode": "stacked_bar",
            "chart_title": "DHW Risk Days",
            "style": {},
        }
        cg2 = {
            "id": "dhw",
            "order": 2,
            "label": "DHW 8+",
            "chart_mode": "stacked_bar",
            "chart_title": "DHW Risk Days",
            "style": {},
        }
        metrics = {
            "dhw_4": {"title": "DHW 4+", "unit": "days", "chart_group": cg1},
            "dhw_8": {"title": "DHW 8+", "unit": "days", "chart_group": cg2},
        }
        series = [
            {
                "metric_id": "dhw_4",
                "location": "Reef",
                "unit": "days",
                "data": [
                    {"year": y, "value": float(y - 2000)} for y in range(2000, 2010)
                ],
                "lat": -18.0,
                "lon": 147.0,
            },
            {
                "metric_id": "dhw_8",
                "location": "Reef",
                "unit": "days",
                "data": [
                    {"year": y, "value": float(y - 2003)} for y in range(2000, 2010)
                ],
                "lat": -18.0,
                "lon": 147.0,
            },
        ]
        charts = _build_chart_payloads(series, _MockTileStore(metrics))
        assert len(charts) == 1
        assert charts[0].get("chart_mode") == "stacked_bar"
        assert len(charts[0]["series"]) == 2

    def test_auto_series_dropped_when_explicit_present_for_same_metric(self):
        explicit = {**_year_series("t2m", "Paris"), "_source": "explicit"}
        auto = {**_year_series("t2m", "Tokyo"), "_source": "auto"}
        ts = _MockTileStore({"t2m": {"title": "Temperature", "unit": "°C"}})
        charts = _build_chart_payloads([explicit, auto], ts)
        assert len(charts) == 1
        assert len(charts[0]["series"]) == 1
        assert charts[0]["series"][0]["label"] == "Paris"

    def test_x_axis_uses_year_integers_for_yearly_data(self):
        series = [_year_series("t2m", "Paris", start=2020, end=2022)]
        ts = _MockTileStore({"t2m": {"title": "Temperature", "unit": "°C"}})
        charts = _build_chart_payloads(series, ts)
        x = charts[0]["series"][0]["x"]
        assert x == [2020, 2021, 2022]

    def test_x_axis_uses_year_month_strings_for_monthly_data(self):
        series = [_monthly_series("t2m", "Paris", n_years=1)]
        ts = _MockTileStore({"t2m": {"title": "Temperature", "unit": "°C"}})
        charts = _build_chart_payloads(series, ts)
        x = charts[0]["series"][0]["x"]
        assert x[0] == "2000-01"
        assert x[11] == "2000-12"

    def test_title_uses_multiple_cities_label_when_more_than_two(self):
        series = [
            _year_series("t2m", "Paris", start=2020, end=2024),
            _year_series("t2m", "Berlin", start=2020, end=2024),
            _year_series("t2m", "Tokyo", start=2020, end=2024),
        ]
        ts = _MockTileStore({"t2m": {"title": "Temperature", "unit": "°C"}})
        charts = _build_chart_payloads(series, ts)
        assert "Multiple cities" in charts[0]["title"]


# ---------------------------------------------------------------------------
# _compute_fly_to_bbox
# ---------------------------------------------------------------------------


class TestComputeFlyToBbox:
    def test_single_continent_returns_bbox(self):
        bbox = _compute_fly_to_bbox([{"region_id": "continent:europe"}])
        assert bbox is not None
        assert len(bbox) == 4
        assert bbox[0] == -25.0  # west bound of Europe

    def test_multiple_continents_returns_none(self):
        series = [{"region_id": "continent:europe"}, {"region_id": "continent:asia"}]
        assert _compute_fly_to_bbox(series) is None

    def test_no_continent_regions_returns_none(self):
        assert _compute_fly_to_bbox([{"region_id": "country:FR"}]) is None

    def test_empty_series_returns_none(self):
        assert _compute_fly_to_bbox([]) is None

    def test_continent_mixed_with_country_still_one_continent(self):
        # Only one unique continent ID → should return bbox
        series = [{"region_id": "continent:africa"}, {"region_id": "country:ZA"}]
        bbox = _compute_fly_to_bbox(series)
        assert bbox is not None

    def test_all_known_continents_have_bbox(self):
        for continent in [
            "africa",
            "antarctica",
            "asia",
            "europe",
            "north_america",
            "oceania",
            "south_america",
        ]:
            bbox = _compute_fly_to_bbox([{"region_id": f"continent:{continent}"}])
            assert bbox is not None, f"Missing bbox for {continent}"


# ---------------------------------------------------------------------------
# _is_quota_exhausted
# ---------------------------------------------------------------------------


class TestIsQuotaExhausted:
    def test_false_for_generic_exception(self):
        assert not _is_quota_exhausted(ValueError("something went wrong"))

    def test_true_for_429_with_tokens_per_day_in_body(self):
        exc = Exception("rate limit")
        exc.status_code = 429
        exc.body = {"error": {"message": "you have exceeded your tokens per day limit"}}
        assert _is_quota_exhausted(exc)

    def test_true_for_429_with_tpd_abbreviation_in_body(self):
        exc = Exception("rate limit")
        exc.status_code = 429
        exc.body = {"error": {"message": "Rate limit 50000 TPD"}}
        assert _is_quota_exhausted(exc)

    def test_false_for_429_with_tokens_per_minute_in_body(self):
        exc = Exception("rate limit")
        exc.status_code = 429
        exc.body = {
            "error": {"message": "you have exceeded your tokens per minute limit"}
        }
        assert not _is_quota_exhausted(exc)

    def test_false_for_non_429_status(self):
        exc = Exception("server error")
        exc.status_code = 500
        exc.body = {}
        assert not _is_quota_exhausted(exc)

    def test_false_when_no_status_code_attr(self):
        assert not _is_quota_exhausted(RuntimeError("unexpected failure"))


# ---------------------------------------------------------------------------
# _is_context_too_large
# ---------------------------------------------------------------------------


class TestIsContextTooLarge:
    def test_true_for_413_status_code(self):
        exc = Exception("too big")
        exc.status_code = 413
        assert _is_context_too_large(exc)

    def test_true_for_request_too_large_message(self):
        assert _is_context_too_large(Exception("Request too large for model"))

    def test_true_for_reduce_message_size_phrase(self):
        assert _is_context_too_large(
            Exception("Please reduce your message size and try again")
        )

    def test_false_for_generic_exception(self):
        assert not _is_context_too_large(Exception("something unrelated"))

    def test_false_for_non_413_status(self):
        exc = Exception("bad gateway")
        exc.status_code = 502
        assert not _is_context_too_large(exc)


# ---------------------------------------------------------------------------
# _is_tpm_error
# ---------------------------------------------------------------------------


class TestIsTpmError:
    def test_true_for_tokens_per_minute_with_retry_phrase(self):
        assert _is_tpm_error(Exception("exceeded tokens per minute. Try again in 30s."))

    def test_true_for_tpm_abbreviation_with_retry_phrase(self):
        assert _is_tpm_error(Exception("100 TPM limit exceeded. Try again in 10s."))

    def test_false_when_retry_phrase_absent(self):
        assert not _is_tpm_error(Exception("tokens per minute exceeded"))

    def test_false_for_request_too_large(self):
        assert not _is_tpm_error(
            Exception(
                "request too large, please reduce your message size. Try again in 1s."
            )
        )

    def test_false_for_tokens_per_day(self):
        assert not _is_tpm_error(
            Exception("tokens per day limit reached. Try again in 30s.")
        )

    def test_false_for_generic_error(self):
        assert not _is_tpm_error(Exception("connection reset by peer"))


# ---------------------------------------------------------------------------
# _parse_retry_after_s
# ---------------------------------------------------------------------------


class TestParseRetryAfterS:
    def test_seconds_only(self):
        assert _parse_retry_after_s(Exception("Try again in 30s")) == 30.0

    def test_minutes_only(self):
        assert _parse_retry_after_s(Exception("Try again in 1m")) == 60.0

    def test_minutes_and_seconds(self):
        assert _parse_retry_after_s(Exception("Try again in 1m 30s")) == 90.0

    def test_fractional_seconds(self):
        assert _parse_retry_after_s(Exception("Try again in 5.5s")) == pytest.approx(
            5.5
        )

    def test_no_match_returns_default(self):
        assert _parse_retry_after_s(Exception("no timing information")) == 5.0

    def test_case_insensitive(self):
        assert _parse_retry_after_s(Exception("TRY AGAIN IN 10S")) == 10.0

    def test_two_minutes_thirty_seconds(self):
        assert _parse_retry_after_s(Exception("Try again in 2m30s")) == 150.0


# ---------------------------------------------------------------------------
# _parse_text_tool_calls
# ---------------------------------------------------------------------------


class TestParseTextToolCalls:
    def test_no_function_tags_returns_empty(self):
        assert _parse_text_tool_calls("No tool calls here.") == []

    def test_single_groq_format_call(self):
        text = '<function=get_metric_series{"location": "Paris", "metric_id": "t2m"}</function>'
        calls = _parse_text_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["name"] == "get_metric_series"
        assert calls[0]["arguments"] == {"location": "Paris", "metric_id": "t2m"}

    def test_multiple_calls_all_parsed(self):
        text = (
            '<function=find_extreme_location{"metric_id": "t2m", "aggregation": "mean", "extremum": "max"}</function>'
            " some text "
            '<function=get_metric_series{"location": "Tokyo", "metric_id": "t2m"}</function>'
        )
        calls = _parse_text_tool_calls(text)
        assert len(calls) == 2
        assert calls[0]["name"] == "find_extreme_location"
        assert calls[1]["name"] == "get_metric_series"

    def test_invalid_json_call_skipped(self):
        text = "<function=bad_tool{invalid json here}</function>"
        assert _parse_text_tool_calls(text) == []

    def test_call_without_brace_skipped(self):
        text = "<function=no_args_here</function>"
        assert _parse_text_tool_calls(text) == []

    def test_each_call_has_unique_id(self):
        text = (
            '<function=get_metric_series{"location": "Paris", "metric_id": "t2m"}</function>'
            '<function=get_metric_series{"location": "Berlin", "metric_id": "t2m"}</function>'
        )
        calls = _parse_text_tool_calls(text)
        assert len(calls) == 2
        assert calls[0]["id"] != calls[1]["id"]

    def test_valid_and_invalid_mixed_only_valid_returned(self):
        text = (
            '<function=good_tool{"key": "value"}</function>'
            "<function=bad_tool{not valid json}</function>"
        )
        calls = _parse_text_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["name"] == "good_tool"


# ---------------------------------------------------------------------------
# _estimate_request_tokens
# ---------------------------------------------------------------------------


class TestEstimateRequestTokens:
    def test_reserves_room_for_the_completion(self):
        """An empty message list still costs the schemas plus the reserve."""
        estimate = _estimate_request_tokens([])
        assert estimate > _COMPLETION_RESERVE_TOKENS

    def test_leaves_headroom_for_the_observed_overhead(self):
        """A request billed at 8,115 must estimate over a free key's 8,000 cap.

        Reconstructed from the recorded session: ~6,880 prompt tokens of
        messages, which Groq reported as 8,115 against its 8,000 ceiling.
        """
        prompt_chars = int(6880 * _CHARS_PER_TOKEN)
        messages = [{"role": "user", "content": "x" * prompt_chars}]
        assert _estimate_request_tokens(messages) > 8000

    def test_does_not_over_count_an_empty_conversation(self):
        """The fixed base is ~4,450 tokens; a fresh question must still fit."""
        assert (
            _estimate_request_tokens([{"role": "user", "content": "Hot or cold"}])
            < 8000
        )

    def test_grows_with_message_size(self):
        small = _estimate_request_tokens([{"role": "user", "content": "hi"}])
        large = _estimate_request_tokens([{"role": "user", "content": "hi" * 5000}])
        assert large > small


# ---------------------------------------------------------------------------
# Tier fallback on an oversized request
# ---------------------------------------------------------------------------


def _chunk(content=None, tool_calls=None):
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(usage=None, choices=[SimpleNamespace(delta=delta)])


def _tool_call_chunk(name, arguments):
    return _chunk(
        tool_calls=[
            SimpleNamespace(
                index=0,
                id="call_1",
                function=SimpleNamespace(name=name, arguments=arguments),
            )
        ]
    )


class _ScriptedClient:
    """Groq-shaped client that replays a scripted response per call."""

    def __init__(self, script):
        self._script = list(script)
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        step = self._script[min(self.calls, len(self._script) - 1)]
        self.calls += 1
        if isinstance(step, Exception):
            raise step
        return iter(step)


def _orchestrator_with(tiers):
    tile_store = SimpleNamespace(metrics={}, rankings={})
    return ChatOrchestrator(
        tiers=tiers,
        tile_store=tile_store,
        location_index=SimpleNamespace(),
        max_steps=3,
    )


def _too_large_error():
    return Exception(
        "Request too large for model `openai/gpt-oss-120b` on tokens per "
        "minute (TPM): Limit 8000, Requested 8115, please reduce your "
        "message size and try again."
    )


class TestOversizedRequestFallsBackMidStream:
    """A request over a free key's ceiling should reach the next tier.

    This is the failure seen in production: the first step made a tool call,
    the tool result pushed the second request over the free key's 8,000 TPM
    ceiling, and the error surfaced to the user instead of falling through to
    the paid tier that could serve it.
    """

    def _run(self, monkeypatch):
        first = _ScriptedClient(
            [
                [_tool_call_chunk("find_extreme_location", '{"metric_id": "t2m"}')],
                _too_large_error(),
            ]
        )
        second = _ScriptedClient([[_chunk(content="Paris is the warmest.")]])
        tiers = [
            ProviderTier(name="free", client=first, model="m", max_request_tokens=None),
            ProviderTier(
                name="paid", client=second, model="m", max_request_tokens=None
            ),
        ]
        orch = _orchestrator_with(tiers)
        monkeypatch.setattr(
            orch, "_dispatch", lambda name, args, unit: json.dumps({"results": []})
        )
        return list(orch.run(question="Harder", session_id="s1")), first, second

    def test_second_tier_answers(self, monkeypatch):
        events, _, second = self._run(monkeypatch)
        assert second.calls == 1
        done = [e for e in events if e["type"] == "done"]
        assert done and done[0]["tier"] == "paid"

    def test_frontend_is_reset_before_the_retry(self, monkeypatch):
        events, _, _ = self._run(monkeypatch)
        types = [e["type"] for e in events]
        assert "reset" in types
        assert types.index("reset") < types.index("done")

    def test_no_error_event_is_surfaced(self, monkeypatch):
        events, _, _ = self._run(monkeypatch)
        assert not [e for e in events if e["type"] == "error"]

    def test_rejected_tier_is_recorded(self, monkeypatch):
        events, _, _ = self._run(monkeypatch)
        done = [e for e in events if e["type"] == "done"][0]
        assert done["rejected_tiers"] == ["free"]


class TestPreflightSkipsOversizedTier:
    def test_tier_under_its_ceiling_is_skipped_without_a_round_trip(self, monkeypatch):
        """A request the estimate already rejects should not be sent at all."""
        first = _ScriptedClient([[_chunk(content="never reached")]])
        second = _ScriptedClient([[_chunk(content="Paris is the warmest.")]])
        tiers = [
            ProviderTier(name="free", client=first, model="m", max_request_tokens=10),
            ProviderTier(
                name="paid", client=second, model="m", max_request_tokens=None
            ),
        ]
        orch = _orchestrator_with(tiers)
        events = list(orch.run(question="Harder", session_id="s1"))
        assert first.calls == 0
        done = [e for e in events if e["type"] == "done"][0]
        assert done["tier"] == "paid"
        assert done["rejected_tiers"] == ["free"]

    def test_all_tiers_too_small_reports_length_not_budget(self):
        client = _ScriptedClient([[_chunk(content="never reached")]])
        tiers = [
            ProviderTier(name="free", client=client, model="m", max_request_tokens=10)
        ]
        orch = _orchestrator_with(tiers)
        events = list(orch.run(question="Harder", session_id="s1"))
        answers = [e for e in events if e["type"] == "answer"]
        assert answers and answers[0]["text"] == _CONVERSATION_TOO_LONG_MSG
