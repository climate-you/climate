from __future__ import annotations

import pytest
import xarray as xr

from climate.geo import ensure_lon_pm180, normalize_lon_pm180
from climate.geo.country import (
    LEGACY_COUNTRY_NAMES,
    apply_country_name_overrides,
)
from climate.geo.marine import (
    MARINE_SOURCE_NATURAL_EARTH,
    NATURAL_EARTH_MARINE_POLYS_FALLBACK_URLS,
    normalize_marine_name,
)
from climate.geo.names import takes_definite_article
from climate.geo.regions import (
    continent_region_id,
    country_region_id,
    ocean_region_id,
    slugify_region_name,
)


def test_lon_helpers_available_from_package_root() -> None:
    assert normalize_lon_pm180(180.0) == -180.0
    ds = xr.Dataset(coords={"lon": [0.0, 180.0, 359.0]})
    out = ensure_lon_pm180(ds, "lon")
    assert float(out["lon"].min()) >= -180.0
    assert float(out["lon"].max()) < 180.0


def test_marine_helpers_and_constants() -> None:
    assert MARINE_SOURCE_NATURAL_EARTH == "natural_earth"
    assert len(NATURAL_EARTH_MARINE_POLYS_FALLBACK_URLS) >= 1
    assert normalize_marine_name("NORTH ATLANTIC OCEAN") == "North Atlantic Ocean"


def test_country_name_overrides_rename_only_the_listed_codes() -> None:
    out = apply_country_name_overrides(
        {"PS": "Palestinian Territory", "IL": "Israel", "FR": "France"}
    )
    assert out["PS"] == "Palestine"
    assert out["IL"] == "Israel"
    assert out["FR"] == "France"


def test_country_name_overrides_do_not_invent_missing_codes() -> None:
    """A code absent from the source map must not be added by the override."""
    assert apply_country_name_overrides({"FR": "France"}) == {"FR": "France"}


def test_country_name_overrides_leave_input_untouched() -> None:
    source = {"PS": "Palestinian Territory"}
    apply_country_name_overrides(source)
    assert source == {"PS": "Palestinian Territory"}


def test_legacy_country_names_still_map_to_their_code() -> None:
    assert LEGACY_COUNTRY_NAMES["palestinian territory"] == "PS"


def test_region_ids_match_the_spelling_used_by_the_aggregates() -> None:
    # These strings are the contract between the aggregate precompute, which
    # writes the keys, and the location index, which writes the column the API
    # looks them up by. Changing one without the other breaks region panels
    # silently, so pin the exact spelling here.
    assert country_region_id("fr") == "country:FR"
    assert country_region_id(" fr ") == "country:FR"
    assert ocean_region_id("North Sea") == "ocean:north_sea"
    assert ocean_region_id("Bahía de Campeche") == "ocean:bahia_de_campeche"
    assert ocean_region_id("Bab el Mandeb") == "ocean:bab_el_mandeb"
    assert continent_region_id("north america") == "continent:north_america"


def test_slugify_strips_accents_and_folds_separators() -> None:
    assert slugify_region_name("Baía de Marajó") == "baia_de_marajo"
    assert slugify_region_name("Bass Strait-North") == "bass_strait_north"


@pytest.mark.parametrize(
    "name, kind, expected",
    [
        # Cities never take one, whatever they are called.
        ("North Sea NY, USA", "city", False),
        ("The Hague, Netherlands", "city", False),
        # Countries: plain names do not; unions and plurals do.
        ("France", "country", False),
        ("Spain", "country", False),
        ("United Kingdom", "country", True),
        ("United States", "country", True),
        ("Solomon Islands", "country", True),
        ("Democratic Republic of the Congo", "country", True),
        ("Philippines", "country", True),
        ("Gambia", "country", True),
        # Already carries it, capitalised: counts as taking one.
        ("The Netherlands", "country", True),
        # Named after a first part that takes none.
        ("South Georgia and the South Sandwich Islands", "country", False),
        ("Saint Vincent and the Grenadines", "country", False),
        # Seas, oceans, gulfs, straits, channels, rivers: yes.
        ("North Sea", "marine", True),
        ("Pacific Ocean", "marine", True),
        ("Gulf of Mexico", "marine", True),
        ("Persian Gulf", "marine", True),
        ("Bay of Bengal", "marine", True),
        ("Strait of Gibraltar", "marine", True),
        ("Davis Strait", "marine", True),
        ("English Channel", "marine", True),
        ("Amazon River", "marine", True),
        ("Great Barrier Reef", "marine", True),
        ("The North Western Passages", "marine", True),
        # A proper name before its generic noun: no.
        ("Hudson Bay", "marine", False),
        ("Puget Sound", "marine", False),
        ("Cook Inlet", "marine", False),
        # Local usage beats the strait pattern.
        ("Bass Strait", "marine", False),
        # Lakes: no, except seas, reservoirs and a few by convention.
        ("Lake Ontario", "lake", False),
        ("Great Bear Lake", "lake", False),
        ("Lago Titicaca", "lake", False),
        ("Tai Hu", "lake", False),
        ("Dead Sea", "lake", True),
        ("Sea of Galilee", "lake", True),
        ("Bratsk Reservoir", "lake", True),
        ("Lake of the Woods", "lake", True),
        ("Great Salt Lake", "lake", True),
    ],
)
def test_definite_article(name: str, kind: str, expected: bool) -> None:
    assert takes_definite_article(name, kind) is expected
