from __future__ import annotations

MARINE_SOURCE_NATURAL_EARTH = "natural_earth"

NATURAL_EARTH_MARINE_POLYS_PRIMARY_URL = (
    "https://www.naturalearthdata.com/http//www.naturalearthdata.com/"
    "download/10m/physical/ne_10m_geography_marine_polys.zip"
)
NATURAL_EARTH_MARINE_POLYS_MIRROR_URL = (
    "https://naciscdn.org/naturalearth/10m/physical/ne_10m_geography_marine_polys.zip"
)
NATURAL_EARTH_MARINE_POLYS_FALLBACK_URLS = [
    NATURAL_EARTH_MARINE_POLYS_PRIMARY_URL,
    NATURAL_EARTH_MARINE_POLYS_MIRROR_URL,
]


def normalize_marine_name(name: str) -> str:
    # Some upstream datasets provide names in all caps; normalize them to title case.
    if name and name == name.upper():
        return name.title()
    return name
