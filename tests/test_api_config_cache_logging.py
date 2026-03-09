from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from climate_api import cache as cache_module
from climate_api import config as config_module
from climate_api import logging as logging_module
from climate_api.main import _normalize_lon


def test_load_settings_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("REPO_ROOT", str(tmp_path))
    monkeypatch.delenv("RELEASE", raising=False)
    monkeypatch.delenv("KDTREE_PATH", raising=False)
    monkeypatch.delenv("OCEAN_MASK_NPZ", raising=False)
    monkeypatch.delenv("OCEAN_NAMES_JSON", raising=False)

    settings = config_module.load_settings()

    assert settings.release == "latest"
    assert settings.releases_root == tmp_path / "data" / "releases"
    assert (
        settings.kdtree_path == tmp_path / "data" / "locations" / "locations.kdtree.pkl"
    )
    assert settings.ocean_mask_npz == tmp_path / "data" / "locations" / "ocean_mask.npz"
    assert (
        settings.ocean_names_json
        == tmp_path / "data" / "locations" / "ocean_names.json"
    )
    assert settings.score_map_preload is False
    assert settings.cors_allow_origins == ["*"]
    assert settings.cors_allow_credentials is False
    assert settings.rate_limit_enabled is True
    assert settings.rate_limit_sustained_rps == 5
    assert settings.rate_limit_burst == 20
    assert settings.rate_limit_window_s == 10


def test_load_settings_none_like_env_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KDTREE_PATH", " none ")
    monkeypatch.setenv("OCEAN_MASK_NPZ", "false")
    monkeypatch.setenv("OCEAN_NAMES_JSON", "0")
    monkeypatch.setenv("SCORE_MAP_PRELOAD", "YES")
    monkeypatch.setenv(
        "CORS_ALLOW_ORIGINS", "https://a.example.com,https://b.example.com"
    )
    monkeypatch.setenv("CORS_ALLOW_CREDENTIALS", "true")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_SUSTAINED_RPS", "3")
    monkeypatch.setenv("RATE_LIMIT_BURST", "11")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_S", "7")

    settings = config_module.load_settings()

    assert settings.kdtree_path is None
    assert settings.ocean_mask_npz is None
    assert settings.ocean_names_json is None
    assert settings.score_map_preload is True
    assert settings.cors_allow_origins == [
        "https://a.example.com",
        "https://b.example.com",
    ]
    assert settings.cors_allow_credentials is True
    assert settings.rate_limit_enabled is False
    assert settings.rate_limit_sustained_rps == 3
    assert settings.rate_limit_burst == 11
    assert settings.rate_limit_window_s == 7


def test_cache_memory_roundtrip_and_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = cache_module.Cache(prefix="test")
    now = 1000.0
    monkeypatch.setattr(cache_module.time, "time", lambda: now)
    cache.set_json("key", {"x": 1}, ttl_s=10)
    assert cache.get_json("key") == {"x": 1}

    monkeypatch.setattr(cache_module.time, "time", lambda: now + 20.0)
    assert cache.get_json("key") is None


def test_cache_redis_backend_usage() -> None:
    redis = Mock()
    redis.get.return_value = b'{"ok":true}'
    cache = cache_module.Cache(redis=redis, prefix="p")

    assert cache.get_json("abc") == {"ok": True}
    cache.set_json("abc", {"value": 2}, ttl_s=33)
    redis.setex.assert_called_once()


def test_make_redis_client_errors_when_redis_package_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cache_module, "Redis", None)
    with pytest.raises(RuntimeError, match="redis package not installed"):
        cache_module.make_redis_client("redis://localhost:6379/0")


def test_format_access_line_and_normalize_lon() -> None:
    line = logging_module.format_access_line(
        "127.0.0.1:9000",
        "GET /health HTTP/1.1",
        404,
        12.345,
        use_colors=False,
    )
    assert "CLIENT ERROR" in line
    assert "(12.3 ms)" in line
    assert _normalize_lon(529.0) == -191.0 + 360.0
    assert _normalize_lon(180.0) == -180.0
