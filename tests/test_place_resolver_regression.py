"""
Location resolver regression tests.

Uses the real data files in data/locations/ to guard against regressions in place
label resolution across diverse geographic areas: city centres, remote land, ocean
points, small island territories, and polar regions.

These tests are skipped automatically when the location data files are absent.
Rebuild them with:

    python scripts/build/build_locations.py --source cities500 --write-kdtree \
        --write-index --write-country-mask --write-country-names
    python scripts/build/build_ocean_mask.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from climate_api.store.country_classifier import CountryClassifier
from climate_api.store.ocean_classifier import OceanClassifier
from climate_api.store.place_resolver import PlaceResolver


REPO_ROOT = Path(__file__).resolve().parents[1]
_DATA = REPO_ROOT / "data" / "locations"

_REQUIRED_FILES = [
    _DATA / "locations.csv",
    _DATA / "locations.kdtree.pkl",
    _DATA / "ocean_mask.npz",
    _DATA / "ocean_names.json",
    _DATA / "country_mask.npz",
    _DATA / "country_codes.json",
    _DATA / "country_names.json",
]


def _missing_reason() -> str | None:
    missing = [str(p.relative_to(REPO_ROOT)) for p in _REQUIRED_FILES if not p.exists()]
    return f"Missing location data files: {', '.join(missing)}" if missing else None


_skip_reason = _missing_reason()
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(_skip_reason is not None, reason=_skip_reason or "skip"),
]


@pytest.fixture(scope="module")
def resolver() -> PlaceResolver:
    ocean_classifier = OceanClassifier(
        _DATA / "ocean_mask.npz",
        _DATA / "ocean_names.json",
    )
    country_classifier = CountryClassifier(
        _DATA / "country_mask.npz",
        _DATA / "country_codes.json",
    )
    country_names = json.loads(
        (_DATA / "country_names.json").read_text(encoding="utf-8")
    )
    return PlaceResolver(
        _DATA / "locations.csv",
        kdtree_path=_DATA / "locations.kdtree.pkl",
        ocean_classifier=ocean_classifier,
        country_classifier=country_classifier,
        country_names=country_names,
    )


# (lat, lon, description, must_contain, must_not_contain)
# Either assertion field can be None to skip that check.
_CASES: list[tuple[float, float, str, str | None, str | None]] = [
    # --- Major city centres (country-constrained lookup should win) ---
    ( 48.8566,   2.3522, "Paris, France",           "France",       "Ocean"),
    ( 51.5074,  -0.1278, "London, UK",              "United Kingdom","Ocean"),
    (-33.8688, 151.2093, "Sydney, Australia",       "Australia",    "Ocean"),
    ( 35.6762, 139.6503, "Tokyo, Japan",            "Japan",        "Ocean"),
    ( 40.7128,  -74.006, "New York, USA",           "USA",          "Ocean"),
    (-22.9068,  -43.173, "Rio de Janeiro, Brazil",  "Brazil",       "Ocean"),
    ( 55.7558,   37.618, "Moscow, Russia",          "Russia",       "Ocean"),
    ( 28.6139,   77.209, "New Delhi, India",        "India",        "Ocean"),
    (-34.6037,  -58.382, "Buenos Aires, Argentina", "Argentina",    "Ocean"),
    ( 30.0444,   31.236, "Cairo, Egypt",            "Egypt",        "Ocean"),
    (-33.9249,   18.424, "Cape Town, South Africa", "South Africa", "Ocean"),

    # --- Remote land (no city nearby, but correct country via global fallback) ---
    ( 72.0,    -42.0,    "Interior Greenland",      "Greenland",    "Ocean"),
    ( 65.0,    110.0,    "Interior Siberia",        "Russia",       "Ocean"),
    (-25.0,    134.0,    "Central Australia",       "Australia",    "Ocean"),
    ( 23.0,      5.0,    "Sahara Desert, Algeria",  "Algeria",      "Ocean"),

    # --- Small island territories (country mask covers them; no ocean label) ---
    ( 78.22,    15.63,   "Longyearbyen, Svalbard",  "Svalbard",     "Ocean"),
    (-51.7,    -57.85,   "Stanley, Falkland Islands","Falkland",    "Ocean"),
    (-55.1,    -67.7,    "Navarino Island, Chile",  "Chile",        "Ocean"),

    # --- Antarctica regression (country-name fallback for countries with no cities) ---
    (-78.5,     16.7,    "Dronning Maud Land",      "Antarctica",   None),
    (-81.8,    121.7,    "East Antarctica",         "Antarctica",   None),
    (-90.0,      0.0,    "South Pole",              "Antarctica",   None),

    # --- Ocean points (country mask returns None → ocean classifier used) ---
    (  0.0,   -140.0,    "Mid Pacific Ocean",       "Pacific",      None),
    (  0.0,    -20.0,    "Mid Atlantic Ocean",      "Atlantic",     None),
    (-20.0,     70.0,    "Indian Ocean",            "Indian",       None),
    ( 85.0,      0.0,    "Arctic Ocean",            "Arctic",       None),

    # --- Coastal ocean (within 80 km of shore → "Ocean off City" label) ---
    (-33.87,   151.7,    "Off Sydney (Tasman Sea)", "off",          None),
]


@pytest.mark.parametrize(
    "lat,lon,description,must_contain,must_not_contain",
    _CASES,
    ids=[c[2] for c in _CASES],
)
def test_location_label(
    resolver: PlaceResolver,
    lat: float,
    lon: float,
    description: str,
    must_contain: str | None,
    must_not_contain: str | None,
) -> None:
    place = resolver.resolve_place(lat, lon)
    if must_contain is not None:
        assert must_contain in place.label, (
            f"[{description}] expected {must_contain!r} in label, got: {place.label!r}"
        )
    if must_not_contain is not None:
        assert must_not_contain not in place.label, (
            f"[{description}] expected {must_not_contain!r} NOT in label, got: {place.label!r}"
        )
