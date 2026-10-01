"""Whether a place name takes "the" in a running English sentence.

The panel title reads "In France, …" but "In the North Sea, …" and "In the
United Kingdom, …". English has no single rule for this, so this module encodes
the conventions that cover the names the explorer actually shows — countries
(GeoNames), seas (Natural Earth marine polygons) and lakes (Natural Earth 50m)
— plus a short list of named exceptions where usage beats the pattern.

Only the decision lives here. The name itself is never changed, because it is
also shown on its own — in search results, or as a heading — where no article
belongs.
"""

from __future__ import annotations

import re

# Countries named for a union of parts, or in the plural: "the United States",
# "the Solomon Islands", "the Central African Republic".
_COUNTRY_COMPOUND = re.compile(
    r"\b(Islands|Republic|Kingdom|States|Emirates|Territory|Territories)\b"
)

# Countries that take "the" by convention rather than by any visible pattern.
_COUNTRIES_WITH_ARTICLE = frozenset(
    {
        "Bahamas",
        "Comoros",
        "Gambia",
        "Isle of Man",
        "Maldives",
        "Netherlands",
        "Philippines",
        "Seychelles",
        "Vatican",
    }
)

# Named after their first part, which takes no article: "South Georgia and the
# South Sandwich Islands" reads as South Georgia, not as a set of islands.
_COUNTRIES_WITHOUT_ARTICLE = frozenset(
    {
        "Heard Island and McDonald Islands",
        "South Georgia and the South Sandwich Islands",
    }
)

# Water bodies where established usage overrides the pattern below.
_WATER_OVERRIDES: dict[str, bool] = {
    # Local usage drops the article for these two, unlike most straits.
    "Bass Strait": False,
    "Cook Strait": False,
    "Gulf St. Vincent": False,
    # Natural Earth names a marine polygon after the city; no article reads right.
    "Kaliningrad": False,
    # Lakes that do take one.
    "Great Salt Lake": True,
    "Lake of the Woods": True,
    "IJsselmeer": True,
    "Tonlé Sap": True,
}

_SEA = re.compile(r"\bSea\b")
_RESERVOIR_LAST = re.compile(r"\b(Reservoir|Res\.)$")
# "Lake Ontario", "Great Bear Lake", and the same shape in other languages —
# "Lago Titicaca", "Lac Saint-Jean", "Ozero Keta", "Réservoir Gouin".
_LAKE_LIKE = re.compile(
    r"^(Lake|Lago|Lagoa|Laguna|Lac|Ozero|Réservoir|Rés\.|Represa|Danau|L\.)\b"
    r"|\bLakes?$"
)
# A proper name followed by its generic noun: "Hudson Bay", "Puget Sound",
# "Cook Inlet" — but not "Bay of Bengal", which keeps its article.
_NAMED_AFTER_GENERIC = re.compile(r"^\S.* (Bay|Sound|Inlet|Basin|Fjord)$")


def takes_definite_article(name: str, kind: str) -> bool:
    """Whether `name` needs "the" before it mid-sentence.

    `kind` is the location index's kind: ``city``, ``country``, ``marine`` or
    ``lake``. A name that already starts with "The" ("The Netherlands") counts
    as taking one; the caller swaps the capital for a lowercase "the".
    """
    name = name.strip()
    if not name or kind == "city":
        return False
    if name.lower().startswith("the "):
        return True
    if kind == "country":
        return _country_takes_article(name)
    if kind in ("marine", "lake"):
        return _water_takes_article(name, kind)
    return False


def _country_takes_article(name: str) -> bool:
    if name in _COUNTRIES_WITHOUT_ARTICLE:
        return False
    return name in _COUNTRIES_WITH_ARTICLE or bool(_COUNTRY_COMPOUND.search(name))


def _water_takes_article(name: str, kind: str) -> bool:
    if name in _WATER_OVERRIDES:
        return _WATER_OVERRIDES[name]
    if _SEA.search(name) or _RESERVOIR_LAST.search(name):
        return True  # "the Dead Sea", "the Bratsk Reservoir"
    if _LAKE_LIKE.search(name) or _NAMED_AFTER_GENERIC.search(name):
        return False  # "Lake Ontario", "Hudson Bay"
    if kind == "lake":
        return False  # native-language names read as proper names: "Tai Hu", "Vänern"
    # Seas, oceans, gulfs, straits, channels, rivers, passages — and names kept
    # in their own language ("Golfo de California"), where "the" is the least
    # awkward choice in an English sentence.
    return True
