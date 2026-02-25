from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from climate.registry.metrics import DEFAULT_DATASETS_PATH, DEFAULT_METRICS_PATH
from climate_api.config import Settings
from climate_api.release import ReleaseResolver
from fastapi import HTTPException


def _settings(releases_root: Path) -> Settings:
    return Settings(
        release="latest",
        releases_root=releases_root,
        latest_release_file=releases_root / "LATEST",
        locations_csv=Path("unused.csv"),
        kdtree_path=None,
        locations_index_csv=Path("unused.index.csv"),
        ocean_mask_npz=None,
        ocean_names_json=None,
        ocean_off_city_max_km=80.0,
        ocean_city_override_max_km=2.0,
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


def test_dev_release_uses_repo_root_registry_and_warns_for_ignored_release_files(
    tmp_path: Path,
) -> None:
    releases_root = tmp_path / "releases"
    dev_root = releases_root / "dev"
    (dev_root / "series").mkdir(parents=True)
    (dev_root / "maps").mkdir(parents=True)
    (dev_root / "registry").mkdir(parents=True)
    (dev_root / "manifest.json").write_text("{}", encoding="utf-8")

    logger = Mock(spec=logging.Logger)
    resolver = ReleaseResolver(settings=_settings(releases_root), logger=logger)

    with (
        patch("climate_api.release.load_metrics", return_value={"version": "0.1"}) as load_metrics_mock,
        patch("climate_api.release.TileDataStore.discover", return_value=Mock()) as discover_mock,
        patch("climate_api.release.load_panels", return_value={"version": "0.1", "panels": {}}),
        patch("climate_api.release.load_maps", return_value={"version": "0.1"}),
        patch("climate_api.release.load_layers", return_value={"version": "0.1"}),
        patch("climate_api.release.validate_maps_against_metrics"),
        patch("climate_api.release.validate_panels_against_metrics"),
        patch("climate_api.release.validate_panels_against_maps"),
        patch("climate_api.release.validate_layers_against_maps"),
    ):
        resolver.resolve_release_context("dev")

    assert load_metrics_mock.call_args.kwargs["path"] == DEFAULT_METRICS_PATH
    assert load_metrics_mock.call_args.kwargs["datasets_path"] == DEFAULT_DATASETS_PATH
    assert discover_mock.call_args.kwargs["metrics_path"] == DEFAULT_METRICS_PATH
    assert discover_mock.call_args.kwargs["datasets_path"] == DEFAULT_DATASETS_PATH
    assert logger.info.call_count >= 1
    assert logger.warning.call_count >= 2


def test_non_dev_release_uses_release_scoped_registry(tmp_path: Path) -> None:
    releases_root = tmp_path / "releases"
    release_root = releases_root / "2026-01"
    registry_root = release_root / "registry"
    (release_root / "series").mkdir(parents=True)
    (release_root / "maps").mkdir(parents=True)
    registry_root.mkdir(parents=True)
    for name in ("metrics.json", "datasets.json", "maps.json", "panels.json", "layers.json"):
        (registry_root / name).write_text("{}", encoding="utf-8")

    logger = Mock(spec=logging.Logger)
    resolver = ReleaseResolver(settings=_settings(releases_root), logger=logger)

    with (
        patch("climate_api.release.load_metrics", return_value={"version": "0.1"}) as load_metrics_mock,
        patch("climate_api.release.TileDataStore.discover", return_value=Mock()) as discover_mock,
        patch("climate_api.release.load_panels", return_value={"version": "0.1", "panels": {}}),
        patch("climate_api.release.load_maps", return_value={"version": "0.1"}),
        patch("climate_api.release.load_layers", return_value={"version": "0.1"}),
        patch("climate_api.release.validate_maps_against_metrics"),
        patch("climate_api.release.validate_panels_against_metrics"),
        patch("climate_api.release.validate_panels_against_maps"),
        patch("climate_api.release.validate_layers_against_maps"),
    ):
        resolver.resolve_release_context("2026-01")

    assert load_metrics_mock.call_args.kwargs["path"] == registry_root / "metrics.json"
    assert load_metrics_mock.call_args.kwargs["datasets_path"] == registry_root / "datasets.json"
    assert discover_mock.call_args.kwargs["metrics_path"] == registry_root / "metrics.json"
    assert discover_mock.call_args.kwargs["datasets_path"] == registry_root / "datasets.json"
    assert logger.warning.call_count == 0


def test_release_alias_validation_and_empty_latest_pointer(tmp_path: Path) -> None:
    releases_root = tmp_path / "releases"
    releases_root.mkdir(parents=True)
    (releases_root / "LATEST").write_text(" \n", encoding="utf-8")
    resolver = ReleaseResolver(settings=_settings(releases_root), logger=Mock(spec=logging.Logger))

    with pytest.raises(HTTPException, match="Invalid release id"):
        resolver.resolve_release_alias("../bad")
    with pytest.raises(HTTPException, match="cannot be empty"):
        resolver.resolve_release_alias("  ")
    with pytest.raises(HTTPException, match="Latest release pointer is empty"):
        resolver.resolve_release_alias("latest")


def test_latest_alias_falls_back_to_demo_when_latest_missing_and_dev_absent(tmp_path: Path) -> None:
    releases_root = tmp_path / "releases"
    (releases_root / "demo").mkdir(parents=True)
    resolver = ReleaseResolver(settings=_settings(releases_root), logger=Mock(spec=logging.Logger))

    assert resolver.resolve_release_alias("latest") == "demo"


def test_latest_alias_prefers_dev_when_latest_missing(tmp_path: Path) -> None:
    releases_root = tmp_path / "releases"
    (releases_root / "dev").mkdir(parents=True)
    (releases_root / "demo").mkdir(parents=True)
    resolver = ReleaseResolver(settings=_settings(releases_root), logger=Mock(spec=logging.Logger))

    assert resolver.resolve_release_alias("latest") == "dev"


def test_release_root_missing_and_escape_blocked(tmp_path: Path) -> None:
    releases_root = tmp_path / "releases"
    releases_root.mkdir(parents=True)
    resolver = ReleaseResolver(settings=_settings(releases_root), logger=Mock(spec=logging.Logger))

    with pytest.raises(HTTPException, match="Unknown release"):
        resolver.release_root("missing")
    with pytest.raises(HTTPException, match="Invalid release path"):
        resolver.release_root("../outside")


def test_resolve_release_context_maps_errors_to_http(tmp_path: Path) -> None:
    releases_root = tmp_path / "releases"
    releases_root.mkdir(parents=True)
    resolver = ReleaseResolver(settings=_settings(releases_root), logger=Mock(spec=logging.Logger))

    with patch.object(resolver, "_load_release_context", side_effect=FileNotFoundError("x")):
        with pytest.raises(HTTPException) as exc:
            resolver.resolve_release_context("dev")
        assert exc.value.status_code == 404

    with patch.object(resolver, "_load_release_context", side_effect=ValueError("bad")):
        with pytest.raises(HTTPException) as exc:
            resolver.resolve_release_context("dev")
        assert exc.value.status_code == 400

    with patch.object(resolver, "_load_release_context", side_effect=RuntimeError("boom")):
        with pytest.raises(HTTPException) as exc:
            resolver.resolve_release_context("dev")
        assert exc.value.status_code == 500
