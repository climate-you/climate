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
