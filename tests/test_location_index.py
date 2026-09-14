from __future__ import annotations

from pathlib import Path

from climate_api.store.location_index import LocationIndex, _norm


def _write_index(path: Path) -> None:
    path.write_text(
        "geonameid,label,lat,lon,country_code,population,norm_label,norm_city,city_name\n"
        '1,"Montréal, Canada",45.5,-73.6,CA,1700000,montreal canada,montreal,Montreal\n'
        '2,"Monaco, Monaco",43.7,7.4,MC,39000,monaco monaco,monaco,Monaco\n'
        '3,"Paris, France",48.8,2.3,FR,2148000,paris france,paris,Paris\n',
        encoding="utf-8",
    )


def _write_index_with_marine(path: Path) -> None:
    path.write_text(
        "geonameid,label,lat,lon,country_code,population,norm_label,norm_city,city_name\n"
        '1,"Montréal, Canada",45.5,-73.6,CA,1700000,montreal canada,montreal,Montreal\n'
        '2000000001,"Barents Sea",75.5,40.5,OC,0,barents sea,barents sea,Barents Sea\n',
        encoding="utf-8",
    )


def test_norm_strips_accents_and_punctuation() -> None:
    assert _norm(" Montréal!! ") == "montreal"


def test_autocomplete_and_resolve(tmp_path: Path) -> None:
    index_csv = tmp_path / "locations.index.csv"
    _write_index(index_csv)
    index = LocationIndex(index_csv, min_query_len=2, prefix_len=2)

    hits = index.autocomplete("mo", limit=5)
    assert [h.geonameid for h in hits] == [1, 2]
    assert index.resolve_by_id(3).label == "Paris, France"
    assert index.resolve_by_id(99999) is None
    assert index.resolve_by_label("paris france").geonameid == 3
    assert index.resolve_by_label("") is None


def test_missing_index_file_raises(tmp_path: Path) -> None:
    missing = tmp_path / "missing.csv"
    try:
        LocationIndex(missing)
    except FileNotFoundError as exc:
        assert "Location index not found" in str(exc)
    else:
        raise AssertionError("Expected FileNotFoundError for missing index file.")


def test_autocomplete_and_resolve_support_marine_entries(tmp_path: Path) -> None:
    index_csv = tmp_path / "locations.index.csv"
    _write_index_with_marine(index_csv)
    index = LocationIndex(index_csv, min_query_len=2, prefix_len=2)

    hits = index.autocomplete("sea", limit=5)
    assert [h.label for h in hits] == ["Barents Sea"]
    assert index.resolve_by_id(2000000001).label == "Barents Sea"


def _write_index_with_areas(path: Path) -> None:
    path.write_text(
        "geonameid,label,lat,lon,country_code,population,norm_label,norm_city,"
        "city_name,kind,bbox\n"
        # A village sharing its name with a sea, and far more populous than the
        # sea's stored population of zero.
        '1,"North Sea NY, USA",40.9,-72.4,US,4300,north sea ny usa,north sea,'
        "North Sea,city,\n"
        '2,"Paris, France",48.8,2.3,FR,2148000,paris france,paris,Paris,city,\n'
        '3,"Paraguari, Paraguay",-25.6,-57.1,PY,22154,paraguari paraguay,'
        "paraguari,Paraguari,city,\n"
        '2000000001,"North Sea",56.0,3.0,OC,0,north sea,north sea,North Sea,'
        'marine,"-4.00000,51.00000,12.00000,61.00000"\n'
        '2100000001,"Lake Ontario",43.7,-77.9,LK,0,lake ontario,lake ontario,'
        'Lake Ontario,lake,"-79.00000,43.20000,-76.00000,44.20000"\n'
        '2200000001,"France",46.5,2.5,FR,67000000,france,france,France,country,'
        '"-4.00000,42.00000,8.00000,51.00000"\n'
        '2200000002,"Paraguay",-23.2,-58.4,PY,6900000,paraguay,paraguay,'
        'Paraguay,country,"-62.00000,-27.00000,-54.00000,-19.00000"\n',
        encoding="utf-8",
    )


def test_named_area_outranks_a_same_named_city(tmp_path: Path) -> None:
    index_csv = tmp_path / "locations.index.csv"
    _write_index_with_areas(index_csv)
    index = LocationIndex(index_csv, min_query_len=3, prefix_len=3)

    # The sea, not the Long Island village that is the more populous of the two.
    assert [h.label for h in index.autocomplete("north sea")] == [
        "North Sea",
        "North Sea NY, USA",
    ]
    assert [h.label for h in index.autocomplete("lake ontario")] == ["Lake Ontario"]
    assert index.autocomplete("france")[0].label == "France"


def test_partial_area_name_wins_only_once_the_query_is_multi_word(
    tmp_path: Path,
) -> None:
    index_csv = tmp_path / "locations.index.csv"
    _write_index_with_areas(index_csv)
    index = LocationIndex(index_csv, min_query_len=3, prefix_len=3)

    # A bare prefix keeps the familiar population ordering, so "par" still means
    # Paris rather than Paraguay.
    assert index.autocomplete("par")[0].label == "Paris, France"
    # Two words read as naming an area, so a half-typed one surfaces.
    assert index.autocomplete("lake onta")[0].label == "Lake Ontario"


def test_autocomplete_exposes_kind_and_bbox(tmp_path: Path) -> None:
    index_csv = tmp_path / "locations.index.csv"
    _write_index_with_areas(index_csv)
    index = LocationIndex(index_csv, min_query_len=3, prefix_len=3)

    lake = index.autocomplete("lake ontario")[0]
    assert lake.kind == "lake"
    assert lake.bbox == (-79.0, 43.2, -76.0, 44.2)

    city = index.autocomplete("paris")[0]
    assert city.kind == "city"
    assert city.bbox is None


def test_name_resolution_and_city_rankings_ignore_areas(tmp_path: Path) -> None:
    index_csv = tmp_path / "locations.index.csv"
    _write_index_with_areas(index_csv)
    index = LocationIndex(index_csv, min_query_len=3, prefix_len=3)

    # A country's population dwarfs any city's, but it must not displace one as
    # the owner of a shared name, nor appear in a ranking of cities.
    assert index.resolve_by_any_name("north sea").label == "North Sea NY, USA"
    assert {h.label for h in index.iter_all()} == {
        "North Sea NY, USA",
        "Paris, France",
        "Paraguari, Paraguay",
    }


def test_index_without_kind_or_bbox_columns_reads_as_cities(tmp_path: Path) -> None:
    index_csv = tmp_path / "locations.index.csv"
    _write_index(index_csv)
    index = LocationIndex(index_csv, min_query_len=2, prefix_len=2)

    hit = index.resolve_by_id(3)
    assert hit.kind == "city"
    assert hit.bbox is None
