from __future__ import annotations

from pathlib import Path

from climate_api.store.location_index import LocationHit, LocationIndex, _norm


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
    assert hit.region_id is None


def _write_index_with_region_ids(path: Path) -> None:
    path.write_text(
        "geonameid,label,lat,lon,country_code,population,norm_label,norm_city,"
        "city_name,kind,bbox,region_id\n"
        '3,"Paris, France",48.8,2.3,FR,2148000,paris france,paris,Paris,city,,\n'
        '2000000001,"North Sea",56.0,3.0,OC,0,north sea,north sea,North Sea,'
        'marine,"-4.0,51.0,12.0,61.0",ocean:north_sea\n'
        '2100000001,"Lake Ontario",43.7,-77.9,LK,0,lake ontario,lake ontario,'
        'Lake Ontario,lake,"-79.0,43.2,-76.0,44.2",\n'
        '2200000001,"France",46.5,2.5,FR,67000000,france,france,France,country,'
        '"-4.0,42.0,8.0,51.0",country:FR\n',
        encoding="utf-8",
    )


def test_region_id_is_read_for_areas_and_absent_elsewhere(tmp_path: Path) -> None:
    index_csv = tmp_path / "locations.index.csv"
    _write_index_with_region_ids(index_csv)
    index = LocationIndex(index_csv, min_query_len=3, prefix_len=3)

    assert index.resolve_by_id(2200000001).region_id == "country:FR"
    assert index.resolve_by_id(2000000001).region_id == "ocean:north_sea"
    # A lake has no mask and so no region; a city never has one.
    assert index.resolve_by_id(2100000001).region_id is None
    assert index.resolve_by_id(3).region_id is None
    # It also survives the autocomplete path, not just direct resolution.
    assert index.autocomplete("france")[0].region_id == "country:FR"


def test_autocomplete_item_gates_region_id_on_release_coverage() -> None:
    """The wire payload must only promise a region the release can serve."""
    from climate_api.main import _autocomplete_item

    index_hit = LocationHit(
        geonameid=2200000001,
        label="France",
        lat=46.5,
        lon=2.5,
        country_code="FR",
        population=0,
        kind="country",
        region_id="country:FR",
    )

    served = _autocomplete_item(index_hit, frozenset({"country:FR", "globe"}))
    assert served.region_id == "country:FR"

    # Same index entry, a release whose aggregates do not cover it: the client
    # is told nothing rather than being sent to an endpoint that would 404.
    not_served = _autocomplete_item(index_hit, frozenset({"globe"}))
    assert not_served.region_id is None
    assert not_served.kind == "country"


def _write_index_with_the(path: Path) -> None:
    path.write_text(
        "geonameid,label,lat,lon,country_code,population,norm_label,norm_city,"
        "city_name,kind,bbox,region_id\n"
        # Big cities whose labels all contain "netherlands".
        '1,"Rotterdam, The Netherlands",51.9,4.5,NL,598199,'
        "rotterdam the netherlands,rotterdam,Rotterdam,city,,\n"
        '2,"The Hague, The Netherlands",52.1,4.3,NL,474292,'
        "the hague the netherlands,the hague,The Hague,city,,\n"
        '2200000001,"The Netherlands",52.2,5.5,NL,17231017,the netherlands,'
        'the netherlands,The Netherlands,country,"3.3,50.7,7.2,53.6",country:NL\n'
        '2000000001,"North Sea",56.0,3.0,OC,0,north sea,north sea,North Sea,'
        'marine,"-4.0,51.0,12.0,61.0",ocean:north_sea\n',
        encoding="utf-8",
    )


def test_a_leading_the_on_the_name_does_not_stop_it_matching(tmp_path: Path) -> None:
    index_csv = tmp_path / "locations.index.csv"
    _write_index_with_the(index_csv)
    index = LocationIndex(index_csv, min_query_len=3, prefix_len=3)

    # GeoNames spells it "The Netherlands"; without this the country was
    # outranked by every city whose label merely contains the word.
    assert index.autocomplete("netherlands")[0].label == "The Netherlands"


def test_a_leading_the_on_the_query_is_ignored(tmp_path: Path) -> None:
    index_csv = tmp_path / "locations.index.csv"
    _write_index_with_the(index_csv)
    index = LocationIndex(index_csv, min_query_len=3, prefix_len=3)

    assert index.autocomplete("the North Sea")[0].label == "North Sea"
    assert index.autocomplete("the netherlands")[0].label == "The Netherlands"
    # A city whose name really begins with "The" is still found.
    assert index.autocomplete("the hague")[0].label == "The Hague, The Netherlands"


def _write_index_for_prefixes(path: Path) -> None:
    rows = [
        # geonameid, label, cc, population, city name, kind
        (1, "Lagos, Nigeria", "NG", 9000000, "Lagos", "city"),
        (2, "Berlin, Germany", "DE", 3400000, "Berlin", "city"),
        (3, "Paris, France", "FR", 2100000, "Paris", "city"),
        (4, "Marseille, France", "FR", 870000, "Marseille", "city"),
        (5, "Asunción, Paraguay", "PY", 520000, "Asunción", "city"),
        (6, "Frankfurt, Germany", "DE", 750000, "Frankfurt", "city"),
        (2200000001, "Nigeria", "NG", 196000000, "Nigeria", "country"),
        (2200000002, "Germany", "DE", 83000000, "Germany", "country"),
        (2200000003, "France", "FR", 67000000, "France", "country"),
        (2200000004, "Paraguay", "PY", 6900000, "Paraguay", "country"),
    ]
    lines = [
        "geonameid,label,lat,lon,country_code,population,norm_label,norm_city,city_name,kind"
    ]
    for gid, label, cc, pop, city, kind in rows:
        norm_label = label.lower().replace(",", "").replace("ó", "o")
        norm_city = city.lower().replace("ó", "o")
        lines.append(
            f'{gid},"{label}",0,0,{cc},{pop},{norm_label},{norm_city},{city},{kind}'
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _labels(index: LocationIndex, q: str) -> list[str]:
    return [h.label for h in index.autocomplete(q, limit=10)]


def test_a_country_appears_before_its_name_is_typed_in_full(tmp_path: Path) -> None:
    index_csv = tmp_path / "locations.index.csv"
    _write_index_for_prefixes(index_csv)
    index = LocationIndex(index_csv, min_query_len=3, prefix_len=3)

    # "fran" is in "Paris, France" only through its country suffix; France is
    # what the reader is typing.
    assert _labels(index, "fran")[0] == "France"


def test_a_match_at_a_word_start_beats_one_inside_a_word(tmp_path: Path) -> None:
    index_csv = tmp_path / "locations.index.csv"
    _write_index_for_prefixes(index_csv)
    index = LocationIndex(index_csv, min_query_len=3, prefix_len=3)

    # Germany begins with "ger"; Nigeria merely contains it; the cities match
    # only through their country ("Lagos, Nigeria", "Berlin, Germany").
    # Nigeria's largest city outnumbers Germany's, so population alone would
    # put Nigeria — and Lagos — first.
    labels = _labels(index, "ger")
    assert labels[:2] == ["Germany", "Nigeria"]
    assert set(labels[2:]) == {
        "Lagos, Nigeria",
        "Berlin, Germany",
        "Frankfurt, Germany",
    }


def test_a_country_ranks_by_its_largest_city_not_its_own_population(
    tmp_path: Path,
) -> None:
    index_csv = tmp_path / "locations.index.csv"
    _write_index_for_prefixes(index_csv)
    index = LocationIndex(index_csv, min_query_len=3, prefix_len=3)

    # Paraguay's 6.9 M would outrank Paris; its largest city (Asunción) does
    # not — but it still makes the list, which zero would not.
    labels = _labels(index, "par")
    assert labels[0] == "Paris, France"
    assert "Paraguay" in labels


def test_a_state_ranks_by_its_largest_town(tmp_path: Path) -> None:
    # The build gives a state entry its largest town's population (Anchorage,
    # 290k); ranked at zero, Alaska would sink below every "Ala…" town.
    index_csv = tmp_path / "locations.index.csv"
    index_csv.write_text(
        "geonameid,label,lat,lon,country_code,population,norm_label,norm_city,"
        "city_name,kind\n"
        '1,"Alassio, Italy",0,0,IT,11000,alassio italy,alassio,Alassio,city\n'
        '2,"Alaşehir, Turkey",0,0,TR,50000,alasehir turkey,alasehir,Alaşehir,city\n'
        "2300000009,Alaska,0,0,US,289600,alaska,alaska,Alaska,state\n",
        encoding="utf-8",
    )
    index = LocationIndex(index_csv, min_query_len=3, prefix_len=3)
    assert _labels(index, "alas")[0] == "Alaska"


def _write_index_with_namesake_waters(path: Path) -> None:
    path.write_text(
        "geonameid,label,lat,lon,country_code,population,norm_label,norm_city,"
        "city_name,kind,bbox,region_id\n"
        '1,"San Francisco CA, USA",37.8,-122.4,US,827526,'
        "san francisco ca usa,san francisco,San Francisco,city,,\n"
        '2,"North Stamford CT, USA",41.1,-73.5,US,121230,'
        "north stamford ct usa,north stamford,North Stamford,city,,\n"
        '2000000001,"San Francisco Bay",37.7,-122.3,OC,0,san francisco bay,'
        'san francisco bay,San Francisco Bay,marine,"-122.5,37.4,-122.0,38.1",\n'
        '2000000002,"North Sea",56.0,3.0,OC,0,north sea,north sea,North Sea,'
        'marine,"-4.0,51.0,12.0,61.0",ocean:north_sea\n',
        encoding="utf-8",
    )


def test_a_major_city_beats_the_water_named_after_it(tmp_path: Path) -> None:
    index_csv = tmp_path / "locations.index.csv"
    _write_index_with_namesake_waters(index_csv)
    index = LocationIndex(index_csv, min_query_len=3, prefix_len=3)

    # Still typing the city's name: the city, then its bay.
    assert _labels(index, "san francis")[:2] == [
        "San Francisco CA, USA",
        "San Francisco Bay",
    ]


def test_a_partly_named_sea_still_beats_a_town(tmp_path: Path) -> None:
    index_csv = tmp_path / "locations.index.csv"
    _write_index_with_namesake_waters(index_csv)
    index = LocationIndex(index_csv, min_query_len=3, prefix_len=3)

    # 121 k is a town next to the North Sea; only a major city outranks it.
    assert _labels(index, "north s")[0] == "North Sea"
