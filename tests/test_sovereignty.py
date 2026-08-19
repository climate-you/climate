from __future__ import annotations

from pathlib import Path

from climate_api.store.location_index import LocationIndex
from climate_api.store.sovereignty import is_sovereign


def _write_capitals_index(path: Path) -> None:
    """An index holding sovereign capitals alongside dependency capitals."""
    path.write_text(
        "geonameid,label,lat,lon,country_code,population,norm_label,norm_city,city_name,capital\n"
        '1,"Ulan Bator, Mongolia",47.9,106.9,MN,844818,ulan bator mongolia,ulan bator,Ulan Bator,true\n'
        '2,"Longyearbyen, Svalbard and Jan Mayen",78.2,15.6,SJ,2400,longyearbyen svalbard,longyearbyen,Longyearbyen,true\n'
        '3,"Nuuk, Greenland",64.2,-51.7,GL,17000,nuuk greenland,nuuk,Nuuk,true\n'
        '4,"Oslo, Norway",59.9,10.8,NO,580000,oslo norway,oslo,Oslo,true\n'
        '5,"Bergen, Norway",60.4,5.3,NO,213585,bergen norway,bergen,Bergen,false\n',
        encoding="utf-8",
    )


def test_dependencies_are_not_sovereign() -> None:
    for code in ("SJ", "GL", "PR", "HK", "GI", "YT", "AX", "CK"):
        assert not is_sovereign(code), f"{code} should be non-sovereign"


def test_countries_are_sovereign() -> None:
    for code in ("MN", "NO", "DK", "FR", "US", "VA", "TW", "XK"):
        assert is_sovereign(code), f"{code} should be sovereign"


def test_unknown_code_defaults_to_sovereign() -> None:
    """A gap in the country data must never drop a real capital from a ranking."""
    assert is_sovereign(None)
    assert is_sovereign("")
    assert is_sovereign("ZZ")


def test_code_matching_ignores_case_and_padding() -> None:
    assert not is_sovereign(" sj ")
    assert not is_sovereign("gl")


def test_capitals_only_excludes_dependency_capitals(tmp_path: Path) -> None:
    index_csv = tmp_path / "locations.index.csv"
    _write_capitals_index(index_csv)
    index = LocationIndex(index_csv, min_query_len=2, prefix_len=2)

    labels = {h.label.split(",")[0] for h in index.iter_all(capitals_only=True)}

    assert labels == {"Ulan Bator", "Oslo"}
    # Svalbard and Greenland have capitals, but Norway and Denmark govern them.
    assert "Longyearbyen" not in labels
    assert "Nuuk" not in labels
    # Non-capitals stay excluded as before.
    assert "Bergen" not in labels


def test_iter_all_without_capital_filter_keeps_every_location(tmp_path: Path) -> None:
    index_csv = tmp_path / "locations.index.csv"
    _write_capitals_index(index_csv)
    index = LocationIndex(index_csv, min_query_len=2, prefix_len=2)

    assert len(index.iter_all()) == 5
