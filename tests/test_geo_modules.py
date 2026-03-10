from __future__ import annotations

import xarray as xr

from climate.geo import ensure_lon_pm180, normalize_lon_pm180
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
