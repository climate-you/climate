"""Region identifiers shared by the aggregate precompute and the search index.

A region_id names one entry in the precomputed regional aggregates, e.g.
``country:FR`` or ``ocean:north_sea``. Two unrelated build steps have to agree
on the exact spelling — `scripts/precompute_regional_aggregates.py` writes the
keys, `scripts/build/build_locations.py` writes the index column the API looks
them up by — so the spelling lives here rather than being reimplemented in
each, where the two copies could drift apart unnoticed.
"""

from __future__ import annotations

import unicodedata

REGION_KIND_COUNTRY = "country"
REGION_KIND_STATE = "state"
REGION_KIND_OCEAN = "ocean"
REGION_KIND_CONTINENT = "continent"

REGION_ID_GLOBE = "globe"


def slugify_region_name(name: str) -> str:
    """Convert a region name to a URL-safe slug: lowercase, spaces→underscores."""
    normalized = unicodedata.normalize("NFD", name)
    ascii_str = normalized.encode("ascii", "ignore").decode("ascii")
    return ascii_str.lower().replace(" ", "_").replace("-", "_")


def country_region_id(country_code: str) -> str:
    """Region id for an ISO 3166-1 alpha-2 country code, e.g. FR → country:FR."""
    return f"{REGION_KIND_COUNTRY}:{country_code.strip().upper()}"


def state_region_id(code: str) -> str:
    """Region id for an ISO 3166-2 subdivision code, e.g. US-AK → state:US-AK."""
    return f"{REGION_KIND_STATE}:{code.strip().upper()}"


def country_mask_region_id(code: str) -> str:
    """Region id for a country-mask code: a country, or a subdivision split from
    one (see climate.geo.country_parts), told apart by the ISO 3166-2 hyphen."""
    return state_region_id(code) if "-" in code else country_region_id(code)


def ocean_region_id(name: str) -> str:
    """Region id for a marine feature name, e.g. North Sea → ocean:north_sea."""
    return f"{REGION_KIND_OCEAN}:{slugify_region_name(name)}"


def continent_region_id(name: str) -> str:
    """Region id for a continent name, e.g. North America → continent:north_america."""
    return f"{REGION_KIND_CONTINENT}:{name.replace(' ', '_')}"
