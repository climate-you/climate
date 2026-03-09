from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from climate.tiles.layout import GridSpec
from climate_api.store.tile_data_store import TileDataStore, _grid_from_id


def test_grid_from_id_supports_known_grids() -> None:
    assert _grid_from_id("global_0p25", tile_size=32).grid_id == "global_0p25"
    assert _grid_from_id("global_0p05", tile_size=64).grid_id == "global_0p05"
    with pytest.raises(RuntimeError, match="Unknown grid_id"):
        _grid_from_id("unknown", tile_size=64)


def test_discover_from_directory_layout(tmp_path: Path) -> None:
    tiles_root = tmp_path / "series"
    zdir = tiles_root / "global_0p25" / "metric_a" / "z32"
    zdir.mkdir(parents=True)

    store = TileDataStore.discover(
        tiles_root,
        metrics_path=None,
        schema_path=None,
        datasets_path=None,
    )
    assert store.grid.grid_id == "global_0p25"
    assert store.grid.tile_size == 32


def test_discover_errors_for_missing_layout_cases(tmp_path: Path) -> None:
    (tmp_path / "series_empty").mkdir(parents=True)
    with pytest.raises(RuntimeError, match="No grid folders found"):
        TileDataStore.discover(
            tmp_path / "series_empty",
            metrics_path=None,
            schema_path=None,
            datasets_path=None,
        )

    bad_grid = tmp_path / "series_bad" / "custom_grid"
    (bad_grid / "metric" / "z16").mkdir(parents=True)
    with pytest.raises(RuntimeError, match="Unknown grid_id"):
        TileDataStore.discover(
            tmp_path / "series_bad",
            metrics_path=None,
            schema_path=None,
            datasets_path=None,
        )

    no_z = tmp_path / "series_noz" / "global_0p25" / "metric"
    no_z.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="Could not find any zNN folder"):
        TileDataStore.discover(
            tmp_path / "series_noz",
            metrics_path=None,
            schema_path=None,
            datasets_path=None,
        )


def test_axis_prefers_metric_spec_values_and_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tiles_root = tmp_path / "series"
    grid = GridSpec.global_0p25(tile_size=64)
    axis_file = tmp_path / "axis.json"
    axis_file.write_text(json.dumps([1990, 1991]), encoding="utf-8")
    monkeypatch.setattr("climate_api.store.tile_data_store.REPO_ROOT", tmp_path)

    store = TileDataStore(
        tiles_root=tiles_root,
        grid=grid,
        metrics={
            "metric_values": {"axis": {"values": [2000, 2001]}},
            "metric_path": {"axis": {"path": "axis.json"}},
        },
        grids={grid.grid_id: grid},
    )

    assert store.axis("metric_values") == [2000, 2001]
    assert store.axis("metric_path") == [1990, 1991]


def test_axis_reads_metric_and_legacy_grid_time_files(tmp_path: Path) -> None:
    tiles_root = tmp_path / "series"
    grid = GridSpec.global_0p25(tile_size=64)
    metric_time = tiles_root / grid.grid_id / "m1" / "time"
    metric_time.mkdir(parents=True)
    (metric_time / "yearly.json").write_text(json.dumps([2019, 2020]), encoding="utf-8")
    legacy_time = tiles_root / grid.grid_id / "time"
    legacy_time.mkdir(parents=True)
    (legacy_time / "monthly.json").write_text(
        json.dumps(["2020-01", "2020-02"]), encoding="utf-8"
    )

    store = TileDataStore(
        tiles_root=tiles_root,
        grid=grid,
        metrics={
            "m1": {"time_axis": "yearly"},
            "m2": {"time_axis": "monthly"},
        },
        grids={grid.grid_id: grid},
    )
    assert store.yearly_axis("m1") == [2019, 2020]
    assert store.axis("m2") == ["2020-01", "2020-02"]
    with pytest.raises(ValueError, match="Expected numeric years"):
        store.yearly_axis("m2")


def test_metric_tile_extension_and_unknown_codec() -> None:
    grid = GridSpec.global_0p25(tile_size=64)
    store = TileDataStore(
        tiles_root=Path("."),
        grid=grid,
        metrics={
            "zstd": {"storage": {"compression": {"codec": "zstd"}}},
            "plain": {"storage": {"compression": {"codec": "none"}}},
            "bad": {"storage": {"compression": {"codec": "gzip"}}},
        },
        grids={grid.grid_id: grid},
    )
    assert store._metric_tile_ext("zstd") == ".bin.zst"
    assert store._metric_tile_ext("plain") == ".bin"
    with pytest.raises(ValueError, match="Unsupported compression codec"):
        store._metric_tile_ext("bad")


def test_metric_grid_lookup_errors_when_grid_missing() -> None:
    grid = GridSpec.global_0p25(tile_size=64)
    store = TileDataStore(
        tiles_root=Path("."),
        grid=grid,
        metrics={"m": {"grid_id": "global_0p05"}},
        grids={grid.grid_id: grid},
    )
    with pytest.raises(RuntimeError, match="No grid spec loaded"):
        store._metric_grid("m")


def test_try_get_metric_vector_handles_missing_and_nan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    grid = GridSpec.global_0p25(tile_size=64)
    store = TileDataStore(
        tiles_root=tmp_path / "series",
        grid=grid,
        metrics={},
        grids={grid.grid_id: grid},
    )

    with pytest.raises(FileNotFoundError):
        store.try_get_metric_vector("m", lat=0.0, lon=0.0)

    tile_path = store._metric_tile_path("m", tile_r=0, tile_c=0)
    tile_path.parent.mkdir(parents=True)
    tile_path.write_bytes(b"x")

    monkeypatch.setattr(
        "climate_api.store.tile_data_store.locate_tile",
        lambda lat, lon, grid: (
            SimpleNamespace(),
            SimpleNamespace(tile_r=0, tile_c=0, o_lat=0, o_lon=0),
        ),
    )
    monkeypatch.setattr(
        "climate_api.store.tile_data_store.read_cell_series",
        lambda p, o_lat, o_lon: (None, np.array([np.nan, np.nan], dtype=np.float32)),
    )
    assert store.try_get_metric_vector("m", lat=0.0, lon=0.0) is None

    monkeypatch.setattr(
        "climate_api.store.tile_data_store.read_cell_series",
        lambda p, o_lat, o_lon: (None, np.array([1.0, 2.0], dtype=np.float32)),
    )
    vec = store.try_get_metric_vector("m", lat=0.0, lon=0.0)
    assert np.allclose(vec, np.array([1.0, 2.0], dtype=np.float32))
