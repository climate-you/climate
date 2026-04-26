from __future__ import annotations

import pytest

from climate_api.chat.canned import _apply_unit, lookup


class TestApplyUnit:
    def test_celsius_returns_first_token(self):
        assert _apply_unit("Temperature is [[20|68]] degrees.", "C") == "Temperature is 20 degrees."

    def test_fahrenheit_returns_second_token(self):
        assert _apply_unit("Temperature is [[20|68]] degrees.", "F") == "Temperature is 68 degrees."

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
            canned_module, "CANNED", {"how warm is earth": ("The Earth is warming.", [], None, [])}
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

        expected = ("It's the long-term weather.", [{"lat": 0.0, "lon": 0.0}], {"metric_id": "t2m"}, ["q2"])
        monkeypatch.setattr(canned_module, "CANNED", {"what is climate": expected})
        assert lookup("what is climate") == expected

    def test_missing_key_returns_none(self, monkeypatch):
        from climate_api.chat import canned as canned_module

        monkeypatch.setattr(canned_module, "CANNED", {"known question": ("answer", [], None, [])})
        assert lookup("unknown question") is None
