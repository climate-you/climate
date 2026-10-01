from __future__ import annotations

LAKE_SOURCE_NATURAL_EARTH = "natural_earth"

# The 50m set holds the world's major lakes and reservoirs (~275 named features).
# The 10m set adds several thousand small ones, which crowd the autocomplete
# without adding places anyone searches for by name.
NATURAL_EARTH_LAKES_PRIMARY_URL = (
    "https://www.naturalearthdata.com/http//www.naturalearthdata.com/"
    "download/50m/physical/ne_50m_lakes.zip"
)
NATURAL_EARTH_LAKES_MIRROR_URL = (
    "https://naciscdn.org/naturalearth/50m/physical/ne_50m_lakes.zip"
)
NATURAL_EARTH_LAKES_FALLBACK_URLS = [
    NATURAL_EARTH_LAKES_PRIMARY_URL,
    NATURAL_EARTH_LAKES_MIRROR_URL,
]
