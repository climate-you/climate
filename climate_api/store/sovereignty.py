from __future__ import annotations

"""
Sovereignty classification for ISO 3166-1 alpha-2 country codes.

GeoNames marks a settlement as a capital with the feature code ``PPLC``,
which means "capital of a political entity" — not "capital of a country".
Dependencies and autonomous territories therefore carry capitals of their
own: Nuuk for Greenland, Longyearbyen for Svalbard, San Juan for Puerto
Rico, and so on.

That is accurate as geography but wrong as an answer: someone who asks for
the coldest or warmest capital means a country's capital, so Longyearbyen
(population ~2,400, administered by Norway from Oslo) should not outrank
Ulaanbaatar. This module draws the line, and the ``capital_only`` query
filter applies it.

Entities are treated as sovereign when they govern themselves and are not
a constituent part of, or administered by, another country. That admits UN
member states plus the Vatican, Palestine, Taiwan and Kosovo, and excludes
the territories listed below.
"""

# Non-sovereign entities that GeoNames may flag with a PPLC capital.
# Codes are listed here even when no capital for them is currently present,
# so that a future locations rebuild stays correct.
NON_SOVEREIGN_COUNTRY_CODES: frozenset[str] = frozenset(
    {
        # United Kingdom — overseas territories
        "AI",  # Anguilla
        "BM",  # Bermuda
        "FK",  # Falkland Islands
        "GI",  # Gibraltar
        "GS",  # South Georgia and the South Sandwich Islands
        "IO",  # British Indian Ocean Territory
        "KY",  # Cayman Islands
        "MS",  # Montserrat
        "PN",  # Pitcairn
        "SH",  # Saint Helena
        "TC",  # Turks and Caicos Islands
        "VG",  # British Virgin Islands
        # United Kingdom — crown dependencies
        "GG",  # Guernsey
        "IM",  # Isle of Man
        "JE",  # Jersey
        # United States
        "AS",  # American Samoa
        "GU",  # Guam
        "MP",  # Northern Mariana Islands
        "PR",  # Puerto Rico
        "UM",  # United States Minor Outlying Islands
        "VI",  # U.S. Virgin Islands
        # France — overseas departments, collectivities and territories
        "BL",  # Saint Barthelemy
        "GF",  # French Guiana
        "GP",  # Guadeloupe
        "MF",  # Saint Martin
        "MQ",  # Martinique
        "NC",  # New Caledonia
        "PF",  # French Polynesia
        "PM",  # Saint Pierre and Miquelon
        "RE",  # Reunion
        "TF",  # French Southern Territories
        "WF",  # Wallis and Futuna
        "YT",  # Mayotte
        # Kingdom of the Netherlands
        "AW",  # Aruba
        "BQ",  # Bonaire, Saint Eustatius and Saba
        "CW",  # Curacao
        "SX",  # Sint Maarten
        # Kingdom of Denmark
        "FO",  # Faroe Islands
        "GL",  # Greenland
        # Norway
        "BV",  # Bouvet Island
        "SJ",  # Svalbard and Jan Mayen
        # Finland
        "AX",  # Aland Islands
        # Australia
        "CC",  # Cocos Islands
        "CX",  # Christmas Island
        "HM",  # Heard Island and McDonald Islands
        "NF",  # Norfolk Island
        # New Zealand — territory and freely associated states
        "CK",  # Cook Islands
        "NU",  # Niue
        "TK",  # Tokelau
        # China — special administrative regions
        "HK",  # Hong Kong
        "MO",  # Macao
        # Other non-self-governing territories
        "AQ",  # Antarctica
        "EH",  # Western Sahara
    }
)


def is_sovereign(country_code: str | None) -> bool:
    """
    True when `country_code` denotes a sovereign state.

    Unknown or missing codes are treated as sovereign so that a gap in the
    country data never silently removes a real capital from a ranking.
    """
    if not country_code:
        return True
    return country_code.strip().upper() not in NON_SOVEREIGN_COUNTRY_CODES
