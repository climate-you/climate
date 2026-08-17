"""
Regression tests for chat place-name resolution (`chat.tools.resolve_location`).

The chat path used to resolve names with the prefix search alone, which matches
only literal labels and ranks by population. That sent every exonym to the wrong
place — "Londres" to a village in Argentina, "Cologne, Germany" to Cologne in
Italy — and dropped the country qualifier on the floor while doing it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from climate_api.chat.tools import _country_code_for, resolve_location
from climate_api.store.location_index import LocationIndex

REPO_ROOT = Path(__file__).resolve().parents[1]
INDEX_CSV = REPO_ROOT / "data" / "locations" / "locations.index.csv"
COUNTRY_NAMES = REPO_ROOT / "data" / "locations" / "country_names.json"


@pytest.fixture(scope="module")
def location_index():
    if not INDEX_CSV.exists():
        pytest.skip(f"no location index at {INDEX_CSV}")
    return LocationIndex(INDEX_CSV)


@pytest.fixture(scope="module")
def country_name_to_code():
    if not COUNTRY_NAMES.exists():
        pytest.skip(f"no country names at {COUNTRY_NAMES}")
    names = json.loads(COUNTRY_NAMES.read_text(encoding="utf-8"))
    return {v.casefold(): k for k, v in names.items()}


# ---------------------------------------------------------------------------
# Country qualifier parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "qualifier,expected",
    [
        ("Germany", "DE"),
        ("germany", "DE"),
        ("  Germany  ", "DE"),
        ("UK", "GB"),
        ("uk", "GB"),
        ("England", "GB"),
        ("USA", "US"),
        ("America", "US"),
        ("DE", "DE"),
        ("fr", "FR"),
        ("Czechia", "CZ"),
        ("", None),
        ("Nowhereland", None),
    ],
)
def test_country_qualifier_mapping(qualifier, expected, country_name_to_code):
    assert _country_code_for(qualifier, country_name_to_code) == expected


# ---------------------------------------------------------------------------
# The reported bugs
# ---------------------------------------------------------------------------


def test_londres_resolves_to_london_not_argentina(location_index, country_name_to_code):
    """The French exonym must beat the literal-label village in Argentina."""
    result = resolve_location("Londres", location_index, country_name_to_code)
    assert result["label"] == "London, United Kingdom"
    assert result["country"] == "GB"


def test_cologne_germany_resolves_to_koln(location_index, country_name_to_code):
    """The country qualifier must disambiguate, not be discarded."""
    result = resolve_location("Cologne, Germany", location_index, country_name_to_code)
    assert result["label"] == "Köln, Germany"
    assert result["country"] == "DE"


def test_cologne_italy_still_resolves_to_italy(location_index, country_name_to_code):
    """Disambiguation must cut both ways — the Italian town is a real answer."""
    result = resolve_location("Cologne, Italy", location_index, country_name_to_code)
    assert result["country"] == "IT"


# ---------------------------------------------------------------------------
# Exonyms in general
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query,expected_label",
    [
        ("Firenze", "Florence, Italy"),
        ("Moscou", "Moscow, Russia"),
        ("Wien", "Vienna, Austria"),
        ("Zurich", "Zürich, Switzerland"),
        ("Köln", "Köln, Germany"),
        ("Cologne", "Köln, Germany"),
    ],
)
def test_exonyms_resolve_to_the_real_city(
    query, expected_label, location_index, country_name_to_code
):
    result = resolve_location(query, location_index, country_name_to_code)
    assert result.get("label") == expected_label


# ---------------------------------------------------------------------------
# No regressions on the names that already worked
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query,expected_label",
    [
        ("London", "London, United Kingdom"),
        ("London, Canada", "London, Canada"),
        ("Paris", "Paris, France"),
        ("Munich, Germany", "Munich, Germany"),
        ("Rome, Italy", "Rome, Italy"),
        ("Stockholm", "Stockholm, Sweden"),
        ("Madrid", "Madrid, Spain"),
    ],
)
def test_plain_names_are_unchanged(
    query, expected_label, location_index, country_name_to_code
):
    result = resolve_location(query, location_index, country_name_to_code)
    assert result.get("label") == expected_label


def test_qualifier_naming_an_unknown_country_falls_back(
    location_index, country_name_to_code
):
    """An unparseable qualifier should still resolve the city, not error out."""
    result = resolve_location("Paris, Freedonia", location_index, country_name_to_code)
    assert result.get("label") == "Paris, France"


def test_resolution_works_without_a_country_map(location_index):
    """The map is optional; built-in aliases still disambiguate."""
    result = resolve_location("Londres, UK", location_index, None)
    assert result["label"] == "London, United Kingdom"


def test_unknown_place_reports_an_error(location_index, country_name_to_code):
    result = resolve_location("Nowhereville", location_index, country_name_to_code)
    assert "error" in result
    assert "Nowhereville" in result["error"]


def test_markdown_bold_is_stripped(location_index, country_name_to_code):
    """LLMs sometimes emit '**Paris**' as the argument."""
    result = resolve_location("**Paris**", location_index, country_name_to_code)
    assert result.get("label") == "Paris, France"


# ---------------------------------------------------------------------------
# Index-level behaviour the resolver depends on
# ---------------------------------------------------------------------------


def test_resolve_all_by_any_name_keeps_homonyms(location_index):
    hits = location_index.resolve_all_by_any_name("Cologne")
    countries = {h.country_code for h in hits}
    assert {
        "DE",
        "IT",
    } <= countries, (
        "both Köln and Cologne (IT) must remain reachable for disambiguation"
    )
    populations = [h.population for h in hits]
    assert populations == sorted(populations, reverse=True)


def test_resolve_all_by_any_name_agrees_with_single_lookup(location_index):
    for name in ("Cologne", "Londres", "Paris", "London"):
        best = location_index.resolve_by_any_name(name)
        every = location_index.resolve_all_by_any_name(name)
        assert every, f"{name} should have at least one match"
        assert every[0].geonameid == best.geonameid


def test_resolve_all_by_any_name_rejects_short_queries(location_index):
    assert location_index.resolve_all_by_any_name("a") == []
    assert location_index.resolve_all_by_any_name("") == []
