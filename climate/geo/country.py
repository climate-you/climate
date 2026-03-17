from __future__ import annotations

# Property field in Natural Earth admin_0 shapefiles that holds the ISO 3166-1 alpha-2 code.
COUNTRY_CODE_FIELD = "ISO_A2"

NATURAL_EARTH_COUNTRIES_PRIMARY_URL = (
    "https://www.naturalearthdata.com/http//www.naturalearthdata.com/"
    "download/50m/cultural/ne_50m_admin_0_countries.zip"
)
NATURAL_EARTH_COUNTRIES_MIRROR_URL = (
    "https://naciscdn.org/naturalearth/50m/cultural/ne_50m_admin_0_countries.zip"
)
NATURAL_EARTH_COUNTRIES_FALLBACK_URLS = [
    NATURAL_EARTH_COUNTRIES_PRIMARY_URL,
    NATURAL_EARTH_COUNTRIES_MIRROR_URL,
]
