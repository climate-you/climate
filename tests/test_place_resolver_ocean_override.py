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
