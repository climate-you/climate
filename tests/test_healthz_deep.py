from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from climate_api.config import Settings
from climate_api.main import create_app
from tests.test_main_unit import _asgi_get


def _app_with_tile_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tile_store: Any
) -> Any:
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
    )
    monkeypatch.setattr("climate_api.main.load_settings", lambda: settings)
    monkeypatch.setattr("climate_api.main.LocationIndex", lambda _path: None)
    monkeypatch.setattr("climate_api.main.PlaceResolver", lambda **kwargs: None)

    class _ReleaseResolver:
        def __init__(self, settings: Settings, logger: Any):
            pass

        def resolve_release_context(self, requested_release: str):
            if tile_store is None:
                raise FileNotFoundError("/srv/climate/data/releases/LATEST")
            return SimpleNamespace(release="v2.3.6", tile_store=tile_store)

    monkeypatch.setattr("climate_api.main.ReleaseResolver", _ReleaseResolver)
    return create_app()


def test_deep_health_reads_one_cell_and_names_the_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reads: list[tuple[str, float, float]] = []

    def _read(metric: str, lat: float, lon: float):
        reads.append((metric, lat, lon))
        return np.arange(48, dtype=np.float32)

    app = _app_with_tile_store(
        tmp_path, monkeypatch, SimpleNamespace(try_get_metric_vector=_read)
    )
    status, data, headers = asyncio.run(_asgi_get(app, "/healthz/deep"))

    assert status == 200
    assert data["status"] == "ok"
    assert data["release"] == "v2.3.6"
    assert data["values"] == 48
    assert headers["cache-control"] == "no-store"
    # Every call reaches the store: nothing in front of it may answer instead.
    asyncio.run(_asgi_get(app, "/healthz/deep"))
    assert len(reads) == 2


def _missing_tile(metric: str, lat: float, lon: float):
    raise FileNotFoundError("Missing tile file: /srv/climate/r002_c011.bin.zst")


@pytest.mark.parametrize(
    "tile_store",
    [
        None,  # the release cannot be resolved
        SimpleNamespace(try_get_metric_vector=_missing_tile),
        SimpleNamespace(try_get_metric_vector=lambda *a: None),  # an empty cell
    ],
    ids=["no-release", "missing-tile", "empty-cell"],
)
def test_deep_health_is_503_without_the_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tile_store: Any
) -> None:
    app = _app_with_tile_store(tmp_path, monkeypatch, tile_store)
    status, data, headers = asyncio.run(_asgi_get(app, "/healthz/deep"))

    assert status == 503
    assert data["status"] == "fail"
    assert "/srv" not in str(data)
    assert headers["cache-control"] == "no-store"
