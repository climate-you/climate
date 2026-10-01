from __future__ import annotations

import csv
import json
from pathlib import Path
import zipfile

import pytest

from scripts.build.build_locations import (
    COUNTRY_SYNTHETIC_ID_START,
    LAKE_SYNTHETIC_ID_START,
    MARINE_SYNTHETIC_ID_START,
    load_country_index_rows,
    load_lake_index_rows,
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
    # Seas map onto the ocean regions in the aggregates, slug and all.
    assert [r["region_id"] for r in rows] == [
        "ocean:barents_sea",
        "ocean:north_atlantic_ocean",
    ]


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
            "kind": "marine",
            "bbox": "40.00000,75.00000,41.00000,76.00000",
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
        area_index_rows=marine_rows,
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
    assert marine["kind"] == "marine"
    assert marine["bbox"] == "40.00000,75.00000,41.00000,76.00000"

    city = next(r for r in index_rows if r["label"] == "Paris, France")
    assert city["kind"] == "city"
    assert city["bbox"] == ""


def _write_lake_geojson(path: Path) -> None:
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "Lake Ontario"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-79.0, 43.2],
                            [-76.0, 43.2],
                            [-76.0, 44.2],
                            [-79.0, 44.2],
                            [-79.0, 43.2],
                        ]
                    ],
                },
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_countries_geojson(path: Path) -> None:
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "ISO_A2": "FR",
                    "LABEL_X": 2.5,
                    "LABEL_Y": 46.5,
                },
                # Mainland plus a far-flung territory, as Natural Earth files
                # French Guiana under France.
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [
                        [
                            [
                                [-4.0, 42.0],
                                [8.0, 42.0],
                                [8.0, 51.0],
                                [-4.0, 51.0],
                                [-4.0, 42.0],
                            ]
                        ],
                        [
                            [
                                [-54.0, 2.0],
                                [-52.0, 2.0],
                                [-52.0, 6.0],
                                [-54.0, 6.0],
                                [-54.0, 2.0],
                            ]
                        ],
                    ],
                },
            },
            {
                # Straddles the antimeridian, as Russia and Fiji do.
                "type": "Feature",
                "properties": {"ISO_A2": "FJ"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [178.0, -18.0],
                            [-179.0, -18.0],
                            [-179.0, -17.0],
                            [178.0, -17.0],
                            [178.0, -18.0],
                        ]
                    ],
                },
            },
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_load_lake_index_rows(tmp_path: Path) -> None:
    pytest.importorskip("fiona")
    lakes = tmp_path / "lakes.geojson"
    _write_lake_geojson(lakes)

    rows = load_lake_index_rows(input_path=lakes, name_field="name", existing_ids=set())

    assert len(rows) == 1
    row = rows[0]
    assert row["label"] == "Lake Ontario"
    assert row["kind"] == "lake"
    assert row["country_code"] == "LK"
    assert int(row["geonameid"]) == LAKE_SYNTHETIC_ID_START
    assert row["bbox"] == "-79.00000,43.20000,-76.00000,44.20000"
    # No lake mask exists, so a lake points at no aggregate region.
    assert row["region_id"] == ""


def test_load_country_index_rows_uses_label_point_and_mainland_bbox(
    tmp_path: Path,
) -> None:
    pytest.importorskip("fiona")
    countries = tmp_path / "countries.geojson"
    _write_countries_geojson(countries)

    rows = load_country_index_rows(
        input_path=countries,
        country_names={"FR": "France", "FJ": "Fiji"},
        country_populations={"FR": 67000000, "FJ": 900000},
    )

    by_code = {r["country_code"]: r for r in rows}
    assert set(by_code) == {"FR", "FJ"}

    france = by_code["FR"]
    assert france["label"] == "France"
    assert france["kind"] == "country"
    assert france["population"] == "67000000"
    assert int(france["geonameid"]) >= COUNTRY_SYNTHETIC_ID_START
    # The hand-placed label point, not the centroid of mainland + French Guiana.
    assert (float(france["lat"]), float(france["lon"])) == (46.5, 2.5)
    # The mainland box, not one stretched across the Atlantic.
    assert france["bbox"] == "-4.00000,42.00000,8.00000,51.00000"
    assert france["region_id"] == "country:FR"
    assert by_code["FJ"]["region_id"] == "country:FJ"

    # A box across the antimeridian stays narrow, with east running past 180.
    assert by_code["FJ"]["bbox"] == "178.00000,-18.00000,181.00000,-17.00000"


def test_load_country_index_rows_skips_countries_geonames_does_not_name(
    tmp_path: Path,
) -> None:
    pytest.importorskip("fiona")
    countries = tmp_path / "countries.geojson"
    _write_countries_geojson(countries)

    rows = load_country_index_rows(
        input_path=countries,
        country_names={"FR": "France"},
        country_populations={},
    )

    assert [r["country_code"] for r in rows] == ["FR"]
    assert rows[0]["population"] == "0"
