"""Parts split from their country: French Guiana from France, Alaska from the US."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("fiona")

from climate.geo.country_parts import load_country_parts, parent_country_code
from climate.geo.regions import country_mask_region_id
from climate_api.store.country_classifier import CountryClassifier


def _square(x0: float, y0: float, x1: float, y1: float) -> dict:
    ring = [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]
    return {"type": "Polygon", "coordinates": [ring]}


def _write(path: Path, features: list[tuple[dict, dict]]) -> str:
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "properties": p, "geometry": g}
                    for p, g in features
                ],
            }
        )
    )
    return str(path)


@pytest.fixture()
def parts(tmp_path: Path):
    countries = _write(
        tmp_path / "countries.geojson",
        [
            # France's ISO_A2 is "-99" in Natural Earth; ISO_A2_EH carries FR.
            (
                {"ADM0_A3": "FRA", "ISO_A2": "-99", "ISO_A2_EH": "FR"},
                _square(0, 40, 8, 50),
            ),
            (
                {"ADM0_A3": "NOR", "ISO_A2": "-99", "ISO_A2_EH": "NO"},
                _square(5, 58, 30, 71),
            ),
            (
                {"ADM0_A3": "IOA", "ISO_A2": "-99", "ISO_A2_EH": "AU"},
                _square(96, -13, 106, -10),
            ),
        ],
    )
    map_units = _write(
        tmp_path / "map_units.geojson",
        [
            # The metropole shares its country's code: not split.
            (
                {
                    "ADM0_A3": "FRA",
                    "GEOUNIT": "France",
                    "ISO_A2": "FR",
                    "ISO_A2_EH": "FR",
                    "LABEL_X": 2.0,
                    "LABEL_Y": 46.0,
                },
                _square(0, 40, 8, 50),
            ),
            # Map units carry ISO 3166-2 codes in ISO_A2; the country-level code
            # is in ISO_A2_EH.
            (
                {
                    "ADM0_A3": "FRA",
                    "GEOUNIT": "French Guiana",
                    "ISO_A2": "FR-973",
                    "ISO_A2_EH": "GF",
                    "LABEL_X": -53.0,
                    "LABEL_Y": 4.0,
                },
                _square(-55, 2, -51, 6),
            ),
            (
                {
                    "ADM0_A3": "NOR",
                    "GEOUNIT": "Norway",
                    "ISO_A2": "-99",
                    "ISO_A2_EH": "NO",
                    "LABEL_X": 9.0,
                    "LABEL_Y": 61.0,
                },
                _square(5, 58, 30, 71),
            ),
            # Natural Earth files Jan Mayen under Norway; ISO puts it with SJ.
            (
                {
                    "ADM0_A3": "NOR",
                    "GEOUNIT": "Jan Mayen",
                    "ISO_A2": "-99",
                    "ISO_A2_EH": "NO",
                    "LABEL_X": -8.5,
                    "LABEL_Y": 71.0,
                },
                _square(-9, 70.8, -7.9, 71.2),
            ),
            (
                {
                    "ADM0_A3": "IOA",
                    "GEOUNIT": "Christmas Island",
                    "ISO_A2": "CX",
                    "ISO_A2_EH": "CX",
                    "LABEL_X": 105.6,
                    "LABEL_Y": -10.5,
                },
                _square(105, -11, 106, -10),
            ),
            (
                {
                    "ADM0_A3": "IOA",
                    "GEOUNIT": "Cocos (Keeling) Islands",
                    "ISO_A2": "CC",
                    "ISO_A2_EH": "CC",
                    "LABEL_X": 96.8,
                    "LABEL_Y": -12.1,
                },
                _square(96, -13, 97, -12),
            ),
        ],
    )
    admin1 = _write(
        tmp_path / "admin1.geojson",
        [
            (
                {
                    "iso_3166_2": "US-AK",
                    "name": "Alaska",
                    "latitude": 64.0,
                    "longitude": -150.0,
                },
                _square(-170, 55, -130, 71),
            ),
            (
                {
                    "iso_3166_2": "US-TX",
                    "name": "Texas",
                    "latitude": 31.0,
                    "longitude": -99.0,
                },
                _square(-106, 26, -94, 36),
            ),
        ],
    )
    return load_country_parts(
        countries_path=countries, map_units_path=map_units, admin1_path=admin1
    )


def test_a_map_unit_with_its_own_iso_code_is_split_off(parts) -> None:
    codes = {(p.code, p.parent, p.name) for p in parts.parts}
    assert ("GF", "FR", "French Guiana") in codes
    assert not any(p.code in ("FR", "NO") for p in parts.parts)


def test_jan_mayen_goes_with_svalbard(parts) -> None:
    assert [p.code for p in parts.parts if p.name == "Jan Mayen"] == ["SJ"]


def test_only_the_named_subdivisions_are_split(parts) -> None:
    subdivisions = [p for p in parts.parts if p.code.startswith("US-")]
    assert [(p.code, p.parent, p.label_point) for p in subdivisions] == [
        ("US-AK", "US", (64.0, -150.0))
    ]


def test_a_feature_split_into_nothing_but_parts_is_reported(parts) -> None:
    # Australia's Indian Ocean Territories: Christmas Island and the Cocos
    # Islands, and nothing left over for Australia.
    assert parts.fully_split_adm0 == frozenset({"IOA"})


def test_region_ids_tell_a_subdivision_from_a_country() -> None:
    assert country_mask_region_id("GF") == "country:GF"
    assert country_mask_region_id("US-AK") == "state:US-AK"
    assert parent_country_code("US-AK") == "US"
    assert parent_country_code("GF") == "GF"


def test_the_classifier_reports_a_subdivision_as_its_country(tmp_path: Path) -> None:
    # Towns are filed by country: a click in Alaska must look for US towns.
    data = np.zeros((4, 4), np.uint16)
    data[0, 0] = 1
    data[0, 1] = 2
    np.savez(tmp_path / "mask.npz", data=data, deg=1.0, lat_max=2.0, lon_min=0.0)
    (tmp_path / "codes.json").write_text(json.dumps({"1": "US-AK", "2": "GF"}))
    classifier = CountryClassifier(tmp_path / "mask.npz", tmp_path / "codes.json")
    assert classifier.classify(1.5, 0.5) == "US"
    assert classifier.classify(1.5, 1.5) == "GF"


def test_parts_take_their_cells_and_get_their_own_entries(
    tmp_path: Path, parts
) -> None:
    from scripts.build.build_locations import (
        build_country_mask,
        load_country_index_rows,
    )

    countries = tmp_path / "countries.geojson"
    build_country_mask(
        output_npz=tmp_path / "mask.npz",
        output_codes_json=tmp_path / "codes.json",
        deg=1.0,
        cache_dir=tmp_path,
        input_path=countries,
        parts=parts,
    )
    mask = np.load(tmp_path / "mask.npz")["data"]
    codes = {
        int(k): v for k, v in json.loads((tmp_path / "codes.json").read_text()).items()
    }
    # French Guiana, burned over nothing here, and Christmas Island, burned over
    # the Australian-coded feature it was part of.
    guiana = codes[int(mask[90 - 4, 180 - 53])]
    christmas = codes[int(mask[90 + 10, 180 + 105])]
    assert (guiana, christmas) == ("GF", "CX")
    assert codes[int(mask[90 - 45, 180 + 4])] == "FR"

    rows = load_country_index_rows(
        input_path=countries,
        country_names={
            "FR": "France",
            "NO": "Norway",
            "AU": "Australia",
            "GF": "French Guiana",
            "SJ": "Svalbard and Jan Mayen",
        },
        country_populations={"GF": 300_000},
        parts=parts,
    )
    by_region = {r["region_id"]: r for r in rows}
    assert by_region["country:GF"]["label"] == "French Guiana"
    assert by_region["state:US-AK"]["kind"] == "state"
    assert by_region["state:US-AK"]["country_code"] == "US"
    # Wholly split off, the territories no longer stretch Australia's box —
    # nothing is left of it, so Australia has no entry from it at all here.
    assert "country:AU" not in by_region
    # Parts get their own id block: existing country ids do not shift.
    assert int(by_region["country:GF"]["geonameid"]) >= 2_300_000_000
    assert int(by_region["country:FR"]["geonameid"]) < 2_300_000_000


def test_a_country_coded_as_a_subdivision_gets_its_own_iso_code() -> None:
    # Natural Earth codes Taiwan "CN-TW". Read as a mask code, the hyphen would
    # make it a subdivision of China, and clicks in Taipei would look for
    # Chinese towns.
    from climate.geo.country_parts import natural_earth_iso_code

    assert natural_earth_iso_code({"ISO_A2": "CN-TW", "ISO_A2_EH": "TW"}) == "TW"
    assert natural_earth_iso_code({"ISO_A2": "-99", "ISO_A2_EH": "FR"}) == "FR"
    assert natural_earth_iso_code({"ISO_A2": "-99", "ISO_A2_EH": "-99"}) == ""
