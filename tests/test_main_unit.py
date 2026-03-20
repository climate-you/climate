from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from climate_api.config import Settings
from climate_api.main import _configure_uvicorn_like_access_logger, create_app
from climate_api.schemas import (
    GraphPayload,
    LocationInfo,
    PanelListResponse,
    PanelPayload,
    PanelResponse,
    PlaceInfo,
    QueryPoint,
    ScoredPanelPayload,
)


async def _asgi_get(
    app: Any, path: str, query: dict[str, Any] | None = None
) -> tuple[int, dict, dict]:
    import urllib.parse

    status: int | None = None
    body_chunks: list[bytes] = []
    headers: dict[str, str] = {}
    query_string = urllib.parse.urlencode(query or {}).encode("utf-8")

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": query_string,
        "headers": [(b"host", b"testserver")],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }

    sent_once = False

    async def receive() -> dict[str, Any]:
        nonlocal sent_once
        if not sent_once:
            sent_once = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await asyncio.sleep(0)
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        nonlocal status
        if message["type"] == "http.response.start":
            status = int(message["status"])
            headers.update(
                {
                    k.decode("latin1"): v.decode("latin1")
                    for k, v in message.get("headers", [])
                }
            )
        elif message["type"] == "http.response.body":
            body_chunks.append(message.get("body", b""))

    await app(scope, receive, send)
    if status is None:
        raise AssertionError("ASGI response missing status.")
    body = b"".join(body_chunks)
    payload: dict[str, Any] = {}
    if body:
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            payload = {}
    return status, payload, headers


def test_create_app_routes_with_mocked_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset_dir = tmp_path / "releases" / "dev" / "maps"
    asset_dir.mkdir(parents=True)
    asset_file = asset_dir / "sample.txt"
    asset_file.write_text("ok", encoding="utf-8")

    settings = Settings(
        release="latest",
        releases_root=tmp_path / "releases",
        latest_release_file=tmp_path / "releases" / "LATEST",
        locations_csv=tmp_path / "locations.csv",
        kdtree_path=None,
        locations_index_csv=tmp_path / "locations.index.csv",
        ocean_mask_npz=None,
        ocean_names_json=None,
        ocean_off_city_max_km=80.0,
        ocean_city_override_max_km=2.0,
        country_mask_npz=None,
        country_codes_json=None,
        country_names_json=None,
        country_constrained_max_km=100.0,
        redis_url=None,
        ttl_resolve_s=60,
        ttl_panel_s=60,
        score_map_preload=False,
        cors_allow_origins=["*"],
        cors_allow_credentials=False,
        rate_limit_enabled=True,
        rate_limit_sustained_rps=5,
        rate_limit_burst=20,
        rate_limit_window_s=10,
    )

    monkeypatch.setattr("climate_api.main.load_settings", lambda: settings)

    class _Index:
        def autocomplete(self, q: str, limit: int = 10):
            return [
                SimpleNamespace(
                    geonameid=1,
                    label="A",
                    lat=10.0,
                    lon=20.0,
                    country_code="US",
                    population=1000,
                )
            ]

        def resolve_by_id(self, geonameid: int):
            if int(geonameid) == 1:
                return SimpleNamespace(
                    geonameid=1,
                    label="A",
                    lat=10.0,
                    lon=20.0,
                    country_code="US",
                    population=1000,
                )
            return None

        def resolve_by_label(self, label: str):
            return self.resolve_by_id(1) if label == "A" else None

    monkeypatch.setattr("climate_api.main.LocationIndex", lambda _path: _Index())

    class _PlaceResolver:
        def resolve_place(self, lat: float, lon: float):
            return SimpleNamespace(
                geonameid=2,
                label="Nearest",
                lat=lat,
                lon=lon,
                distance_km=1.2,
                country_code="US",
                population=123,
            )

    monkeypatch.setattr(
        "climate_api.main.PlaceResolver", lambda **kwargs: _PlaceResolver()
    )

    context = SimpleNamespace(
        release="dev",
        release_root=tmp_path / "releases" / "dev",
        tile_store=object(),
        panels_manifest={"panels": {}},
        maps_manifest={"version": "0.1"},
        maps_root=asset_dir,
        layers=[],
    )

    class _ReleaseResolver:
        def __init__(self, settings: Settings, logger: Any):
            pass

        def resolve_release_alias(self, requested_release: str) -> str:
            return "dev" if requested_release == "latest" else requested_release

        def resolve_release_context(self, requested_release: str):
            return context

        def release_root(self, canonical_release: str) -> Path:
            return tmp_path / "releases" / canonical_release

    monkeypatch.setattr("climate_api.main.ReleaseResolver", _ReleaseResolver)

    location = LocationInfo(
        query=QueryPoint(lat=10.0, lon=20.0),
        place=PlaceInfo(
            geonameid=1,
            label="A",
            lat=10.0,
            lon=20.0,
            distance_km=0.0,
            country_code="US",
            population=1000,
        ),
        data_cells=[],
        panel_valid_bbox=None,
        panel_cell_indices=None,
    )

    monkeypatch.setattr(
        "climate_api.main.build_scored_panels_tiles_registry",
        lambda **kwargs: PanelListResponse(
            release="dev",
            unit="C",
            location=location,
            panels=[
                ScoredPanelPayload(
                    score=2, panel=PanelPayload(id="p", title="P", graphs=[])
                )
            ],
            series={},
            headlines=[],
        ),
    )
    monkeypatch.setattr(
        "climate_api.main.build_panel_tiles_registry",
        lambda **kwargs: PanelResponse(
            release="dev",
            unit="C",
            location=location,
            panel=PanelPayload(
                id="p",
                title="P",
                graphs=[GraphPayload(id="g1", title="G1", series_keys=[])],
            ),
            series={},
            headlines=[],
        ),
    )

    app = create_app()

    status, data, _ = asyncio.run(_asgi_get(app, "/api/v/latest/release"))
    assert status == 200
    assert data["requested_release"] == "latest"
    assert data["release"] == "dev"
    assert isinstance(data.get("version"), dict)
    assert data["version"]["assets_release"] == "dev"
    assert isinstance(data["version"]["app_version"], str) and bool(
        data["version"]["app_version"]
    )

    status, data, _ = asyncio.run(
        _asgi_get(app, "/api/v/dev/locations/autocomplete", {"q": "ab"})
    )
    assert status == 200
    assert len(data["results"]) == 1

    status, data, _ = asyncio.run(
        _asgi_get(app, "/api/v/dev/locations/resolve", {"geonameid": 1})
    )
    assert status == 200
    assert data["result"]["geonameid"] == 1

    status, data, _ = asyncio.run(_asgi_get(app, "/api/v/dev/locations/resolve"))
    assert status == 400
    assert "Provide geonameid or label" in data["detail"]

    status, data, _ = asyncio.run(
        _asgi_get(app, "/api/v/dev/locations/nearest", {"lat": 0.0, "lon": 529.0})
    )
    assert status == 200
    assert data["query"]["lon"] == pytest.approx(169.0)

    status, data, _ = asyncio.run(
        _asgi_get(
            app,
            "/api/v/dev/location/graphs",
            {"lat": 0.0, "lon": 0.0, "panel_id": "air_temperature"},
        )
    )
    assert status == 200
    assert data["graph_ids"] == ["g1"]

    status, _, headers = asyncio.run(_asgi_get(app, "/assets/v/latest/maps/sample.txt"))
    assert status == 200
    assert headers["cache-control"] == "no-store"

    status, data, _ = asyncio.run(_asgi_get(app, "/healthz"))
    assert status == 200
    assert data["status"] == "ok"


def test_configure_uvicorn_like_access_logger_is_idempotent() -> None:
    _configure_uvicorn_like_access_logger()
    _configure_uvicorn_like_access_logger()


def test_asset_route_cache_variants_and_invalid_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dev_root = tmp_path / "releases" / "dev"
    rel_root = tmp_path / "releases" / "2026-01"
    for root in (dev_root, rel_root):
        (root / "maps").mkdir(parents=True)
        (root / "maps" / "sample.txt").write_text("ok", encoding="utf-8")

    settings = Settings(
        release="latest",
        releases_root=tmp_path / "releases",
        latest_release_file=tmp_path / "releases" / "LATEST",
        locations_csv=tmp_path / "locations.csv",
        kdtree_path=None,
        locations_index_csv=tmp_path / "locations.index.csv",
        ocean_mask_npz=None,
        ocean_names_json=None,
        ocean_off_city_max_km=80.0,
        ocean_city_override_max_km=2.0,
        country_mask_npz=None,
        country_codes_json=None,
        country_names_json=None,
        country_constrained_max_km=100.0,
        redis_url=None,
        ttl_resolve_s=60,
        ttl_panel_s=60,
        score_map_preload=True,
        cors_allow_origins=["*"],
        cors_allow_credentials=False,
        rate_limit_enabled=True,
        rate_limit_sustained_rps=5,
        rate_limit_burst=20,
        rate_limit_window_s=10,
    )
    monkeypatch.setattr("climate_api.main.load_settings", lambda: settings)
    monkeypatch.setattr(
        "climate_api.main.LocationIndex",
        lambda _path: SimpleNamespace(
            autocomplete=lambda q, limit=10: [],
            resolve_by_id=lambda geonameid: None,
            resolve_by_label=lambda label: None,
        ),
    )
    monkeypatch.setattr(
        "climate_api.main.PlaceResolver",
        lambda **kwargs: SimpleNamespace(
            resolve_place=lambda lat, lon: SimpleNamespace(
                geonameid=1,
                label="A",
                lat=lat,
                lon=lon,
                distance_km=0.0,
                country_code="US",
                population=1,
            )
        ),
    )

    class _ReleaseResolver:
        def __init__(self, settings: Settings, logger: Any):
            pass

        def resolve_release_context(self, requested_release: str):
            raise RuntimeError("warmup failure")

        def resolve_release_alias(self, requested_release: str) -> str:
            if requested_release == "latest":
                return "2026-01"
            return requested_release

        def release_root(self, canonical_release: str) -> Path:
            return tmp_path / "releases" / canonical_release

    monkeypatch.setattr("climate_api.main.ReleaseResolver", _ReleaseResolver)

    app = create_app()

    status, _, headers = asyncio.run(_asgi_get(app, "/assets/v/latest/maps/sample.txt"))
    assert status == 200
    assert headers["cache-control"] == "no-store"

    status, _, headers = asyncio.run(_asgi_get(app, "/assets/v/dev/maps/sample.txt"))
    assert status == 200
    assert headers["cache-control"] == "public, max-age=0, must-revalidate"

    status, _, headers = asyncio.run(
        _asgi_get(app, "/assets/v/2026-01/maps/sample.txt")
    )
    assert status == 200
    assert headers["cache-control"] == "public, max-age=31536000, immutable"

    status, data, _ = asyncio.run(_asgi_get(app, "/assets/v/dev/maps/missing.txt"))
    assert status == 404
    assert "Asset not found" in data["detail"]

    status, data, _ = asyncio.run(_asgi_get(app, "/assets/v/dev/../../outside.txt"))
    assert status == 400
    assert "Invalid asset path" in data["detail"]


def test_rate_limit_returns_429_when_window_is_exceeded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(
        release="latest",
        releases_root=tmp_path / "releases",
        latest_release_file=tmp_path / "releases" / "LATEST",
        locations_csv=tmp_path / "locations.csv",
        kdtree_path=None,
        locations_index_csv=tmp_path / "locations.index.csv",
        ocean_mask_npz=None,
        ocean_names_json=None,
        ocean_off_city_max_km=80.0,
        ocean_city_override_max_km=2.0,
        country_mask_npz=None,
        country_codes_json=None,
        country_names_json=None,
        country_constrained_max_km=100.0,
        redis_url=None,
        ttl_resolve_s=60,
        ttl_panel_s=60,
        score_map_preload=False,
        cors_allow_origins=["*"],
        cors_allow_credentials=False,
        rate_limit_enabled=True,
        rate_limit_sustained_rps=0,
        rate_limit_burst=2,
        rate_limit_window_s=10,
    )

    monkeypatch.setattr("climate_api.main.load_settings", lambda: settings)
    monkeypatch.setattr(
        "climate_api.main.LocationIndex",
        lambda _path: SimpleNamespace(
            autocomplete=lambda q, limit=10: [],
            resolve_by_id=lambda geonameid: None,
            resolve_by_label=lambda label: None,
        ),
    )
    monkeypatch.setattr(
        "climate_api.main.PlaceResolver",
        lambda **kwargs: SimpleNamespace(
            resolve_place=lambda lat, lon: SimpleNamespace(
                geonameid=1,
                label="A",
                lat=lat,
                lon=lon,
                distance_km=0.0,
                country_code="US",
                population=1,
            )
        ),
    )

    class _ReleaseResolver:
        def __init__(self, settings: Settings, logger: Any):
            pass

        def resolve_release_context(self, requested_release: str):
            return SimpleNamespace(
                release="dev",
                tile_store=object(),
                panels_manifest={"panels": {}},
                maps_manifest={"version": "0.1"},
                maps_root=tmp_path / "releases" / "dev",
                layers=[],
            )

        def resolve_release_alias(self, requested_release: str) -> str:
            return "dev"

        def release_root(self, canonical_release: str) -> Path:
            return tmp_path / "releases" / canonical_release

    monkeypatch.setattr("climate_api.main.ReleaseResolver", _ReleaseResolver)
    app = create_app()

    first_status, _, _ = asyncio.run(
        _asgi_get(app, "/api/v/dev/locations/autocomplete", {"q": "ab"})
    )
    second_status, _, _ = asyncio.run(
        _asgi_get(app, "/api/v/dev/locations/autocomplete", {"q": "ab"})
    )
    third_status, third_data, third_headers = asyncio.run(
        _asgi_get(app, "/api/v/dev/locations/autocomplete", {"q": "ab"})
    )

    assert first_status == 200
    assert second_status == 200
    assert third_status == 429
    assert "Rate limit exceeded" in third_data["detail"]
    assert third_headers["retry-after"] == "1"
