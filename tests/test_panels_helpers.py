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


# ---------------------------------------------------------------------------
# _compute_t2m_recent_headline  (significantly refactored)
# ---------------------------------------------------------------------------

def test_compute_t2m_recent_headline_success() -> None:
    years = list(range(1979, 2024))

    class _Store:
        def axis(self, metric: str):
            return years

        def try_get_metric_vector(self, metric: str, lat: float, lon: float):
            return np.linspace(10.0, 12.2, num=len(years), dtype=np.float32)

    h = panels_module._compute_t2m_recent_headline(
        tile_store=_Store(), lat=0.0, lon=0.0, unit="C"
    )
    assert h.value is not None
    assert h.unit == "C"
    assert h.baseline == "1979-2000"
    assert h.period is not None and "-" in h.period


def test_compute_t2m_recent_headline_unit_conversion() -> None:
    years = list(range(1979, 2024))

    class _Store:
        def axis(self, metric: str):
            return years

        def try_get_metric_vector(self, metric: str, lat: float, lon: float):
            return np.linspace(10.0, 12.2, num=len(years), dtype=np.float32)

    h_c = panels_module._compute_t2m_recent_headline(
        tile_store=_Store(), lat=0.0, lon=0.0, unit="C"
    )
    h_f = panels_module._compute_t2m_recent_headline(
        tile_store=_Store(), lat=0.0, lon=0.0, unit="F"
    )
    assert h_f.unit == "F"
    assert h_f.value == pytest.approx(h_c.value * 1.8, abs=1e-3)


def test_compute_t2m_recent_headline_missing_cases() -> None:
    class _FileNotFound:
        def try_get_metric_vector(self, metric: str, lat: float, lon: float):
            raise FileNotFoundError("missing")

    assert panels_module._compute_t2m_recent_headline(
        tile_store=_FileNotFound(), lat=0.0, lon=0.0, unit="C"
    ).value is None

    class _NoneVec:
        def try_get_metric_vector(self, metric: str, lat: float, lon: float):
            return None

    assert panels_module._compute_t2m_recent_headline(
        tile_store=_NoneVec(), lat=0.0, lon=0.0, unit="C"
    ).value is None

    # All-NaN axis values -> finite_years empty
    class _BadAxis:
        start_year_fallback = 1979

        def axis(self, metric: str):
            return ["not-a-date", "also-not"]

        def try_get_metric_vector(self, metric: str, lat: float, lon: float):
            return np.array([10.0, 11.0], dtype=np.float32)

    assert panels_module._compute_t2m_recent_headline(
        tile_store=_BadAxis(), lat=0.0, lon=0.0, unit="C"
    ).value is None

    # Only 2 recent years (< _HEADLINE_RECENT_YEARS - 1 = 4)
    class _TooShortRecent:
        def axis(self, metric: str):
            return list(range(1979, 2000)) + [2022, 2023]

        def try_get_metric_vector(self, metric: str, lat: float, lon: float):
            return np.ones(21 + 2, dtype=np.float32)

    assert panels_module._compute_t2m_recent_headline(
        tile_store=_TooShortRecent(), lat=0.0, lon=0.0, unit="C"
    ).value is None

    # Ref period 1979-2000 has fewer than 10 years
    class _TooShortRef:
        def axis(self, metric: str):
            return [1995, 1996, 2019, 2020, 2021, 2022, 2023]

        def try_get_metric_vector(self, metric: str, lat: float, lon: float):
            return np.ones(7, dtype=np.float32)

    assert panels_module._compute_t2m_recent_headline(
        tile_store=_TooShortRef(), lat=0.0, lon=0.0, unit="C"
    ).value is None


# ---------------------------------------------------------------------------
# _compute_trend_at_last_headline  (new generic helper)
# ---------------------------------------------------------------------------

def _trend_store(years, values):
    class _Store:
        start_year_fallback = years[0]

        def axis(self, metric: str):
            return years

        def try_get_metric_vector(self, metric: str, lat: float, lon: float):
            return np.asarray(values, dtype=np.float32)

    return _Store()


def test_compute_trend_at_last_headline_success() -> None:
    years = list(range(1979, 2024))
    values = np.linspace(5.0, 10.0, num=len(years))
    store = _trend_store(years, values)

    h = panels_module._compute_trend_at_last_headline(
        tile_store=store,
        lat=0.0,
        lon=0.0,
        metric="t2m_hotdays_per_year",
        key="t2m_hotdays_local",
        label="Air hot days per year",
        unit="days",
        baseline_year=1979,
    )
    assert h.value is not None
    assert h.key == "t2m_hotdays_local"
    assert h.unit == "days"
    assert h.baseline_value is not None
    assert h.period == str(years[-1])


def test_compute_trend_at_last_headline_missing() -> None:
    class _FileNotFound:
        def try_get_metric_vector(self, metric: str, lat: float, lon: float):
            raise FileNotFoundError("missing")

    h = panels_module._compute_trend_at_last_headline(
        tile_store=_FileNotFound(), lat=0.0, lon=0.0,
        metric="m", key="k", label="L", unit="days", baseline_year=1979,
    )
    assert h.value is None

    class _NoneVec:
        def try_get_metric_vector(self, metric: str, lat: float, lon: float):
            return None

    h2 = panels_module._compute_trend_at_last_headline(
        tile_store=_NoneVec(), lat=0.0, lon=0.0,
        metric="m", key="k", label="L", unit="days", baseline_year=1979,
    )
    assert h2.value is None


def test_compute_trend_at_last_headline_no_baseline_year() -> None:
    years = list(range(2010, 2024))
    values = np.linspace(1.0, 5.0, num=len(years))
    store = _trend_store(years, values)

    h = panels_module._compute_trend_at_last_headline(
        tile_store=store, lat=0.0, lon=0.0,
        metric="m", key="k", label="L", unit="days", baseline_year=1979,
    )
    assert h.value is not None
    assert h.baseline_value is None


# ---------------------------------------------------------------------------
# _compute_coral_local_headlines  (new)
# ---------------------------------------------------------------------------

def test_compute_coral_local_headlines_file_not_found() -> None:
    class _Store:
        start_year_fallback = 1985

        def axis(self, metric: str):
            return list(range(1985, 2024))

        def try_get_metric_vector(self, metric: str, lat: float, lon: float):
            raise FileNotFoundError("missing")

    result = panels_module._compute_coral_local_headlines(
        tile_store=_Store(), lat=0.0, lon=0.0
    )
    assert len(result) == 3
    assert all(h.value is None for h in result)


def test_compute_coral_local_headlines_none_severe() -> None:
    class _Store:
        start_year_fallback = 1985

        def axis(self, metric: str):
            return list(range(1985, 2024))

        def try_get_metric_vector(self, metric: str, lat: float, lon: float):
            return None

    result = panels_module._compute_coral_local_headlines(
        tile_store=_Store(), lat=0.0, lon=0.0
    )
    assert all(h.value is None for h in result)


def test_compute_coral_local_headlines_all_nan_severe() -> None:
    class _Store:
        start_year_fallback = 1985

        def axis(self, metric: str):
            return list(range(1985, 2024))

        def try_get_metric_vector(self, metric: str, lat: float, lon: float):
            n = len(list(range(1985, 2024)))
            return np.full(n, np.nan, dtype=np.float32)

    result = panels_module._compute_coral_local_headlines(
        tile_store=_Store(), lat=0.0, lon=0.0
    )
    assert all(h.value is None for h in result)


def test_compute_coral_local_headlines_severe_only() -> None:
    years = list(range(1985, 2024))
    severe = np.zeros(len(years), dtype=np.float32)
    severe[10] = 30.0  # worst year = 1985+10 = 1995

    class _Store:
        start_year_fallback = 1985

        def axis(self, metric: str):
            return years

        def try_get_metric_vector(self, metric: str, lat: float, lon: float):
            if "severe" in metric:
                return severe
            return None  # no moderate

    result = panels_module._compute_coral_local_headlines(
        tile_store=_Store(), lat=0.0, lon=0.0
    )
    assert result[0].value == 1.0  # flag
    assert result[1].value == 1995.0  # worst year
    assert result[2].value == 30.0  # days


def test_compute_coral_local_headlines_severe_plus_moderate() -> None:
    years = list(range(1985, 2024))
    n = len(years)
    severe = np.zeros(n, dtype=np.float32)
    moderate = np.zeros(n, dtype=np.float32)
    severe[5] = 10.0
    moderate[5] = 15.0  # combined 25 at year 1990, larger than any other year

    class _Store:
        start_year_fallback = 1985

        def axis(self, metric: str):
            return years

        def try_get_metric_vector(self, metric: str, lat: float, lon: float):
            if "severe" in metric:
                return severe
            return moderate

    result = panels_module._compute_coral_local_headlines(
        tile_store=_Store(), lat=0.0, lon=0.0
    )
    assert result[1].value == 1990.0
    assert result[2].value == 25.0


def test_compute_coral_local_headlines_mismatched_moderate_size() -> None:
    years = list(range(1985, 2024))
    n = len(years)
    severe = np.zeros(n, dtype=np.float32)
    severe[0] = 5.0
    mismatched_moderate = np.ones(n + 3, dtype=np.float32)  # wrong size

    class _Store:
        start_year_fallback = 1985

        def axis(self, metric: str):
            return years

        def try_get_metric_vector(self, metric: str, lat: float, lon: float):
            if "severe" in metric:
                return severe
            return mismatched_moderate

    result = panels_module._compute_coral_local_headlines(
        tile_store=_Store(), lat=0.0, lon=0.0
    )
    # Mismatched moderate is treated as zeros; severe[0]=5.0 is still the worst year
    assert result[0].value == 1.0  # flag
    assert result[2].value == 5.0


# ---------------------------------------------------------------------------
# _local_graph_ui  (new)
# ---------------------------------------------------------------------------

def test_local_graph_ui() -> None:
    assert panels_module._local_graph_ui({}) is None
    assert panels_module._local_graph_ui({"ui": {"x": 1}}) == {"x": 1}
    assert panels_module._local_graph_ui({"local_info_text": "hello"}) == {"info_text": "hello"}
    assert panels_module._local_graph_ui({"ui": {"x": 1}, "local_info_text": "hi"}) == {
        "x": 1,
        "info_text": "hi",
    }


# ---------------------------------------------------------------------------
# _global_aggregate_recent_delta_headline  (new)
# ---------------------------------------------------------------------------

def _make_agg_store(metric, aggregation, time_axis, values):
    class _Store:
        aggregates = {
            (metric, aggregation): {
                "time_axis": time_axis,
                "regions": {"globe": {"values": values}},
            }
        }

    return _Store()


def test_global_aggregate_recent_delta_headline_success() -> None:
    years = list(range(1979, 2024))
    values = [float(10 + i * 0.05) for i in range(len(years))]
    store = _make_agg_store("tp_annual_total_mm", "mean", years, values)

    h = panels_module._global_aggregate_recent_delta_headline(
        tile_store=store,
        metric="tp_annual_total_mm",
        key="precip_global",
        label="Precip global",
        unit_in="mm",
        unit_out="mm",
        baseline_year=1979,
    )
    assert h.value is not None
    assert h.unit == "mm"
    assert h.period is not None


def test_global_aggregate_recent_delta_headline_temperature_unit_conversion() -> None:
    years = list(range(1979, 2024))
    values = [float(15 + i * 0.05) for i in range(len(years))]
    store = _make_agg_store("t2m_yearly_mean_c", "mean", years, values)

    h_c = panels_module._global_aggregate_recent_delta_headline(
        tile_store=store,
        metric="t2m_yearly_mean_c",
        key="t2m_recent_global",
        label="T global",
        unit_in="C",
        unit_out="C",
        baseline_year=1979,
    )
    store2 = _make_agg_store("t2m_yearly_mean_c", "mean", years, values)
    h_f = panels_module._global_aggregate_recent_delta_headline(
        tile_store=store2,
        metric="t2m_yearly_mean_c",
        key="t2m_recent_global",
        label="T global",
        unit_in="C",
        unit_out="F",
        baseline_year=1979,
    )
    assert h_f.unit == "F"
    assert h_f.value == pytest.approx(h_c.value * 1.8, abs=1e-3)


def test_global_aggregate_recent_delta_headline_missing() -> None:
    class _Empty:
        aggregates: dict = {}

    h = panels_module._global_aggregate_recent_delta_headline(
        tile_store=_Empty(),
        metric="m",
        key="k",
        label="L",
        unit_in="mm",
        unit_out="mm",
        baseline_year=1979,
    )
    assert h.value is None

    class _NoGlobe:
        aggregates = {("m", "mean"): {"time_axis": [2020], "regions": {}}}

    h2 = panels_module._global_aggregate_recent_delta_headline(
        tile_store=_NoGlobe(),
        metric="m",
        key="k",
        label="L",
        unit_in="mm",
        unit_out="mm",
        baseline_year=1979,
    )
    assert h2.value is None


# ---------------------------------------------------------------------------
# _global_aggregate_trend_headline  (new)
# ---------------------------------------------------------------------------

def test_global_aggregate_trend_headline_success() -> None:
    years = list(range(1979, 2024))
    values = [float(5 + i * 0.1) for i in range(len(years))]
    store = _make_agg_store("t2m_hotdays_per_year", "mean", years, values)

    h = panels_module._global_aggregate_trend_headline(
        tile_store=store,
        metric="t2m_hotdays_per_year",
        key="t2m_hotdays_global",
        label="Hot days global",
        unit="days",
        baseline_year=1979,
    )
    assert h.value is not None
    assert h.baseline_value is not None
    assert h.period == str(years[-1])


def test_global_aggregate_trend_headline_missing() -> None:
    class _Empty:
        aggregates: dict = {}

    h = panels_module._global_aggregate_trend_headline(
        tile_store=_Empty(),
        metric="m",
        key="k",
        label="L",
        unit="days",
        baseline_year=1979,
    )
    assert h.value is None


# ---------------------------------------------------------------------------
# _compute_global_t2m_preindustrial_headline  (new)
# ---------------------------------------------------------------------------

def test_compute_global_t2m_preindustrial_headline_success() -> None:
    class _Store:
        aggregates = {
            ("t2m_total_warming_vs_preindustrial_c", "mean"): {
                "time_axis": [2020, 2021, 2022, 2023],
                "regions": {"globe": {"values": [1.1, 1.15, 1.18, 1.2]}},
            }
        }

    h = panels_module._compute_global_t2m_preindustrial_headline(
        tile_store=_Store(), unit="C"
    )
    assert h.value == pytest.approx(1.2)
    assert h.period == "2023"

    h_f = panels_module._compute_global_t2m_preindustrial_headline(
        tile_store=_Store(), unit="F"
    )
    assert h_f.value == pytest.approx(1.2 * 1.8, abs=1e-3)


def test_compute_global_t2m_preindustrial_headline_missing() -> None:
    class _Empty:
        aggregates: dict = {}

    assert panels_module._compute_global_t2m_preindustrial_headline(
        tile_store=_Empty(), unit="C"
    ).value is None

    class _NoGlobe:
        aggregates = {
            ("t2m_total_warming_vs_preindustrial_c", "mean"): {
                "time_axis": [],
                "regions": {},
            }
        }

    assert panels_module._compute_global_t2m_preindustrial_headline(
        tile_store=_NoGlobe(), unit="C"
    ).value is None

    class _EmptyValues:
        aggregates = {
            ("t2m_total_warming_vs_preindustrial_c", "mean"): {
                "time_axis": [],
                "regions": {"globe": {"values": []}},
            }
        }

    assert panels_module._compute_global_t2m_preindustrial_headline(
        tile_store=_EmptyValues(), unit="C"
    ).value is None


# ---------------------------------------------------------------------------
# _dhw_info_bubble_text  (new)
# ---------------------------------------------------------------------------

def test_dhw_info_bubble_text_success() -> None:
    class _Store:
        aggregates = {
            ("dhw_severe_risk_days_per_year", "fraction_1pct"): {
                "aggregation": "fraction_1pct"
            }
        }

    text = panels_module._dhw_info_bubble_text(_Store())
    assert text is not None
    assert "99th percentile" in text
    assert "1%" in text


def test_dhw_info_bubble_text_missing() -> None:
    class _Empty:
        aggregates: dict = {}

    assert panels_module._dhw_info_bubble_text(_Empty()) is None

    class _WrongFormat:
        aggregates = {
            ("dhw_severe_risk_days_per_year", "fraction_1pct"): {
                "aggregation": "mean"
            }
        }

    assert panels_module._dhw_info_bubble_text(_WrongFormat()) is None


# ---------------------------------------------------------------------------
# _with_coral_info_bubble  (new)
# ---------------------------------------------------------------------------

def test_with_coral_info_bubble() -> None:
    class _NoAgg:
        aggregates: dict = {}

    assert panels_module._with_coral_info_bubble(None, _NoAgg()) is None
    assert panels_module._with_coral_info_bubble({"type": "temperature"}, _NoAgg()) == {"type": "temperature"}

    # Coral type but no aggregate -> spec returned unchanged
    spec = {"type": "coral", "info_bubble_texts": {"foo": "bar"}}
    assert panels_module._with_coral_info_bubble(spec, _NoAgg()) is spec

    class _WithAgg:
        aggregates = {
            ("dhw_severe_risk_days_per_year", "fraction_1pct"): {
                "aggregation": "fraction_1pct"
            }
        }

    result = panels_module._with_coral_info_bubble({"type": "coral", "info_bubble_texts": {"existing": "x"}}, _WithAgg())
    assert result is not None
    assert "trend" in result["info_bubble_texts"]
    assert "coral_unavailable" in result["info_bubble_texts"]
    assert result["info_bubble_texts"]["existing"] == "x"
