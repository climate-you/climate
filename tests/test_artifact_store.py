"""
Unit tests for the v2 artifact-store release system.

Covers:
- TileDataStore.per_metric_roots: tile path and axis resolution
- release.py: v2 manifest loading (per_metric_roots, map_artifact_roots)
- config.py: artifacts_root default derivation
- main.py: get_release_asset for v2 map paths
- scripts/validate/release_manifest.py: v2 validation
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from climate_api.config import Settings, load_settings
from climate_api.store.tile_data_store import TileDataStore
from climate.tiles.layout import GridSpec


# ---------------------------------------------------------------------------
# Config: artifacts_root default
# ---------------------------------------------------------------------------


def test_load_settings_artifacts_root_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """artifacts_root defaults to sibling of releases_root named 'artifacts'."""
    monkeypatch.delenv("ARTIFACTS_ROOT", raising=False)
    monkeypatch.delenv("RELEASES_ROOT", raising=False)
    monkeypatch.delenv("REPO_ROOT", raising=False)
    settings = load_settings()
    assert settings.artifacts_root is not None
    assert settings.artifacts_root.name == "artifacts"
    assert settings.artifacts_root.parent == settings.releases_root.parent


def test_load_settings_artifacts_root_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """ARTIFACTS_ROOT env var overrides the default."""
    custom = tmp_path / "custom_artifacts"
    monkeypatch.setenv("ARTIFACTS_ROOT", str(custom))
    settings = load_settings()
    assert settings.artifacts_root == custom


# ---------------------------------------------------------------------------
# TileDataStore: per_metric_roots
# ---------------------------------------------------------------------------


def _make_grid() -> GridSpec:
    return GridSpec.global_0p25(tile_size=64)


def test_per_metric_roots_tile_path(tmp_path: Path) -> None:
    """_metric_tile_path uses per_metric_root when set."""
    grid = _make_grid()
    artifact_root = tmp_path / "artifacts" / "series" / "t2m_annual" / "2026_04_01"
    artifact_root.mkdir(parents=True)

    store = TileDataStore(
        tiles_root=tmp_path / "series",
        grid=grid,
        per_metric_roots={"t2m_annual": artifact_root},
    )

    path = store._metric_tile_path("t2m_annual", 2, 14)
    assert path == artifact_root / "z64" / "r002_c014.bin.zst"


def test_per_metric_roots_fallback_to_tiles_root(tmp_path: Path) -> None:
    """Metrics not in per_metric_roots use tiles_root as before."""
    grid = _make_grid()
    tiles_root = tmp_path / "series"
    tiles_root.mkdir()

    store = TileDataStore(
        tiles_root=tiles_root,
        grid=grid,
        per_metric_roots={},  # empty
    )

    path = store._metric_tile_path("t2m_annual", 2, 14)
    assert (
        path == tiles_root / "global_0p25" / "t2m_annual" / "z64" / "r002_c014.bin.zst"
    )


def test_per_metric_roots_axis(tmp_path: Path) -> None:
    """axis() reads from per_metric_root/time/ when set."""
    grid = _make_grid()
    artifact_root = tmp_path / "art"
    (artifact_root / "time").mkdir(parents=True)
    (artifact_root / "time" / "yearly.json").write_text(
        json.dumps([2000, 2001, 2002]), encoding="utf-8"
    )

    store = TileDataStore(
        tiles_root=tmp_path / "series",
        grid=grid,
        per_metric_roots={"t2m_annual": artifact_root},
    )

    axis = store.axis("t2m_annual")
    assert axis == [2000, 2001, 2002]


def test_per_metric_roots_axis_missing_returns_empty(tmp_path: Path) -> None:
    """axis() returns [] when time/ file is missing in artifact root."""
    grid = _make_grid()
    artifact_root = tmp_path / "art"
    artifact_root.mkdir()

    store = TileDataStore(
        tiles_root=tmp_path / "series",
        grid=grid,
        per_metric_roots={"t2m_annual": artifact_root},
    )

    assert store.axis("t2m_annual") == []


# ---------------------------------------------------------------------------
# release.py: ReleaseContext v2 fields default
# ---------------------------------------------------------------------------


def test_release_context_v2_defaults() -> None:
    """ReleaseContext format_version defaults to 1, map_artifact_roots to {}."""
    from climate_api.release import ReleaseContext

    ctx = ReleaseContext(
        release="dev",
        release_root=Path("."),
        tile_store=None,  # type: ignore[arg-type]
        panels_manifest={},
        maps_manifest={},
        maps_root=Path("."),
        layers=[],
    )
    assert ctx.format_version == 1
    assert ctx.map_artifact_roots == {}


# ---------------------------------------------------------------------------
# scripts/validate/release_manifest.py: v2 validation
# ---------------------------------------------------------------------------


def _write_registry(release_dir: Path) -> None:
    registry_dir = release_dir / "registry"
    registry_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "metrics.json",
        "datasets.json",
        "maps.json",
        "panels.json",
        "layers.json",
    ):
        (registry_dir / name).write_text("{}", encoding="utf-8")


def _write_artifact_manifest(artifact_dir: Path, info: dict) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / ".artifact_manifest.json").write_text(
        json.dumps(info), encoding="utf-8"
    )


def test_validate_v2_manifest_ok(tmp_path: Path) -> None:
    """v2 manifest validation passes when all artifact dirs and manifests exist."""
    import subprocess, sys

    releases_root = tmp_path / "releases"
    artifacts_root = tmp_path / "artifacts"

    release_id = "2026_04_01"
    release_dir = releases_root / release_id
    _write_registry(release_dir)

    # Create artifact dirs
    series_art = artifacts_root / "series" / "t2m_annual" / "2026_04_01"
    _write_artifact_manifest(
        series_art, {"metric_id": "t2m_annual", "artifact_date": "2026_04_01"}
    )
    map_art = artifacts_root / "maps" / "t2m_mean_map" / "2026_04_01"
    _write_artifact_manifest(
        map_art, {"map_id": "t2m_mean_map", "artifact_date": "2026_04_01"}
    )

    manifest = {
        "release": release_id,
        "format_version": 2,
        "created_at_utc": "2026-04-01T10:00:00Z",
        "registry": {
            "metrics.json": "registry/metrics.json",
            "datasets.json": "registry/datasets.json",
            "maps.json": "registry/maps.json",
            "panels.json": "registry/panels.json",
            "layers.json": "registry/layers.json",
        },
        "series": {"t2m_annual": "2026_04_01"},
        "maps": {"t2m_mean_map": "2026_04_01"},
    }
    (release_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/validate/release_manifest.py",
            "--release",
            release_id,
            "--releases-root",
            str(releases_root),
            "--artifacts-root",
            str(artifacts_root),
        ],
        capture_output=True,
        text=True,
        cwd=(
            str(tmp_path.parent.parent)  # run from repo root equivalent
            if False
            else None
        ),
    )
    # We just invoke the function directly instead of subprocess to avoid cwd issues
    from scripts.validate.release_manifest import main as validate_main
    import sys as _sys

    orig_argv = _sys.argv
    _sys.argv = [
        "release_manifest.py",
        "--release",
        release_id,
        "--releases-root",
        str(releases_root),
        "--artifacts-root",
        str(artifacts_root),
    ]
    try:
        rc = validate_main()
    finally:
        _sys.argv = orig_argv
    assert rc == 0


def test_validate_v2_manifest_missing_artifact(tmp_path: Path) -> None:
    """v2 manifest validation fails when artifact dir is missing."""
    from scripts.validate.release_manifest import main as validate_main
    import sys as _sys

    releases_root = tmp_path / "releases"
    artifacts_root = tmp_path / "artifacts"

    release_id = "2026_04_01"
    release_dir = releases_root / release_id
    _write_registry(release_dir)
    # No artifact dirs created

    manifest = {
        "release": release_id,
        "format_version": 2,
        "created_at_utc": "2026-04-01T10:00:00Z",
        "registry": {
            "metrics.json": "registry/metrics.json",
            "datasets.json": "registry/datasets.json",
            "maps.json": "registry/maps.json",
            "panels.json": "registry/panels.json",
            "layers.json": "registry/layers.json",
        },
        "series": {"t2m_annual": "2026_04_01"},
        "maps": {},
    }
    (release_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    orig_argv = _sys.argv
    _sys.argv = [
        "release_manifest.py",
        "--release",
        release_id,
        "--releases-root",
        str(releases_root),
        "--artifacts-root",
        str(artifacts_root),
    ]
    try:
        rc = validate_main()
    finally:
        _sys.argv = orig_argv
    assert rc == 1


def test_validate_v2_manifest_missing_artifact_manifest(tmp_path: Path) -> None:
    """v2 validation fails when artifact dir exists but manifest.json is missing (incomplete build)."""
    from scripts.validate.release_manifest import main as validate_main
    import sys as _sys

    releases_root = tmp_path / "releases"
    artifacts_root = tmp_path / "artifacts"

    release_id = "2026_04_01"
    release_dir = releases_root / release_id
    _write_registry(release_dir)

    # Artifact dir exists but no manifest.json
    series_art = artifacts_root / "series" / "t2m_annual" / "2026_04_01"
    series_art.mkdir(parents=True)

    manifest = {
        "release": release_id,
        "format_version": 2,
        "created_at_utc": "2026-04-01T10:00:00Z",
        "registry": {
            "metrics.json": "registry/metrics.json",
            "datasets.json": "registry/datasets.json",
            "maps.json": "registry/maps.json",
            "panels.json": "registry/panels.json",
        },
        "series": {"t2m_annual": "2026_04_01"},
        "maps": {},
    }
    (release_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    orig_argv = _sys.argv
    _sys.argv = [
        "release_manifest.py",
        "--release",
        release_id,
        "--releases-root",
        str(releases_root),
        "--artifacts-root",
        str(artifacts_root),
    ]
    try:
        rc = validate_main()
    finally:
        _sys.argv = orig_argv
    assert rc == 1


# ---------------------------------------------------------------------------
# main.py: v2 map asset serving via get_release_asset
# ---------------------------------------------------------------------------


async def _asgi_get(app: Any, path: str) -> tuple[int, dict, dict]:
    import urllib.parse
    import json as _json

    status = None
    body_chunks: list[bytes] = []
    headers: dict[str, str] = {}

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "headers": [(b"host", b"testserver")],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }

    sent_once = False

    async def receive():
        nonlocal sent_once
        if not sent_once:
            sent_once = True
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
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
    payload: dict = {}
    if body:
        try:
            payload = _json.loads(body.decode("utf-8"))
        except Exception:
            payload = {}
    return status, payload, headers


def test_v2_release_asset_served_from_artifact_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """get_release_asset resolves v2 map paths from map_artifact_roots."""
    from climate_api.config import Settings
    from climate_api.main import create_app
    from climate_api.release import ReleaseContext
    from climate_api.store.tile_data_store import TileDataStore

    # Create a map file in the artifact store
    artifact_map_dir = tmp_path / "artifacts" / "maps" / "t2m_mean_map" / "2026_04_01"
    artifact_map_dir.mkdir(parents=True)
    (artifact_map_dir / "t2m_mean.png").write_bytes(b"fake-png-data")

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
        rate_limit_enabled=False,
        rate_limit_sustained_rps=5,
        rate_limit_burst=20,
        rate_limit_window_s=10,
        artifacts_root=tmp_path / "artifacts",
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

    # Build a v2 release context with map_artifact_roots
    tile_store = TileDataStore(
        tiles_root=tmp_path / "series",
        grid=GridSpec.global_0p25(),
    )
    v2_context = ReleaseContext(
        release="2026_04_01",
        release_root=tmp_path / "releases" / "2026_04_01",
        tile_store=tile_store,
        panels_manifest={},
        maps_manifest={},
        maps_root=tmp_path / "releases" / "2026_04_01" / "maps",
        layers=[],
        format_version=2,
        map_artifact_roots={"t2m_mean_map": artifact_map_dir},
    )

    class _MockReleaseResolver:
        def __init__(self, settings: Settings, logger: Any):
            pass

        def resolve_release_alias(self, requested: str) -> str:
            return "2026_04_01" if requested == "latest" else requested

        def resolve_release_context(self, release: str):
            return v2_context

        def release_root(self, release: str) -> Path:
            p = tmp_path / "releases" / release
            p.mkdir(parents=True, exist_ok=True)
            return p

    monkeypatch.setattr("climate_api.main.ReleaseResolver", _MockReleaseResolver)

    app = create_app()

    # v2 path: maps/<map_id>/<filename>
    status, _, headers = asyncio.run(
        _asgi_get(app, "/assets/v/2026_04_01/maps/t2m_mean_map/t2m_mean.png")
    )
    assert status == 200


def test_v2_release_asset_missing_returns_404(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """get_release_asset returns 404 when v2 map file does not exist."""
    from climate_api.config import Settings
    from climate_api.main import create_app
    from climate_api.release import ReleaseContext
    from climate_api.store.tile_data_store import TileDataStore

    artifact_map_dir = tmp_path / "artifacts" / "maps" / "t2m_mean_map" / "2026_04_01"
    artifact_map_dir.mkdir(parents=True)
    # No actual image file

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
        rate_limit_enabled=False,
        rate_limit_sustained_rps=5,
        rate_limit_burst=20,
        rate_limit_window_s=10,
        artifacts_root=tmp_path / "artifacts",
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

    tile_store = TileDataStore(
        tiles_root=tmp_path / "series",
        grid=GridSpec.global_0p25(),
    )
    v2_context = ReleaseContext(
        release="2026_04_01",
        release_root=tmp_path / "releases" / "2026_04_01",
        tile_store=tile_store,
        panels_manifest={},
        maps_manifest={},
        maps_root=tmp_path / "releases" / "2026_04_01" / "maps",
        layers=[],
        format_version=2,
        map_artifact_roots={"t2m_mean_map": artifact_map_dir},
    )

    class _MockReleaseResolver:
        def __init__(self, settings: Settings, logger: Any):
            pass

        def resolve_release_alias(self, requested: str) -> str:
            return requested

        def resolve_release_context(self, release: str):
            return v2_context

        def release_root(self, release: str) -> Path:
            p = tmp_path / "releases" / release
            p.mkdir(parents=True, exist_ok=True)
            return p

    monkeypatch.setattr("climate_api.main.ReleaseResolver", _MockReleaseResolver)

    app = create_app()

    status, data, _ = asyncio.run(
        _asgi_get(app, "/assets/v/2026_04_01/maps/t2m_mean_map/nonexistent.png")
    )
    assert status == 404
    assert "Asset not found" in data.get("detail", "")
