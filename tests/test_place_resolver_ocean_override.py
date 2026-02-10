from __future__ import annotations

from pathlib import Path

from apps.api.climate_api.store.ocean_classifier import OceanHit
from apps.api.climate_api.store.place_resolver import PlaceResolver


class _AlwaysOcean:
    def classify(self, lat: float, lon: float) -> OceanHit:
        return OceanHit(in_water=True, ocean_id=3, ocean_name="North Atlantic Ocean")


def _write_locations_csv(path: Path) -> None:
    path.write_text(
        "geonameid,lat,lon,label\n"
        '3372562,37.83333,-25.15000,"Nordeste, Portugal"\n',
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
