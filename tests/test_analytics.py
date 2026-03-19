from __future__ import annotations

import asyncio
import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from climate_api.analytics.db import AnalyticsDB, snap
from climate_api.analytics.geo import GeoIPCache
from climate_api.config import Settings


# ---------------------------------------------------------------------------
# Helpers shared with test_main_unit.py
# ---------------------------------------------------------------------------


async def _asgi_request(
    app: Any,
    method: str,
    path: str,
    body: bytes = b"",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> tuple[int, dict, dict]:
    import urllib.parse

    status: int | None = None
    body_chunks: list[bytes] = []
    resp_headers: dict[str, str] = {}

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method.upper(),
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "headers": (headers or []) + [(b"host", b"testserver")],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }

    sent_once = False

    async def receive() -> dict[str, Any]:
        nonlocal sent_once
        if not sent_once:
            sent_once = True
            return {"type": "http.request", "body": body, "more_body": False}
        await asyncio.sleep(0)
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        nonlocal status
        if message["type"] == "http.response.start":
            status = int(message["status"])
            resp_headers.update(
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
    raw = b"".join(body_chunks)
    payload: dict[str, Any] = {}
    if raw:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            payload = {}
    return status, payload, resp_headers


async def _asgi_post_json(app: Any, path: str, data: dict) -> tuple[int, dict, dict]:
    body = json.dumps(data).encode("utf-8")
    return await _asgi_request(
        app,
        "POST",
        path,
        body=body,
        headers=[
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
    )


async def _asgi_post(app: Any, path: str) -> tuple[int, dict, dict]:
    return await _asgi_request(app, "POST", path)


async def _asgi_get(app: Any, path: str) -> tuple[int, dict, dict]:
    return await _asgi_request(app, "GET", path)


# ---------------------------------------------------------------------------
# snap()
# ---------------------------------------------------------------------------


def test_snap_click_grid() -> None:
    assert snap(0.0, 0.25) == pytest.approx(0.0)
    assert snap(0.12, 0.25) == pytest.approx(0.0)
    assert snap(0.13, 0.25) == pytest.approx(0.25)
    assert snap(57.3, 0.25) == pytest.approx(57.25)
    assert snap(-20.1, 0.25) == pytest.approx(-20.0)
    assert snap(-20.2, 0.25) == pytest.approx(-20.25)


def test_snap_origin_grid() -> None:
    assert snap(37.7, 1.0) == pytest.approx(38.0)
    assert snap(-95.4, 1.0) == pytest.approx(-95.0)
    assert snap(0.5, 1.0) == pytest.approx(0.0) or snap(0.5, 1.0) == pytest.approx(
        1.0
    )  # banker's rounding tolerance


# ---------------------------------------------------------------------------
# AnalyticsDB
# ---------------------------------------------------------------------------


def test_analytics_db_record_and_query_clicks(tmp_path: Path) -> None:
    db = AnalyticsDB(tmp_path / "events.db")
    db.record_click(57.3, 20.1)
    db.record_click(57.3, 20.1)
    db.record_click(-20.3, 57.4)

    clicks = db.get_click_aggregates()
    assert len(clicks) == 2
    by_lat = {c["lat"]: c for c in clicks}
    # 57.3 -> 57.25, 20.1 -> 20.0
    assert by_lat[57.25]["lon"] == pytest.approx(20.0)
    assert by_lat[57.25]["count"] == 2
    # -20.3 -> -20.25, 57.4 -> 57.5
    assert by_lat[-20.25]["count"] == 1


def test_analytics_db_record_and_query_sessions(tmp_path: Path) -> None:
    db = AnalyticsDB(tmp_path / "events.db")
    db.record_session("US", 37.7, -95.4)
    db.record_session("US", 37.7, -95.4)
    db.record_session("FR", 46.2, 2.2)
    db.record_session(None, None, None)

    origins = db.get_session_aggregates()
    assert len(origins) == 3
    by_country = {o["country"]: o for o in origins}
    assert by_country["US"]["count"] == 2
    assert by_country["FR"]["count"] == 1
    assert by_country[None]["count"] == 1


def test_analytics_db_empty(tmp_path: Path) -> None:
    db = AnalyticsDB(tmp_path / "events.db")
    assert db.get_click_aggregates() == []
    assert db.get_session_aggregates() == []


def test_analytics_db_creates_parent_dirs(tmp_path: Path) -> None:
    db = AnalyticsDB(tmp_path / "deep" / "nested" / "events.db")
    db.record_click(0.0, 0.0)
    assert (tmp_path / "deep" / "nested" / "events.db").exists()


# ---------------------------------------------------------------------------
# GeoIPCache
# ---------------------------------------------------------------------------


def test_geoip_cache_returns_parsed_result() -> None:
    cache = GeoIPCache(ttl_s=3600)
    fake_response = json.dumps(
        {"status": "success", "countryCode": "AU", "lat": -25.0, "lon": 133.0}
    ).encode()

    class _FakeResponse:
        def read(self):
            return fake_response

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    with patch("urllib.request.urlopen", return_value=_FakeResponse()):
        result = cache.lookup("1.2.3.4")

    assert result == ("AU", -25.0, 133.0)


def test_geoip_cache_hit_avoids_second_fetch() -> None:
    cache = GeoIPCache(ttl_s=3600)
    call_count = 0

    fake_response = json.dumps(
        {"status": "success", "countryCode": "DE", "lat": 51.0, "lon": 10.0}
    ).encode()

    class _FakeResponse:
        def read(self):
            nonlocal call_count
            call_count += 1
            return fake_response

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    with patch("urllib.request.urlopen", return_value=_FakeResponse()):
        cache.lookup("5.6.7.8")
        cache.lookup("5.6.7.8")

    assert call_count == 1


def test_geoip_cache_returns_nulls_on_failure() -> None:
    cache = GeoIPCache(ttl_s=3600)
    with patch("urllib.request.urlopen", side_effect=OSError("network error")):
        result = cache.lookup("9.9.9.9")
    assert result == (None, None, None)


def test_geoip_cache_returns_nulls_on_non_success_status() -> None:
    cache = GeoIPCache(ttl_s=3600)
    fake_response = json.dumps({"status": "fail", "message": "private range"}).encode()

    class _FakeResponse:
        def read(self):
            return fake_response

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    with patch("urllib.request.urlopen", return_value=_FakeResponse()):
        result = cache.lookup("192.168.1.1")
    assert result == (None, None, None)


# ---------------------------------------------------------------------------
# API endpoints (via ASGI)
# ---------------------------------------------------------------------------


def _make_settings(tmp_path: Path) -> Settings:
    return Settings(
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
        country_constrained_max_km=100.0,
        redis_url=None,
        ttl_resolve_s=60,
        ttl_panel_s=60,
        score_map_preload=False,
        cors_allow_origins=["*"],
        cors_allow_credentials=False,
        rate_limit_enabled=False,
        rate_limit_sustained_rps=5,
        rate_limit_burst=20,
        rate_limit_window_s=10,
        analytics_db_path=tmp_path / "analytics" / "events.db",
        analytics_enabled=True,
        geoip_cache_ttl_s=3600,
    )


def _make_app(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Any:
    from climate_api.main import create_app

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

    class _RR:
        def __init__(self, settings, logger):
            pass

        def resolve_release_context(self, r):
            raise RuntimeError("not needed in analytics tests")

        def resolve_release_alias(self, r):
            return r

        def release_root(self, r):
            return Path("/tmp")

    monkeypatch.setattr("climate_api.main.ReleaseResolver", _RR)
    return create_app()


def test_post_click_returns_204(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _make_settings(tmp_path)
    app = _make_app(settings, monkeypatch)

    status, _, _ = asyncio.run(
        _asgi_post_json(app, "/api/events/click", {"lat": 10.0, "lon": 20.0})
    )
    assert status == 204

    db = AnalyticsDB(settings.analytics_db_path)
    clicks = db.get_click_aggregates()
    assert len(clicks) == 1
    assert clicks[0]["lat"] == pytest.approx(10.0)
    assert clicks[0]["lon"] == pytest.approx(20.0)


def test_post_session_returns_204(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _make_settings(tmp_path)
    app = _make_app(settings, monkeypatch)

    with patch("climate_api.analytics.geo.GeoIPCache.lookup", return_value=("US", 37.0, -95.0)):
        status, _, _ = asyncio.run(_asgi_post(app, "/api/events/session"))
    assert status == 204

    db = AnalyticsDB(settings.analytics_db_path)
    origins = db.get_session_aggregates()
    assert len(origins) == 1
    assert origins[0]["country"] == "US"


def test_get_admin_events_returns_aggregates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _make_settings(tmp_path)

    db = AnalyticsDB(settings.analytics_db_path)
    db.record_click(10.0, 20.0)
    db.record_click(10.0, 20.0)
    db.record_session("DE", 51.0, 10.0)

    app = _make_app(settings, monkeypatch)

    status, data, _ = asyncio.run(_asgi_get(app, "/api/admin/events"))
    assert status == 200
    assert len(data["clicks"]) == 1
    assert data["clicks"][0]["count"] == 2
    assert len(data["origins"]) == 1
    assert data["origins"][0]["country"] == "DE"


def test_analytics_disabled_skips_recording(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = dataclasses.replace(_make_settings(tmp_path), analytics_enabled=False)
    app = _make_app(settings, monkeypatch)

    status, _, _ = asyncio.run(
        _asgi_post_json(app, "/api/events/click", {"lat": 5.0, "lon": 5.0})
    )
    assert status == 204

    db = AnalyticsDB(settings.analytics_db_path)
    assert db.get_click_aggregates() == []
