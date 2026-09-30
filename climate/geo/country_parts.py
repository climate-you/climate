"""Parts of a country that the explorer treats as regions of their own.

Natural Earth's admin_0 polygon for France includes French Guiana, Réunion and
the other overseas departments; Norway's includes Svalbard; the United States'
includes Alaska and Hawaii. Averaged together, a country's figure is then partly
about a place thousands of kilometres from the mainland the map frames: French
Guiana is 13% of France's average, Alaska 15% of the US's, Svalbard 16% of
Norway's. National weather services report the mainland (Météo-France's
metropolitan France, NOAA's contiguous US), and so does this.

The split parts are burned over their country in the country mask, so they are
averaged, outlined and searchable on their own:

- **Map units with their own ISO code.** Natural Earth's admin_0 *map units*
  split a country into its geographically separate units; those carrying an
  ISO 3166-1 code of their own (French Guiana GF, Svalbard SJ, the Caribbean
  Netherlands BQ, ...) become that country. The rule, not a list, picks them,
  and it matches GeoNames, which already files those places' towns under the
  same codes.
- **Named subdivisions.** Parts with no ISO country code: Alaska and Hawaii,
  from Natural Earth's admin-1 states, keyed by their ISO 3166-2 code.

Countries whose far parts stay in (the Azores, the Canaries, the Galápagos:
a few percent of the average) get a note saying so instead; see REGION_NOTES.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

NATURAL_EARTH_MAP_UNITS_URL = (
    "https://naciscdn.org/naturalearth/50m/cultural/ne_50m_admin_0_map_units.zip"
)
NATURAL_EARTH_ADMIN1_URL = (
    "https://naciscdn.org/naturalearth/50m/cultural/"
    "ne_50m_admin_1_states_provinces.zip"
)

# Subdivisions split from their country, by ISO 3166-2 code.
SUBDIVISIONS: dict[str, str] = {
    "US-AK": "Alaska",
    "US-HI": "Hawaii",
}

# Map units whose Natural Earth code disagrees with ISO 3166. Natural Earth
# files Jan Mayen under Norway; ISO and GeoNames put it with Svalbard (SJ,
# "Svalbard and Jan Mayen").
MAP_UNIT_CODE_OVERRIDES: dict[str, str] = {
    "Jan Mayen": "SJ",
}

# What a country's figures cover, where that is not the obvious whole.
REGION_NOTES: dict[str, str] = {
    "country:FR": (
        "Metropolitan France and Corsica. French Guiana, Guadeloupe, Martinique, "
        "Réunion and Mayotte have their own entries."
    ),
    "country:NO": "Mainland Norway. Svalbard and Jan Mayen have their own entry.",
    "country:NL": (
        "The European Netherlands. Bonaire, Sint Eustatius and Saba have their "
        "own entry."
    ),
    "country:US": "The contiguous United States. Alaska and Hawaii have their own entries.",
    "country:PT": "Includes the Azores and Madeira.",
    "country:ES": "Includes the Canary Islands.",
    "country:EC": "Includes the Galápagos Islands.",
}


def parent_country_code(code: str) -> str:
    """The ISO 3166-1 country a mask code belongs to: US-AK → US, FR → FR."""
    return code.split("-", 1)[0]


def is_subdivision(code: str) -> bool:
    return "-" in code


@dataclass(frozen=True)
class CountryPart:
    """A part of a country split off as a region of its own."""

    code: str  # ISO 3166-1 alpha-2, or ISO 3166-2 for a subdivision
    parent: str  # the country it is split from
    name: str  # Natural Earth's name; GeoNames' is preferred where it has one
    geometry: Any
    label_point: tuple[float, float] | None  # (lat, lon)


@dataclass(frozen=True)
class CountryParts:
    parts: list[CountryPart]
    # Natural Earth admin_0 features (ADM0_A3) whose every map unit is split
    # off, so nothing of them is left to count towards their country — the
    # Indian Ocean Territories, filed under Australia, become Christmas Island
    # and the Cocos Islands.
    fully_split_adm0: frozenset[str]


def natural_earth_iso_code(props: dict, code_field: str = "ISO_A2") -> str:
    """A Natural Earth feature's ISO 3166-1 alpha-2 code, or "" if it has none.

    `code_field` holds "-99" where Natural Earth leaves the code unassigned
    (France, Norway, Kosovo), and sometimes an ISO 3166-2 code instead: Taiwan
    is "CN-TW", a map unit like French Guiana "FR-973". ISO_A2_EH has the
    country-level code in both cases. Mask codes with a hyphen are reserved for
    the subdivisions split off on purpose (SUBDIVISIONS), which the rest of the
    pipeline treats as part of their country.
    """
    code = str(props.get(code_field) or "").strip().upper()
    if not code or code == "-99" or "-" in code:
        code = str(props.get("ISO_A2_EH") or "").strip().upper()
    return "" if code == "-99" or "-" in code else code


def _label_point(props: dict, x_field: str, y_field: str) -> tuple[float, float] | None:
    try:
        return float(props[y_field]), float(props[x_field])
    except (KeyError, TypeError, ValueError):
        return None


def load_country_parts(
    *, countries_path: str, map_units_path: str, admin1_path: str
) -> CountryParts:
    """Every split part, map units first, then subdivisions.

    Paths are anything fiona opens (a `zip://` path for the Natural Earth zips).
    """
    import fiona

    country_codes: dict[str, str] = {}
    with fiona.open(countries_path, "r") as src:
        for feat in src:
            props = feat.get("properties") or {}
            country_codes[str(props.get("ADM0_A3"))] = natural_earth_iso_code(props)

    parts: list[CountryPart] = []
    units_left: dict[str, int] = {}
    with fiona.open(map_units_path, "r") as src:
        for feat in src:
            props = feat.get("properties") or {}
            adm0 = str(props.get("ADM0_A3"))
            name = str(props.get("GEOUNIT") or "")
            code = MAP_UNIT_CODE_OVERRIDES.get(name) or natural_earth_iso_code(props)
            parent = country_codes.get(adm0, "")
            units_left.setdefault(adm0, 0)
            if not code or not parent or code == parent or not feat.get("geometry"):
                units_left[adm0] += 1
                continue
            parts.append(
                CountryPart(
                    code=code,
                    parent=parent,
                    name=name,
                    geometry=feat["geometry"],
                    label_point=_label_point(props, "LABEL_X", "LABEL_Y"),
                )
            )

    with fiona.open(admin1_path, "r") as src:
        for feat in src:
            props = feat.get("properties") or {}
            code = str(props.get("iso_3166_2") or "").strip().upper()
            if code not in SUBDIVISIONS or not feat.get("geometry"):
                continue
            parts.append(
                CountryPart(
                    code=code,
                    parent=parent_country_code(code),
                    name=SUBDIVISIONS[code],
                    geometry=feat["geometry"],
                    label_point=_label_point(props, "longitude", "latitude"),
                )
            )
    return CountryParts(
        parts=parts,
        fully_split_adm0=frozenset(a for a, n in units_left.items() if n == 0),
    )
