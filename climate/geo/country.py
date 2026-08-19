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

# Display names to use in place of the ones GeoNames' countryInfo.txt supplies,
# keyed by ISO 3166-1 alpha-2 code.
COUNTRY_NAME_OVERRIDES: dict[str, str] = {
    # GeoNames still says "Palestinian Territory"; "Palestine" matches current
    # UN usage and how the other entries here are worded.
    "PS": "Palestine",
}

# Superseded names, casefolded, kept resolvable so that queries and saved links
# written against the old wording keep working.
LEGACY_COUNTRY_NAMES: dict[str, str] = {
    "palestinian territory": "PS",
}


def apply_country_name_overrides(names: dict[str, str]) -> dict[str, str]:
    """Return `names` (ISO alpha-2 → country name) with the overrides applied."""
    merged = dict(names)
    for code, name in COUNTRY_NAME_OVERRIDES.items():
        if code in merged:
            merged[code] = name
    return merged
