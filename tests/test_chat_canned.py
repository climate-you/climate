from __future__ import annotations

import pytest

from climate_api.chat.canned import _apply_unit, lookup


class TestApplyUnit:
    def test_celsius_returns_first_token(self):
        assert (
            _apply_unit("Temperature is [[20|68]] degrees.", "C")
            == "Temperature is 20 degrees."
        )

    def test_fahrenheit_returns_second_token(self):
        assert (
            _apply_unit("Temperature is [[20|68]] degrees.", "F")
            == "Temperature is 68 degrees."
        )

    def test_no_tokens_unchanged(self):
        text = "No temperature here."
        assert _apply_unit(text, "C") == text
        assert _apply_unit(text, "F") == text

    def test_multiple_tokens_all_replaced(self):
        text = "Min [[10|50]] and max [[30|86]]."
        assert _apply_unit(text, "C") == "Min 10 and max 30."
        assert _apply_unit(text, "F") == "Min 50 and max 86."

    def test_decimal_values_preserved(self):
        text = "Trend: [[1.21|2.18]] per decade."
        assert _apply_unit(text, "C") == "Trend: 1.21 per decade."
        assert _apply_unit(text, "F") == "Trend: 2.18 per decade."

    def test_empty_string_unchanged(self):
        assert _apply_unit("", "C") == ""
        assert _apply_unit("", "F") == ""


class TestLookup:
    def test_returns_none_for_unknown_question(self):
        assert lookup("zzzthis question does not exist in the treezzz") is None

    def test_case_insensitive_match(self, monkeypatch):
        from climate_api.chat import canned as canned_module

        monkeypatch.setattr(
            canned_module,
            "CANNED",
            {"how warm is earth": ("The Earth is warming.", [], None, [])},
        )
        assert lookup("How Warm Is Earth") is not None

    def test_extra_whitespace_normalised(self, monkeypatch):
        from climate_api.chat import canned as canned_module

        monkeypatch.setattr(
            canned_module, "CANNED", {"how warm is earth": ("answer", [], None, [])}
        )
        assert lookup("  how warm   is earth  ") is not None

    def test_exact_match_returns_full_tuple(self, monkeypatch):
        from climate_api.chat import canned as canned_module

        expected = (
            "It's the long-term weather.",
            [{"lat": 0.0, "lon": 0.0}],
            {"metric_id": "t2m"},
            ["q2"],
        )
        monkeypatch.setattr(canned_module, "CANNED", {"what is climate": expected})
        assert lookup("what is climate") == expected

    def test_missing_key_returns_none(self, monkeypatch):
        from climate_api.chat import canned as canned_module

        monkeypatch.setattr(
            canned_module, "CANNED", {"known question": ("answer", [], None, [])}
        )
        assert lookup("unknown question") is None


class TestAnswerRegions:
    """A canned answer offers the regions its chart plots and its text names."""

    def _index(self):
        from types import SimpleNamespace

        hits = {
            "country:EG": SimpleNamespace(
                geonameid=1,
                label="Egypt",
                lat=26.5,
                lon=29.9,
                country_code="EG",
                population=1,
                alt_names="",
                kind="country",
                bbox=None,
            ),
            "country:LY": SimpleNamespace(
                geonameid=2,
                label="Libya",
                lat=27.0,
                lon=17.0,
                country_code="LY",
                population=1,
                alt_names="",
                kind="country",
                bbox=None,
            ),
        }
        return SimpleNamespace(resolve_by_region_id=hits.get)

    def test_named_charted_country_is_offered(self):
        from types import SimpleNamespace

        from climate_api.chat.canned import answer_regions

        store = SimpleNamespace(
            region_ids=frozenset({"country:EG", "country:LY", "globe"})
        )
        spec = {"metric_id": "tp", "region_ids": ["country:EG", "globe"]}
        regions = answer_regions("**Egypt** is the driest.", spec, self._index(), store)
        assert [r["region_id"] for r in regions] == ["country:EG"]

    def test_no_chart_or_no_regions_offers_nothing(self):
        from types import SimpleNamespace

        from climate_api.chat.canned import answer_regions

        store = SimpleNamespace(region_ids=frozenset({"country:EG"}))
        assert answer_regions("Egypt", None, self._index(), store) == []
        assert answer_regions("Egypt", {"metric_id": "tp"}, self._index(), store) == []

    def test_multi_series_spec_is_read(self):
        from types import SimpleNamespace

        from climate_api.chat.canned import answer_regions

        store = SimpleNamespace(region_ids=frozenset({"country:EG", "country:LY"}))
        spec = {
            "series": [
                {"metric_id": "a", "region_ids": ["country:EG"]},
                {"metric_id": "b", "region_ids": ["country:LY"]},
            ]
        }
        regions = answer_regions("Egypt and Libya.", spec, self._index(), store)
        assert {r["region_id"] for r in regions} == {"country:EG", "country:LY"}
