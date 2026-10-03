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

# Non-sovereign entities, mapped to the state they belong to. GeoNames may
# flag any of them with a PPLC capital, and each is a region of its own in
# the aggregates. Codes are listed here even when no capital for them is
# currently present, so that a future locations rebuild stays correct.
# None marks a territory that belongs to no state, or whose status is
# disputed: naming a country beside it would take a side.
TERRITORY_SOVEREIGN: dict[str, str | None] = {
    # United Kingdom — overseas territories
    "AI": "GB",  # Anguilla
    "BM": "GB",  # Bermuda
    "FK": "GB",  # Falkland Islands
    "GI": "GB",  # Gibraltar
    "GS": "GB",  # South Georgia and the South Sandwich Islands
    "IO": "GB",  # British Indian Ocean Territory
    "KY": "GB",  # Cayman Islands
    "MS": "GB",  # Montserrat
    "PN": "GB",  # Pitcairn
    "SH": "GB",  # Saint Helena
    "TC": "GB",  # Turks and Caicos Islands
    "VG": "GB",  # British Virgin Islands
    # United Kingdom — crown dependencies
    "GG": "GB",  # Guernsey
    "IM": "GB",  # Isle of Man
    "JE": "GB",  # Jersey
    # United States
    "AS": "US",  # American Samoa
    "GU": "US",  # Guam
    "MP": "US",  # Northern Mariana Islands
    "PR": "US",  # Puerto Rico
    "UM": "US",  # United States Minor Outlying Islands
    "VI": "US",  # U.S. Virgin Islands
    # France — overseas departments, collectivities and territories
    "BL": "FR",  # Saint Barthelemy
    "GF": "FR",  # French Guiana
    "GP": "FR",  # Guadeloupe
    "MF": "FR",  # Saint Martin
    "MQ": "FR",  # Martinique
    "NC": "FR",  # New Caledonia
    "PF": "FR",  # French Polynesia
    "PM": "FR",  # Saint Pierre and Miquelon
    "RE": "FR",  # Reunion
    "TF": "FR",  # French Southern Territories
    "WF": "FR",  # Wallis and Futuna
    "YT": "FR",  # Mayotte
    # Kingdom of the Netherlands
    "AW": "NL",  # Aruba
    "BQ": "NL",  # Bonaire, Saint Eustatius and Saba
    "CW": "NL",  # Curacao
    "SX": "NL",  # Sint Maarten
    # Kingdom of Denmark
    "FO": "DK",  # Faroe Islands
    "GL": "DK",  # Greenland
    # Norway
    "BV": "NO",  # Bouvet Island
    "SJ": "NO",  # Svalbard and Jan Mayen
    # Finland
    "AX": "FI",  # Aland Islands
    # Australia
    "CC": "AU",  # Cocos Islands
    "CX": "AU",  # Christmas Island
    "HM": "AU",  # Heard Island and McDonald Islands
    "NF": "AU",  # Norfolk Island
    # New Zealand — territory and freely associated states
    "CK": "NZ",  # Cook Islands
    "NU": "NZ",  # Niue
    "TK": "NZ",  # Tokelau
    # China — special administrative regions
    "HK": "CN",  # Hong Kong
    "MO": "CN",  # Macao
    # Other non-self-governing territories
    "AQ": None,  # Antarctica
    "EH": None,  # Western Sahara
}

NON_SOVEREIGN_COUNTRY_CODES: frozenset[str] = frozenset(TERRITORY_SOVEREIGN)


def is_sovereign(country_code: str | None) -> bool:
    """
    True when `country_code` denotes a sovereign state.

    Unknown or missing codes are treated as sovereign so that a gap in the
    country data never silently removes a real capital from a ranking.
    """
    if not country_code:
        return True
    return country_code.strip().upper() not in NON_SOVEREIGN_COUNTRY_CODES


def sovereign_of(country_code: str | None) -> str | None:
    """
    The ISO code of the state a territory belongs to, or None.

    None for sovereign states themselves, for unknown codes, and for
    territories that belong to no state (Antarctica) or are disputed
    (Western Sahara).
    """
    if not country_code:
        return None
    return TERRITORY_SOVEREIGN.get(country_code.strip().upper())
