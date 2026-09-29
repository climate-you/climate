from __future__ import annotations

from pathlib import Path

from climate_api.store.ocean_classifier import OceanHit
from climate_api.store.place_resolver import PlaceResolver


class _AlwaysOcean:
    def classify(self, lat: float, lon: float) -> OceanHit:
        return OceanHit(in_water=True, ocean_id=3, ocean_name="North Atlantic Ocean")


class _AlwaysCountry:
    def __init__(self, code: str) -> None:
        self._code = code

    def classify(self, lat: float, lon: float) -> str | None:
        return self._code


def _write_locations_csv(path: Path) -> None:
    path.write_text(
        "geonameid,lat,lon,label,population\n"
        '3372562,37.83333,-25.15000,"Nordeste, Portugal",5000\n',
        encoding="utf-8",
    )


def test_city_override_keeps_city_label_when_near_city(tmp_path: Path) -> None:
    csv_path = tmp_path / "locations.csv"
    _write_locations_csv(csv_path)

    resolver = PlaceResolver(
        locations_csv=csv_path,
        ocean_classifier=_AlwaysOcean(),
        ocean_city_override_max_km=5.0,
        ocean_off_city_max_km=80.0,
        cache=None,
    )

    place = resolver.resolve_place(37.83333, -25.15000)
    assert place.label == "Nordeste, Portugal"
    assert place.population is None


def test_country_classifier_overrides_ocean_classifier_for_land(
    tmp_path: Path,
) -> None:
    # Ocean classifier says in_water=True, but country classifier says it's Chile.
    # The country classifier should win — no ocean label applied.
    csv_path = tmp_path / "locations.csv"
    csv_path.write_text(
        "geonameid,lat,lon,label,country_code,population\n"
        '3874960,-53.15,-70.92,"Punta Arenas, Chile",CL,130000\n',
        encoding="utf-8",
    )
    resolver = PlaceResolver(
        locations_csv=csv_path,
        ocean_classifier=_AlwaysOcean(),
        country_classifier=_AlwaysCountry("CL"),
        cache=None,
    )
    place = resolver.resolve_place(-55.84, -67.29)
    assert place.label == "Punta Arenas, Chile"
    assert "Ocean" not in place.label


def test_city_override_allows_ocean_label_when_farther(tmp_path: Path) -> None:
    csv_path = tmp_path / "locations.csv"
    _write_locations_csv(csv_path)

    resolver = PlaceResolver(
        locations_csv=csv_path,
        ocean_classifier=_AlwaysOcean(),
        ocean_city_override_max_km=0.1,
        ocean_off_city_max_km=80.0,
        cache=None,
    )

    place = resolver.resolve_place(37.90000, -25.15000)
    assert place.label.startswith("North Atlantic Ocean")
    assert place.population is None


def test_ocean_label_takes_the_even_with_a_city_appended(tmp_path: Path) -> None:
    csv_path = tmp_path / "locations.csv"
    _write_locations_csv(csv_path)
    resolver = PlaceResolver(
        locations_csv=csv_path,
        ocean_classifier=_AlwaysOcean(),
        ocean_city_override_max_km=0.1,
        ocean_off_city_max_km=80.0,
        cache=None,
    )

    # "the North Atlantic Ocean off Nordeste, Portugal": the water body leads.
    place = resolver.resolve_place(37.90000, -25.15000)
    assert " off " in place.label
    assert place.definite_article is True


def test_city_label_takes_no_article(tmp_path: Path) -> None:
    csv_path = tmp_path / "locations.csv"
    _write_locations_csv(csv_path)
    resolver = PlaceResolver(
        locations_csv=csv_path,
        ocean_classifier=_AlwaysOcean(),
        ocean_city_override_max_km=5.0,
        cache=None,
    )

    place = resolver.resolve_place(37.83333, -25.15000)
    assert place.label == "Nordeste, Portugal"
    assert place.definite_article is False


class _DictCache:
    """In-memory stand-in for the resolver's JSON cache."""

    def __init__(self) -> None:
        self.store: dict = {}

    def get_json(self, key):
        return self.store.get(key)

    def set_json(self, key, value, ttl_s=None) -> None:
        self.store[key] = value


def test_article_survives_the_resolution_cache(tmp_path: Path) -> None:
    csv_path = tmp_path / "locations.csv"
    _write_locations_csv(csv_path)
    cache = _DictCache()
    resolver = PlaceResolver(
        locations_csv=csv_path,
        ocean_classifier=_AlwaysOcean(),
        ocean_city_override_max_km=0.1,
        cache=cache,
    )

    first = resolver.resolve_place(37.90000, -25.15000)
    assert cache.store, "expected the first resolution to be cached"
    second = resolver.resolve_place(37.90000, -25.15000)
    assert second.label == first.label
    assert second.definite_article is True
