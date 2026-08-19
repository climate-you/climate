from __future__ import annotations

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
