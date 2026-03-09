from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from climate_api.schemas import PlaceInfo
from climate_api.services import panels as panels_module


def test_apply_transform_and_convert_unit() -> None:
    x = np.array([2000.0, 2001.0, 2002.0], dtype=np.float64)
    y = np.array([1.0, 2.0, 3.0], dtype=np.float32)

    assert np.allclose(panels_module._apply_transform(x=x, y=y, transform=None), y)
    rolling = panels_module._apply_transform(
        x=x,
        y=y,
        transform={"fn": "rolling_mean", "params": {"window": 3}},
    )
    assert np.isnan(rolling[0]) and np.isnan(rolling[2])
    assert float(rolling[1]) == pytest.approx(2.0)

    trend = panels_module._apply_transform(x=x, y=y, transform="linear_trend_line")
    assert np.allclose(trend, y, atol=1e-5)

    with pytest.raises(ValueError, match="Unsupported transform"):
        panels_module._apply_transform(x=x, y=y, transform={"fn": "unknown"})

    assert np.allclose(
        panels_module._convert_unit(y, "C", "F"), np.array([33.8, 35.6, 37.4])
    )
    assert np.allclose(
        panels_module._convert_unit(np.array([32.0, 50.0]), "F", "C"),
        np.array([0.0, 10.0]),
    )


def test_series_axis_and_caption_helpers() -> None:
    tile_store = SimpleNamespace(
        start_year_fallback=1979,
        axis=lambda metric: [2000, 2001, 2002, 2003],
    )
    axis = panels_module._series_axis(tile_store, "metric", 2)
    assert axis == [2002, 2003]

    non_numeric_store = SimpleNamespace(
        start_year_fallback=1980,
        axis=lambda metric: ["a"],
    )
    assert panels_module._series_axis(non_numeric_store, "metric", 3) == [
        1980,
        1981,
        1982,
    ]

    ctx = panels_module._caption_context_from_series(
        axis_series=([2000, 2001], np.array([1.0, 3.0], dtype=np.float32)),
        unit="C",
        place=PlaceInfo(geonameid=1, label="A", lat=1.0, lon=2.0, distance_km=0.0),
        lat=-1.0,
    )
    assert ctx["data"]["total_span_years"] == 1
    assert ctx["facts"]["hemisphere"] == "S"

    assert (
        panels_module._caption_from_spec({"type": "static", "text": "x"}, context=ctx)
        == "x"
    )
    assert panels_module._caption_from_spec({}, context=ctx) is None
    assert panels_module._caption_from_spec({"type": "noop"}, context=ctx) is None
    assert panels_module._caption_from_spec({"type": "fn"}, context=ctx) is None
    with pytest.raises(KeyError, match="Unknown caption function"):
        panels_module._caption_from_spec({"type": "fn", "fn": "missing"}, context=ctx)


def test_read_score_value_clamps_constant_scores() -> None:
    tile_store = SimpleNamespace(
        _metric_grid=lambda metric: SimpleNamespace(grid_id="global_0p25")
    )
    assert (
        panels_module._read_score_value(
            lat=0.0,
            lon=0.0,
            map_id="m",
            map_spec={"constant_score": -2},
            tile_store=tile_store,
            maps_root=Path("."),
        )
        == 0
    )
    assert (
        panels_module._read_score_value(
            lat=0.0,
            lon=0.0,
            map_id="m",
            map_spec={"constant_score": 6},
            tile_store=tile_store,
            maps_root=Path("."),
        )
        == 4
    )


def test_read_score_value_from_binary_with_source_metric(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    grid = SimpleNamespace(grid_id="global_0p25", nlat=2, nlon=3)
    tile_store = SimpleNamespace(_metric_grid=lambda metric: grid)
    monkeypatch.setattr(panels_module, "_grid_from_id", lambda grid_id: grid)
    monkeypatch.setattr(
        panels_module,
        "_load_score_map_values_cached",
        lambda bin_path, expected: np.array([0, 1, 2, 3, 4, 9], dtype=np.int16),
    )
    monkeypatch.setattr(
        panels_module,
        "locate_tile",
        lambda lat, lon, grid: (SimpleNamespace(i_lat=1, i_lon=2), None),
    )

    score = panels_module._read_score_value(
        lat=0.0,
        lon=0.0,
        map_id="m",
        map_spec={"type": "score", "source_metric": "metric_a", "output": {}},
        tile_store=tile_store,
        maps_root=Path("/tmp"),
    )
    assert score == 4


def test_compute_t2m_preindustrial_headline_success_and_missing() -> None:
    years = list(range(1979, 2024))
    current = np.linspace(10.0, 12.2, num=len(years), dtype=np.float32)
    offset = np.array([0.5], dtype=np.float32)

    class _Store:
        def axis(self, metric: str):
            return years

        def try_get_metric_vector(self, metric: str, lat: float, lon: float):
            if metric == "t2m_yearly_mean_c":
                return current
            if metric == "t2m_cmip_offset_1979_2000_vs_1850_1900_mean_5models_c":
                return offset
            return None

    headline = panels_module._compute_t2m_preindustrial_headline(
        tile_store=_Store(),
        lat=0.0,
        lon=0.0,
        unit="C",
    )
    assert headline.value is not None
    assert headline.unit == "C"
    assert headline.period == "2019-2023"

    class _MissingStore:
        def try_get_metric_vector(self, metric: str, lat: float, lon: float):
            return None

    missing = panels_module._compute_t2m_preindustrial_headline(
        tile_store=_MissingStore(),
        lat=0.0,
        lon=0.0,
        unit="F",
    )
    assert missing.value is None
    assert missing.unit == "F"


def test_series_and_axis_misc_branches() -> None:
    assert (
        panels_module._series_key({"metric": "m", "transform": {"fn": "rolling_mean"}})
        == "m_rolling_mean"
    )
    assert (
        panels_module._series_key({"metric": "m", "transform": "linear_trend_line"})
        == "m_linear_trend_line"
    )
    assert np.allclose(
        panels_module._convert_unit(np.array([1.0], dtype=np.float32), None, "C"),
        np.array([1.0], dtype=np.float32),
    )
    assert (
        panels_module._build_series_annotations(
            series_key="s",
            y=np.array([np.nan, np.nan], dtype=np.float32),
            unit="C",
            annotations=[{"type": "min"}],
        )
        == []
    )
    assert np.isnan(panels_module._axis_to_numeric("not-a-date"))

    axis_trim_store = SimpleNamespace(
        start_year_fallback=1979, axis=lambda metric: ["a", "b", "c", "d"]
    )
    assert panels_module._series_axis(axis_trim_store, "m", 2) == ["c", "d"]
    axis_empty_store = SimpleNamespace(start_year_fallback=1985, axis=lambda metric: [])
    assert panels_module._series_axis(axis_empty_store, "m", 3) == [1985, 1986, 1987]
    assert panels_module._to_unit_delta(1.0, "F") == pytest.approx(1.8)


def test_trend_extension_helpers() -> None:
    axis_end, x_end = panels_module._resolve_trend_extend_value(
        axis_vals=["2024-10-01", "2024-11-01"], extend_to="2025"
    )
    assert axis_end == "2025-12-31"
    assert isinstance(x_end, float)

    axis_vals, y_out = panels_module._apply_transform_with_axis(
        axis_vals=["2024-10-01", "2024-11-01"],
        x=np.array([1.0, 2.0], dtype=np.float64),
        y=np.array([10.0, 12.0], dtype=np.float32),
        transform={"fn": "linear_trend_line", "params": {"extend_to": "2025-12-31"}},
    )
    assert axis_vals[-1] == "2025-12-31"
    assert len(axis_vals) == 3
    assert y_out.shape[0] == 3


def test_headline_early_return_branches() -> None:
    # FileNotFound path for current metric
    class _NoCurrent:
        def try_get_metric_vector(self, metric: str, lat: float, lon: float):
            raise FileNotFoundError("missing")

    h = panels_module._compute_t2m_preindustrial_headline(
        tile_store=_NoCurrent(), lat=0.0, lon=0.0, unit="C"
    )
    assert h.value is None

    # Finite years empty / recent too short / era5 ref too short
    class _StoreFiniteEmpty:
        def axis(self, metric: str):
            return ["bad", "axis"]

        def try_get_metric_vector(self, metric: str, lat: float, lon: float):
            return np.array([1.0, 2.0], dtype=np.float32)

    assert (
        panels_module._compute_t2m_preindustrial_headline(
            tile_store=_StoreFiniteEmpty(), lat=0.0, lon=0.0, unit="C"
        ).value
        is None
    )

    class _StoreRecentShort:
        def axis(self, metric: str):
            return [2022, 2023]

        def try_get_metric_vector(self, metric: str, lat: float, lon: float):
            if metric == "t2m_yearly_mean_c":
                return np.array([10.0, 11.0], dtype=np.float32)
            return np.array([0.2], dtype=np.float32)

    assert (
        panels_module._compute_t2m_preindustrial_headline(
            tile_store=_StoreRecentShort(), lat=0.0, lon=0.0, unit="C"
        ).value
        is None
    )

    class _StoreEraShort:
        def axis(self, metric: str):
            return [2015, 2016, 2017, 2018, 2019]

        def try_get_metric_vector(self, metric: str, lat: float, lon: float):
            if metric == "t2m_yearly_mean_c":
                return np.array([10, 11, 12, 13, 14], dtype=np.float32)
            return np.array([0.2], dtype=np.float32)

    assert (
        panels_module._compute_t2m_preindustrial_headline(
            tile_store=_StoreEraShort(), lat=0.0, lon=0.0, unit="C"
        ).value
        is None
    )

    class _StoreMissingCmip:
        def axis(self, metric: str):
            return list(range(1979, 2024))

        def try_get_metric_vector(self, metric: str, lat: float, lon: float):
            if metric == "t2m_yearly_mean_c":
                return np.linspace(10.0, 12.0, num=45, dtype=np.float32)
            raise FileNotFoundError("cmip missing")

    assert (
        panels_module._compute_t2m_preindustrial_headline(
            tile_store=_StoreMissingCmip(), lat=0.0, lon=0.0, unit="C"
        ).value
        is None
    )

    class _StoreEmptyCmip:
        def axis(self, metric: str):
            return list(range(1979, 2024))

        def try_get_metric_vector(self, metric: str, lat: float, lon: float):
            if metric == "t2m_yearly_mean_c":
                return np.linspace(10.0, 12.0, num=45, dtype=np.float32)
            return np.array([np.nan], dtype=np.float32)

    assert (
        panels_module._compute_t2m_preindustrial_headline(
            tile_store=_StoreEmptyCmip(), lat=0.0, lon=0.0, unit="C"
        ).value
        is None
    )


def test_preload_score_maps_cache_and_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    grid = SimpleNamespace(grid_id="global_0p25", nlat=2, nlon=2)
    tile_store = SimpleNamespace(_metric_grid=lambda metric: grid)
    monkeypatch.setattr(panels_module, "_grid_from_id", lambda grid_id: grid)

    seen: list[tuple[Path, int]] = []
    monkeypatch.setattr(
        panels_module,
        "_load_score_map_values_cached",
        lambda bin_path, expected: seen.append((bin_path, expected))
        or np.zeros(4, dtype=np.int16),
    )
    loaded, skipped = panels_module.preload_score_maps_cache(
        maps_manifest={
            "version": "0.1",
            "const": {"type": "score", "constant_score": 2},
            "valid": {"type": "score", "grid_id": "global_0p25"},
            "by_metric": {"type": "score", "source_metric": "m1"},
        },
        tile_store=tile_store,
        maps_root=Path("/tmp"),
    )
    assert loaded == 2
    assert skipped == 1
    assert len(seen) == 2

    with pytest.raises(KeyError, match="must define grid_id or a valid source_metric"):
        panels_module.preload_score_maps_cache(
            maps_manifest={"bad": {"type": "score"}},
            tile_store=tile_store,
            maps_root=Path("/tmp"),
        )


def test_load_score_map_values_cached_missing_and_invalid_size(tmp_path: Path) -> None:
    missing = tmp_path / "missing.bin"
    with pytest.raises(FileNotFoundError, match="Missing score map binary"):
        panels_module._load_score_map_values_cached(bin_path=missing, expected=1)

    bad = tmp_path / "bad.bin"
    np.array([1, 2], dtype="<i2").tofile(bad)
    with pytest.raises(ValueError, match="invalid size"):
        panels_module._load_score_map_values_cached(bin_path=bad, expected=3)

    good = tmp_path / "good.bin"
    np.array([1, 2, 3], dtype="<i2").tofile(good)
    first = panels_module._load_score_map_values_cached(bin_path=good, expected=3)
    good.unlink()
    second = panels_module._load_score_map_values_cached(bin_path=good, expected=3)
    assert np.array_equal(first, second)


def test_build_scored_panels_tiles_registry_validates_manifest() -> None:
    place_resolver = SimpleNamespace(
        resolve_place=lambda lat, lon: SimpleNamespace(
            geonameid=1,
            label="A",
            lat=lat,
            lon=lon,
            distance_km=0.0,
            country_code="US",
            population=1,
        )
    )
    tile_store = SimpleNamespace()

    with pytest.raises(KeyError, match="missing 'panels' root object"):
        panels_module.build_scored_panels_tiles_registry(
            place_resolver=place_resolver,
            tile_store=tile_store,
            cache=None,
            ttl_panel_s=10,
            release="dev",
            lat=0.0,
            lon=0.0,
            unit="C",
            panels_manifest={"panels": []},
            maps_manifest={},
            maps_root=Path("/tmp"),
        )

    with pytest.raises(KeyError, match="missing score_map_id"):
        panels_module.build_scored_panels_tiles_registry(
            place_resolver=place_resolver,
            tile_store=tile_store,
            cache=None,
            ttl_panel_s=10,
            release="dev",
            lat=0.0,
            lon=0.0,
            unit="C",
            panels_manifest={"panels": {"p1": {}}},
            maps_manifest={},
            maps_root=Path("/tmp"),
        )

    with pytest.raises(KeyError, match="unknown score map"):
        panels_module.build_scored_panels_tiles_registry(
            place_resolver=place_resolver,
            tile_store=tile_store,
            cache=None,
            ttl_panel_s=10,
            release="dev",
            lat=0.0,
            lon=0.0,
            unit="C",
            panels_manifest={"panels": {"p1": {"score_map_id": "m1"}}},
            maps_manifest={"m1x": {"type": "score"}},
            maps_root=Path("/tmp"),
        )

    with pytest.raises(KeyError, match="unsupported type"):
        panels_module.build_scored_panels_tiles_registry(
            place_resolver=place_resolver,
            tile_store=tile_store,
            cache=None,
            ttl_panel_s=10,
            release="dev",
            lat=0.0,
            lon=0.0,
            unit="C",
            panels_manifest={"panels": {"p1": {"score_map_id": "m1"}}},
            maps_manifest={"m1": {"type": "texture"}},
            maps_root=Path("/tmp"),
        )


def test_grid_and_read_score_misc_branches() -> None:
    with pytest.raises(KeyError, match="Unsupported map grid_id"):
        panels_module._grid_from_id("bad_grid")
    assert (
        panels_module._read_score_value(
            lat=0.0,
            lon=0.0,
            map_id="m",
            map_spec={"constant_score": 3},
            tile_store=SimpleNamespace(),
            maps_root=Path("/tmp"),
        )
        == 3
    )

    with pytest.raises(KeyError, match="must define grid_id or a valid source_metric"):
        panels_module._read_score_value(
            lat=0.0,
            lon=0.0,
            map_id="m",
            map_spec={"type": "score"},
            tile_store=SimpleNamespace(),
            maps_root=Path("/tmp"),
        )

    grid = SimpleNamespace(grid_id="global_0p25", nlat=1, nlon=1)
    old_grid_from_id = panels_module._grid_from_id
    old_locate_tile = panels_module.locate_tile
    old_loader = panels_module._load_score_map_values_cached
    try:
        panels_module._grid_from_id = lambda grid_id: grid
        panels_module.locate_tile = lambda lat, lon, g: (
            SimpleNamespace(i_lat=0, i_lon=0),
            None,
        )
        panels_module._load_score_map_values_cached = (
            lambda bin_path, expected: np.array([-1], dtype=np.int16)
        )
        assert (
            panels_module._read_score_value(
                lat=0.0,
                lon=0.0,
                map_id="m",
                map_spec={"type": "score", "grid_id": "global_0p25"},
                tile_store=SimpleNamespace(),
                maps_root=Path("/tmp"),
            )
            == 0
        )
    finally:
        panels_module._grid_from_id = old_grid_from_id
        panels_module.locate_tile = old_locate_tile
        panels_module._load_score_map_values_cached = old_loader
