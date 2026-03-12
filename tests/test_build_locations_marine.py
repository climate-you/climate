from __future__ import annotations

import csv
import json
from pathlib import Path
import zipfile

import pytest

from scripts.build.build_locations import (
    MARINE_SYNTHETIC_ID_START,
    load_marine_index_rows,
    write_locations_csv,
)


def _write_geonames_zip(path: Path, geonameid: str = "1") -> None:
    # Minimal valid GeoNames row (19 columns) for a single populated place.
    cols = [
        geonameid,  # geonameid
        "Paris",  # name
        "",  # asciiname
        "",  # alternatenames
        "48.85660",  # latitude
        "2.35220",  # longitude
        "P",  # feature class
        "PPLC",  # feature code
        "FR",  # country code
        "",  # cc2
        "",  # admin1
        "",  # admin2
        "",  # admin3
        "",  # admin4
        "2148000",  # population
        "",  # elevation
        "",  # dem
        "Europe/Paris",  # timezone
        "2020-01-01",  # modification date
    ]
    line = "\t".join(cols) + "\n"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("allCountries.txt", line)


def _write_marine_geojson(path: Path) -> None:
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "NORTH ATLANTIC OCEAN"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-40.0, 20.0],
                            [-39.0, 20.0],
                            [-39.0, 21.0],
                            [-40.0, 21.0],
                            [-40.0, 20.0],
                        ]
                    ],
                },
            },
            {
                "type": "Feature",
                "properties": {"name": "Barents Sea"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [40.0, 75.0],
                            [41.0, 75.0],
                            [41.0, 76.0],
                            [40.0, 76.0],
                            [40.0, 75.0],
                        ]
                    ],
                },
            },
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_load_marine_index_rows_assigns_stable_ids(tmp_path: Path) -> None:
    pytest.importorskip("fiona")
    marine = tmp_path / "marine.geojson"
    _write_marine_geojson(marine)

    rows = load_marine_index_rows(
        input_path=marine,
        name_field="name",
        existing_ids={MARINE_SYNTHETIC_ID_START},
    )

    assert [r["label"] for r in rows] == ["Barents Sea", "North Atlantic Ocean"]
    assert [int(r["geonameid"]) for r in rows] == [
        MARINE_SYNTHETIC_ID_START + 1,
        MARINE_SYNTHETIC_ID_START + 2,
    ]
    assert all(r["country_code"] == "OC" for r in rows)
    assert all(r["population"] == "0" for r in rows)


def test_write_locations_csv_keeps_city_csv_city_only_and_adds_marine_to_index(
    tmp_path: Path,
) -> None:
    geonames_zip = tmp_path / "cities.zip"
    # Deliberately collide with marine synthetic id start.
    _write_geonames_zip(geonames_zip, geonameid=str(MARINE_SYNTHETIC_ID_START))
    out_csv = tmp_path / "locations.csv"
    index_csv = tmp_path / "locations.index.csv"

    marine_rows = [
        {
            "geonameid": str(MARINE_SYNTHETIC_ID_START),
            "label": "Barents Sea",
            "city_name": "Barents Sea",
            "country_name": "Ocean",
            "country_code": "OC",
            "lat": "75.50000",
            "lon": "40.50000",
            "population": "0",
            "alias_count": 0,
            "feature_code": "MARINE",
        }
    ]

    count, _points = write_locations_csv(
        out_csv=out_csv,
        zip_path=geonames_zip,
        country_names={"FR": "France"},
        admin1_names={},
        admin2_names={},
        excluded_feature_codes=set(),
        collect_points=False,
        index_csv=index_csv,
        marine_index_rows=marine_rows,
    )

    assert count == 1

    with out_csv.open("r", encoding="utf-8", newline="") as f:
        city_rows = list(csv.DictReader(f))
    assert len(city_rows) == 1
    assert city_rows[0]["kind"] == "city"
    assert city_rows[0]["city_name"] == "Paris"

    with index_csv.open("r", encoding="utf-8", newline="") as f:
        index_rows = list(csv.DictReader(f))
    assert len(index_rows) == 2
    labels = {r["label"] for r in index_rows}
    assert labels == {"Paris, France", "Barents Sea"}

    marine = next(r for r in index_rows if r["label"] == "Barents Sea")
    assert int(marine["geonameid"]) == MARINE_SYNTHETIC_ID_START + 1
    assert marine["country_code"] == "OC"
    assert marine["population"] == "0"
