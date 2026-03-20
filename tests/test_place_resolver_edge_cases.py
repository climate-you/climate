from __future__ import annotations

from pathlib import Path
import pickle

import numpy as np
import pytest

from climate_api.store.ocean_classifier import OceanHit
from climate_api.store.place_resolver import (
    PlaceResolver,
    _haversine_km_pair,
    _haversine_km_vec,
)


class _MemoryCache:
    def __init__(self) -> None:
        self.store: dict[str, dict] = {}
        self.last_set: tuple[str, dict, int] | None = None

    def get_json(self, key: str):
        return self.store.get(key)

    def set_json(self, key: str, obj: dict, ttl_s: int) -> None:
        self.store[key] = obj
        self.last_set = (key, obj, ttl_s)


class _KDTree:
    def __init__(self, index: int = 0) -> None:
        self.n = 1
        self._index = index

    def query(self, point, k=1):
        return 0.0, self._index


class _AlwaysCountry:
    def __init__(self, code: str) -> None:
        self._code = code

    def classify(self, lat: float, lon: float) -> str | None:
        return self._code


class _AlwaysLand:
    def classify(self, lat: float, lon: float) -> OceanHit:
        return OceanHit(in_water=False, ocean_id=0, ocean_name=None)


class _WaterNoName:
    def classify(self, lat: float, lon: float) -> OceanHit:
        return OceanHit(in_water=True, ocean_id=9, ocean_name=None)


def _write_locations(path: Path) -> None:
    path.write_text(
        "geonameid,lat,lon,label,country_code,population,city_name,country_name\n"
        '1,10.0,20.0,"City A, US",us,1000,City A,US\n'
        '2,11.0,21.0,"",,0,City B,US\n',
        encoding="utf-8",
    )


def test_haversine_helpers_agree_for_single_point() -> None:
    pair = _haversine_km_pair(0.0, 0.0, 0.0, 1.0)
    vec = _haversine_km_vec(0.0, 0.0, np.array([0.0]), np.array([1.0]))[0]
    assert pair == pytest.approx(vec, rel=1e-6)


def test_place_resolver_requires_columns(tmp_path: Path) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text("geonameid,lat\n1,10\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required column"):
        PlaceResolver(locations_csv=bad)


def test_place_resolver_cache_hit_and_set(tmp_path: Path) -> None:
    csv_path = tmp_path / "locations.csv"
    _write_locations(csv_path)
    cache = _MemoryCache()
    cache.store["place:10.0:20.0"] = {
        "geonameid": 99,
        "label": "From Cache",
        "lat": 1.0,
        "lon": 2.0,
        "distance_km": 3.0,
        "country_code": "us",
        "population": 7,
    }
    resolver = PlaceResolver(locations_csv=csv_path, cache=cache, round_decimals=1)
    place = resolver.resolve_place(10.0, 20.0)
    assert place.geonameid == 99
    assert place.country_code == "US"

    cache.store.clear()
    place2 = resolver.resolve_place(10.01, 20.04)
    assert place2.geonameid in {1, 2}
    assert cache.last_set is not None
    assert cache.last_set[0].startswith("place:10.0:20.0")


def test_place_resolver_kdtree_paths(tmp_path: Path) -> None:
    csv_path = tmp_path / "locations.csv"
    _write_locations(csv_path)
    kdtree_file = tmp_path / "tree.pkl"
    with open(kdtree_file, "wb") as f:
        pickle.dump(_KDTree(index=0), f)

    # No ocean classifier: KD-tree path computes accurate distance via pair helper.
    resolver = PlaceResolver(
        locations_csv=csv_path, kdtree_path=kdtree_file, cache=None
    )
    place = resolver.resolve_place(10.1, 20.1)
    assert place.distance_km > 0.0

    # With land classifier: KD-tree branch shortcuts distance to 0 for performance.
    resolver_land = PlaceResolver(
        locations_csv=csv_path,
        kdtree_path=kdtree_file,
        ocean_classifier=_AlwaysLand(),
        cache=None,
    )
    place_land = resolver_land.resolve_place(10.1, 20.1)
    assert place_land.distance_km == 0.0

    # Broken KD-tree file falls back to linear scan.
    bad_tree = tmp_path / "broken.pkl"
    bad_tree.write_bytes(b"not a pickle")
    resolver_fallback = PlaceResolver(
        locations_csv=csv_path, kdtree_path=bad_tree, cache=None
    )
    place_fallback = resolver_fallback.resolve_place(10.1, 20.1)
    assert place_fallback.geonameid in {1, 2}


def test_place_resolver_country_name_fallback_for_no_city_country(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "locations.csv"
    _write_locations(csv_path)
    # "ZZ" is a country code with no cities in the index.
    resolver = PlaceResolver(
        locations_csv=csv_path,
        country_classifier=_AlwaysCountry("ZZ"),
        country_names={"ZZ": "Nowhere Land"},
        cache=None,
    )
    place = resolver.resolve_place(-78.0, 16.0)
    assert place.label == "Nowhere Land"


def test_place_resolver_country_name_fallback_unknown_code_falls_through(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "locations.csv"
    _write_locations(csv_path)
    # "ZZ" has no cities and no entry in country_names → falls through to global search.
    resolver = PlaceResolver(
        locations_csv=csv_path,
        country_classifier=_AlwaysCountry("ZZ"),
        country_names={"AQ": "Antarctica"},
        cache=None,
    )
    place = resolver.resolve_place(-78.0, 16.0)
    assert place.label != "Antarctica"
    assert place.geonameid in {1, 2}


def test_place_resolver_ocean_open_ocean_label_and_city_fallback(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "locations.csv"
    _write_locations(csv_path)
    resolver = PlaceResolver(
        locations_csv=csv_path,
        ocean_classifier=_WaterNoName(),
        ocean_city_override_max_km=0.0,
        ocean_off_city_max_km=1.0,
        cache=None,
    )
    # Far enough from nearest city with unnamed ocean -> "Open Ocean"
    place = resolver.resolve_place(40.0, -120.0)
    assert place.label == "Open Ocean"
    assert place.population is None
