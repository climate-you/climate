from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from climate.tiles.layout import GridSpec
from climate_api.schemas import (
    LocationInfo,
    PanelPayload,
    PanelResponse,
    PlaceInfo,
    QueryPoint,
)
from climate_api.services import panels as panels_module


class _MemCache:
    def __init__(self) -> None:
        self.data: dict[str, dict] = {}
        self.ttl: int | None = None

    def get_json(self, key: str):
        return self.data.get(key)

    def set_json(self, key: str, obj: dict, ttl_s: int) -> None:
        self.data[key] = obj
        self.ttl = ttl_s


class _TileStore:
    def __init__(self, grid: GridSpec) -> None:
        self.grid = grid
        self.start_year_fallback = 1979
        self.aggregates: dict = {}

    def _metric_grid(self, metric: str) -> GridSpec:
        return self.grid

    def axis(self, metric: str):
        if metric == "m_temp":
            return [2000, 2001, 2002]
        return list(range(1979, 2024))

    def try_get_metric_vector(self, metric: str, lat: float, lon: float):
        if metric == "m_temp":
            return np.array([1.0, 3.0, 2.0], dtype=np.float32)
        if metric == "missing_metric":
            raise FileNotFoundError("missing")
        if metric == "t2m_yearly_mean_c":
            return np.linspace(10.0, 12.2, num=45, dtype=np.float32)
        if metric == "t2m_cmip_offset_1979_2000_vs_1850_1900_mean_5models_c":
            return np.array([0.5], dtype=np.float32)
        return None


def _place_resolver() -> SimpleNamespace:
    return SimpleNamespace(
        resolve_place=lambda lat, lon: SimpleNamespace(
            geonameid=123,
            label="Test Place",
            lat=lat,
            lon=lon,
            distance_km=0.1,
            country_code="US",
            population=100,
        )
    )


def test_build_panel_tiles_registry_happy_path_and_cache_hit() -> None:
    grid = GridSpec.global_0p25(tile_size=64)
    store = _TileStore(grid)
    cache = _MemCache()
    manifest = {
        "panels": {
            "p1": {
                "title": "Panel One",
                "graphs": [
                    {
                        "id": "g1",
                        "title": "Graph One",
                        "series": [
                            {
                                "metric": "m_temp",
                                "unit": "C",
                                "annotations": [
                                    {"type": "min", "label": "Min"},
                                    {"type": "max"},
                                ],
                            }
                        ],
                        "caption": {"type": "static", "text": "hello"},
                    }
                ],
            }
        }
    }

    resp = panels_module.build_panel_tiles_registry(
        place_resolver=_place_resolver(),
        tile_store=store,
        cache=cache,
        ttl_panel_s=77,
        release="dev",
        lat=0.0,
        lon=0.0,
        unit="c",
        panel_id="p1",
        panels_manifest=manifest,
    )
    assert resp.unit == "C"
    assert resp.panel.graphs[0].caption == "hello"
    assert len(resp.panel.graphs[0].annotations) == 2
    assert resp.panel.graphs[0].series_keys == ["m_temp"]
    assert resp.location.panel_valid_bbox is not None
    assert resp.location.panel_bbox_grid_id == "global_0p25"
    assert resp.location.panel_cell_indices is not None
    assert cache.ttl == 77

    # Verify model_validate(cache-hit) branch by bypassing resolver execution.
    exploding_resolver = SimpleNamespace(
        resolve_place=lambda lat, lon: (_ for _ in ()).throw(
            AssertionError("should not be called")
        )
    )
    resp2 = panels_module.build_panel_tiles_registry(
        place_resolver=exploding_resolver,
        tile_store=store,
        cache=cache,
        ttl_panel_s=77,
        release="dev",
        lat=0.0,
        lon=0.0,
        unit="C",
        panel_id="p1",
        panels_manifest=manifest,
    )
    assert resp2.panel.id == "p1"
    assert resp2.location.place.geonameid == 123


def test_build_panel_tiles_registry_handles_missing_metric() -> None:
    grid = GridSpec.global_0p25(tile_size=64)
    store = _TileStore(grid)
    manifest = {
        "panels": {
            "p_missing": {
                "title": "Missing",
                "graphs": [
                    {
                        "id": "g_missing",
                        "title": "Graph Missing",
                        "series": [{"metric": "missing_metric"}],
                    }
                ],
            }
        }
    }
    resp = panels_module.build_panel_tiles_registry(
        place_resolver=_place_resolver(),
        tile_store=store,
        cache=None,
        ttl_panel_s=60,
        release="dev",
        lat=0.0,
        lon=0.0,
        unit="C",
        panel_id="p_missing",
        panels_manifest=manifest,
    )
    graph = resp.panel.graphs[0]
    assert graph.error is not None
    assert graph.series_keys == []


def test_build_panel_tiles_registry_unknown_panel_raises() -> None:
    grid = GridSpec.global_0p25(tile_size=64)
    with pytest.raises(KeyError, match="Unknown panel_id"):
        panels_module.build_panel_tiles_registry(
            place_resolver=_place_resolver(),
            tile_store=_TileStore(grid),
            cache=None,
            ttl_panel_s=10,
            release="dev",
            lat=0.0,
            lon=0.0,
            unit="C",
            panel_id="does_not_exist",
            panels_manifest={"panels": {}},
        )


def test_build_scored_panels_tiles_registry_success_and_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    place = PlaceInfo(
        geonameid=10,
        label="Sel",
        lat=1.0,
        lon=2.0,
        distance_km=0.0,
        country_code="US",
        population=10,
    )
    location = LocationInfo(
        query=QueryPoint(lat=1.0, lon=2.0),
        place=place,
        data_cells=[],
        panel_valid_bbox=None,
        panel_cell_indices=None,
    )

    def _panel_response(panel_id: str) -> PanelResponse:
        return PanelResponse(
            release="dev",
            unit="C",
            location=location,
            panel=PanelPayload(id=panel_id, title=panel_id, graphs=[]),
            series={"shared": {"x": [1], "y": [1.0]}, panel_id: {"x": [1], "y": [2.0]}},
            headlines=[],
        )

    monkeypatch.setattr(
        panels_module,
        "_read_score_value",
        lambda lat, lon, map_id, map_spec, tile_store, maps_root, map_artifact_roots=None: {
            "m1": 1,
            "m2": 3,
        }.get(
            map_id, 0
        ),
    )
    monkeypatch.setattr(
        panels_module,
        "build_panel_tiles_registry",
        lambda **kwargs: _panel_response(kwargs["panel_id"]),
    )
    monkeypatch.setattr(
        panels_module,
        "_compute_t2m_preindustrial_headline",
        lambda tile_store, lat, lon, unit: {
            "key": "x",
            "label": "x",
            "value": None,
            "unit": unit,
            "baseline": None,
            "period": None,
            "method": None,
        },
    )
    monkeypatch.setattr(
        panels_module,
        "_compute_t2m_recent_headline",
        lambda tile_store, lat, lon, unit: {
            "key": "t2m_recent_local",
            "label": "Air temperature recent change",
            "value": None,
            "unit": unit,
            "baseline": "1979",
            "period": "latest 5-year mean",
            "method": None,
        },
    )
    monkeypatch.setattr(
        panels_module,
        "_compute_sst_recent_headline",
        lambda tile_store, lat, lon, unit: {
            "key": "sst_recent_local",
            "label": "Sea surface temperature recent change",
            "value": None,
            "unit": unit,
            "baseline": "1982",
            "period": "latest 5-year mean",
            "method": None,
        },
    )
    monkeypatch.setattr(
        panels_module,
        "_compute_t2m_hotdays_headline",
        lambda tile_store, lat, lon: {
            "key": "t2m_hotdays_local",
            "label": "Air hot days per year",
            "value": None,
            "unit": "days",
            "baseline": "1979",
            "period": None,
            "method": None,
        },
    )
    monkeypatch.setattr(
        panels_module,
        "_compute_sst_hotdays_headline",
        lambda tile_store, lat, lon: {
            "key": "sst_hotdays_local",
            "label": "Sea surface hot days per year",
            "value": None,
            "unit": "days",
            "baseline": "1982",
            "period": None,
            "method": None,
        },
    )
    monkeypatch.setattr(
        panels_module,
        "_compute_precip_headline",
        lambda tile_store, lat, lon: {
            "key": "precip_local",
            "label": "Annual precipitation",
            "value": None,
            "unit": "mm",
            "baseline": "1979",
            "period": None,
            "method": None,
        },
    )
    monkeypatch.setattr(
        panels_module,
        "_compute_cdd_headline",
        lambda tile_store, lat, lon: {
            "key": "cdd_local",
            "label": "Consecutive dry days per year",
            "value": None,
            "unit": "days",
            "baseline": "1979",
            "period": None,
            "method": None,
        },
    )
    monkeypatch.setattr(
        panels_module,
        "_compute_coral_local_headlines",
        lambda tile_store, lat, lon: [],
    )
    monkeypatch.setattr(
        panels_module,
        "_compute_global_t2m_preindustrial_headline",
        lambda tile_store, unit: {
            "key": "t2m_vs_preindustrial_global",
            "label": "Air temperature change vs pre-industrial (global)",
            "value": None,
            "unit": unit,
            "baseline": "1850-1900",
            "period": None,
            "method": None,
        },
    )
    monkeypatch.setattr(
        panels_module,
        "_global_aggregate_recent_delta_headline",
        lambda **kwargs: {
            "key": kwargs["key"],
            "label": kwargs["label"],
            "value": None,
            "unit": kwargs["unit_out"],
            "baseline": str(kwargs["baseline_year"]),
            "period": None,
            "method": None,
        },
    )
    monkeypatch.setattr(
        panels_module,
        "_global_aggregate_trend_headline",
        lambda **kwargs: {
            "key": kwargs["key"],
            "label": kwargs["label"],
            "value": None,
            "unit": kwargs["unit"],
            "baseline": str(kwargs["baseline_year"]),
            "period": None,
            "method": None,
        },
    )

    scored = panels_module.build_scored_panels_tiles_registry(
        place_resolver=_place_resolver(),
        tile_store=SimpleNamespace(),
        cache=None,
        ttl_panel_s=60,
        release="dev",
        lat=1.0,
        lon=2.0,
        unit="c",
        panels_manifest={
            "panels": {"p1": {"score_map_id": "m1"}, "p2": {"score_map_id": "m2"}}
        },
        maps_manifest={"m1": {"type": "score"}, "m2": {"type": "score"}},
        maps_root=Path("/tmp"),
    )
    assert [p.panel.id for p in scored.panels] == ["p2", "p1"]
    assert "shared" in scored.series and "p1" in scored.series and "p2" in scored.series

    # No scored panels: fallback to selected place path.
    monkeypatch.setattr(
        panels_module,
        "_read_score_value",
        lambda lat, lon, map_id, map_spec, tile_store, maps_root, map_artifact_roots=None: 0,
    )
    empty = panels_module.build_scored_panels_tiles_registry(
        place_resolver=_place_resolver(),
        tile_store=SimpleNamespace(),
        cache=None,
        ttl_panel_s=60,
        release="dev",
        lat=1.0,
        lon=2.0,
        unit="F",
        panels_manifest={"panels": {"p1": {"score_map_id": "m1"}}},
        maps_manifest={"m1": {"type": "score"}},
        maps_root=Path("/tmp"),
        selected_place=place,
    )
    assert len(empty.panels) == 1
    assert empty.panels[0].score == 0
    assert empty.panels[0].panel.id == "p1"
    assert empty.location.place.geonameid == place.geonameid

    # No selected place and no scored panels -> resolve_place fallback branch.
    empty2 = panels_module.build_scored_panels_tiles_registry(
        place_resolver=_place_resolver(),
        tile_store=SimpleNamespace(),
        cache=None,
        ttl_panel_s=60,
        release="dev",
        lat=1.0,
        lon=2.0,
        unit="F",
        panels_manifest={"panels": {"p1": {"score_map_id": "m1"}}},
        maps_manifest={"m1": {"type": "score"}},
        maps_root=Path("/tmp"),
        selected_place=None,
    )
    assert empty2.location.place.label == "Test Place"


def test_build_panel_tiles_registry_misc_internal_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    grid_a = GridSpec.global_0p25(tile_size=64)
    grid_b = GridSpec.global_0p05(tile_size=64)

    class _WeirdStore:
        def __init__(self) -> None:
            self.start_year_fallback = 1979
            self.calls = 0
            self.aggregates: dict = {}

        def _metric_grid(self, metric: str):
            self.calls += 1
            return grid_a if self.calls == 1 else grid_b

        def axis(self, metric: str):
            return [2000]

        def try_get_metric_vector(self, metric: str, lat: float, lon: float):
            if metric == "m_none":
                return None
            return np.array([1.0], dtype=np.float32)

    class _CaptureCache:
        def __init__(self) -> None:
            self.last_key = None
            self.val = None

        def get_json(self, key: str):
            self.last_key = key
            return None

        def set_json(self, key: str, obj: dict, ttl_s: int):
            self.last_key = key
            self.val = obj

    capture = _CaptureCache()
    selected = PlaceInfo(
        geonameid=999,
        label="Selected",
        lat=0.0,
        lon=0.0,
        distance_km=0.0,
        country_code="US",
        population=1,
    )
    manifest = {
        "panels": {
            "p": {
                "graphs": [
                    {
                        "id": "g",
                        "title": "G",
                        "series": [
                            {"metric": None},  # line 543 branch
                            {"metric": "m_none"},  # vec None branch
                            {"metric": "m_ok"},
                        ],
                    }
                ],
            }
        }
    }
    monkeypatch.setattr(
        panels_module,
        "locate_tile",
        lambda lat, lon, grid: (
            SimpleNamespace(i_lat=0, i_lon=0),
            SimpleNamespace(tile_r=0, tile_c=0, o_lat=0, o_lon=0),
        ),
    )
    monkeypatch.setattr(
        panels_module, "cell_center_latlon", lambda i_lat, i_lon, grid: (0.0, 0.0)
    )
    monkeypatch.setattr(
        panels_module,
        "_compute_t2m_preindustrial_headline",
        lambda tile_store, lat, lon, unit: {
            "key": "k",
            "label": "l",
            "value": None,
            "unit": unit,
            "baseline": None,
            "period": None,
            "method": None,
        },
    )

    resp = panels_module.build_panel_tiles_registry(
        place_resolver=_place_resolver(),
        tile_store=_WeirdStore(),
        cache=capture,
        ttl_panel_s=1,
        release="dev",
        lat=0.0,
        lon=0.0,
        unit="C",
        panel_id="p",
        panels_manifest=manifest,
        selected_place=selected,
    )
    assert "selected:999" in str(capture.last_key)
    assert resp.location.place.geonameid == 999
    assert resp.panel.graphs[0].error is not None


def test_build_panel_tiles_registry_uses_0p05_bbox_in_sparse_risk_zone(
    tmp_path: Path,
) -> None:
    sparse_mask_path = tmp_path / "aux" / "sparse_risk_global_0p25_mask.npz"
    sparse_mask_path.parent.mkdir(parents=True, exist_ok=True)
    mask = np.zeros((720, 1440), dtype=np.uint8)
    # Query point (0, 0) maps to i_lat=360, i_lon=720 on global_0p25.
    mask[360, 720] = 1
    np.savez_compressed(
        sparse_mask_path,
        data=mask,
        deg=np.float64(0.25),
        lat_max=np.float64(90.0),
        lon_min=np.float64(-180.0),
    )

    class _MixedGridStore:
        def __init__(self) -> None:
            self.start_year_fallback = 1979
            self.aggregates: dict = {}

        def _metric_grid(self, metric: str) -> GridSpec:
            if metric == "m_reef":
                return GridSpec.global_0p05(tile_size=64)
            return GridSpec.global_0p25(tile_size=64)

        def axis(self, metric: str):
            return [2000, 2001, 2002]

        def try_get_metric_vector(self, metric: str, lat: float, lon: float):
            if metric == "m_temp":
                return np.array([1.0, 2.0, 3.0], dtype=np.float32)
            if metric == "m_reef":
                return None
            if metric == "t2m_yearly_mean_c":
                return np.linspace(10.0, 12.2, num=45, dtype=np.float32)
            if metric == "t2m_cmip_offset_1979_2000_vs_1850_1900_mean_5models_c":
                return np.array([0.5], dtype=np.float32)
            return None

    manifest = {
        "panels": {
            "p_sparse": {
                "title": "Sparse Panel",
                "graphs": [
                    {
                        "id": "g_sparse",
                        "title": "Sparse Graph",
                        "series": [
                            {"metric": "m_temp", "unit": "C"},
                            {"metric": "m_reef", "unit": "C"},
                        ],
                    }
                ],
            }
        }
    }

    resp = panels_module.build_panel_tiles_registry(
        place_resolver=_place_resolver(),
        tile_store=_MixedGridStore(),
        cache=None,
        ttl_panel_s=60,
        release="dev",
        lat=0.0,
        lon=0.0,
        unit="C",
        panel_id="p_sparse",
        panels_manifest=manifest,
        release_root=tmp_path,
    )
    assert resp.location.panel_valid_bbox is not None
    assert resp.location.panel_bbox_grid_id == "global_0p05"
    bbox = resp.location.panel_valid_bbox
    assert (bbox.lat_max - bbox.lat_min) == pytest.approx(0.05)
    assert (bbox.lon_max - bbox.lon_min) == pytest.approx(0.05)


def test_build_panel_tiles_registry_loads_default_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    grid = GridSpec.global_0p25(tile_size=64)
    store = _TileStore(grid)
    monkeypatch.setattr(
        panels_module,
        "load_panels",
        lambda path, validate=True: {
            "panels": {
                "p_auto": {
                    "graphs": [
                        {
                            "id": "g",
                            "title": "G",
                            "series": [{"metric": "m_temp", "unit": "C"}],
                        }
                    ]
                }
            }
        },
    )
    resp = panels_module.build_panel_tiles_registry(
        place_resolver=_place_resolver(),
        tile_store=store,
        cache=None,
        ttl_panel_s=5,
        release="dev",
        lat=0.0,
        lon=0.0,
        unit="C",
        panel_id="p_auto",
        panels_manifest=None,
    )
    assert resp.panel.id == "p_auto"


# ---------------------------------------------------------------------------
# Score=0 panels produce stub graphs (new behaviour)
# ---------------------------------------------------------------------------


def test_build_scored_panels_score_zero_produces_stub_panels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Panels with score=0 must appear as stub ScoredPanelPayloads with empty
    series_keys and an error string, not be silently dropped."""
    monkeypatch.setattr(panels_module, "_read_score_value", lambda *_a, **_kw: 0)

    _nh = {
        "key": "x",
        "label": "x",
        "value": None,
        "unit": "C",
        "baseline": None,
        "period": None,
        "method": None,
    }
    _nhd = {**_nh, "unit": "days"}

    # Stub all headline functions so SimpleNamespace tile_store is sufficient.
    for _name in (
        "_compute_t2m_preindustrial_headline",
        "_compute_t2m_recent_headline",
        "_compute_sst_recent_headline",
        "_compute_t2m_hotdays_headline",
        "_compute_sst_hotdays_headline",
        "_compute_precip_headline",
        "_compute_cdd_headline",
        "_compute_global_t2m_preindustrial_headline",
    ):
        monkeypatch.setattr(panels_module, _name, lambda *_a, **_kw: _nh)
    monkeypatch.setattr(
        panels_module, "_compute_coral_local_headlines", lambda *_a, **_kw: []
    )
    monkeypatch.setattr(
        panels_module, "_global_aggregate_recent_delta_headline", lambda *_a, **_kw: _nh
    )
    monkeypatch.setattr(
        panels_module, "_global_aggregate_trend_headline", lambda *_a, **_kw: _nhd
    )

    from types import SimpleNamespace

    result = panels_module.build_scored_panels_tiles_registry(
        place_resolver=_place_resolver(),
        tile_store=SimpleNamespace(aggregates={}),
        cache=None,
        ttl_panel_s=60,
        release="dev",
        lat=0.0,
        lon=0.0,
        unit="C",
        panels_manifest={
            "panels": {
                "p_coral": {
                    "title": "Coral",
                    "score_map_id": "m_coral",
                    "graphs": [
                        {"id": "g1", "title": "Graph 1"},
                        {"id": "g2", "title": "Graph 2"},
                    ],
                }
            }
        },
        maps_manifest={"m_coral": {"type": "score", "constant_score": 0}},
        maps_root=Path("/tmp"),
    )
    assert len(result.panels) == 1
    panel = result.panels[0]
    assert panel.score == 0
    assert panel.panel.id == "p_coral"
    assert len(panel.panel.graphs) == 2
    for g in panel.panel.graphs:
        assert g.series_keys == []
        assert g.error is not None


# ---------------------------------------------------------------------------
# global_only series are skipped in local panel build (new behaviour)
# ---------------------------------------------------------------------------


def test_build_panel_tiles_registry_skips_global_only_series() -> None:
    grid = GridSpec.global_0p25(tile_size=64)
    store = _TileStore(grid)
    manifest = {
        "panels": {
            "p_mixed": {
                "title": "Mixed",
                "graphs": [
                    {
                        "id": "g",
                        "title": "G",
                        "series": [
                            {"metric": "m_temp", "unit": "C"},
                            {"metric": "m_temp", "unit": "C", "global_only": True},
                        ],
                    }
                ],
            }
        }
    }
    resp = panels_module.build_panel_tiles_registry(
        place_resolver=_place_resolver(),
        tile_store=store,
        cache=None,
        ttl_panel_s=60,
        release="dev",
        lat=0.0,
        lon=0.0,
        unit="C",
        panel_id="p_mixed",
        panels_manifest=manifest,
    )
    # The global_only series must NOT appear in series_keys
    keys = resp.panel.graphs[0].series_keys
    assert len(keys) == 1
    assert keys[0] == "m_temp"


# ---------------------------------------------------------------------------
# Animation steps filtered to only include locally-available series (new behaviour)
# ---------------------------------------------------------------------------


def test_build_panel_tiles_registry_animation_filtering() -> None:
    grid = GridSpec.global_0p25(tile_size=64)
    store = _TileStore(grid)

    # m_temp is available; missing_metric raises FileNotFoundError (not available)
    manifest = {
        "panels": {
            "p_anim": {
                "title": "Animated",
                "graphs": [
                    {
                        "id": "g_anim",
                        "title": "G Anim",
                        "series": [
                            {"metric": "m_temp", "unit": "C"},
                        ],
                        "animation": {
                            "steps": [
                                {"series_keys": ["m_temp"], "label": "Step A"},
                                {"series_keys": ["missing_metric"], "label": "Step B"},
                                {"series_keys": ["m_temp"], "label": "Step C"},
                            ]
                        },
                    }
                ],
            }
        }
    }
    resp = panels_module.build_panel_tiles_registry(
        place_resolver=_place_resolver(),
        tile_store=store,
        cache=None,
        ttl_panel_s=60,
        release="dev",
        lat=0.0,
        lon=0.0,
        unit="C",
        panel_id="p_anim",
        panels_manifest=manifest,
    )
    graph = resp.panel.graphs[0]
    # Two steps reference m_temp (available) so animation should be kept with those two steps
    assert graph.animation is not None
    steps = graph.animation["steps"]
    assert len(steps) == 2
    for step in steps:
        assert "missing_metric" not in step["series_keys"]


def test_build_panel_tiles_registry_animation_dropped_when_only_one_step_survives() -> (
    None
):
    grid = GridSpec.global_0p25(tile_size=64)
    store = _TileStore(grid)

    manifest = {
        "panels": {
            "p_anim2": {
                "title": "Anim2",
                "graphs": [
                    {
                        "id": "g2",
                        "title": "G2",
                        "series": [{"metric": "m_temp", "unit": "C"}],
                        "animation": {
                            "steps": [
                                {"series_keys": ["m_temp"], "label": "Only Step"},
                                {"series_keys": ["missing_metric"], "label": "Missing"},
                            ]
                        },
                    }
                ],
            }
        }
    }
    resp = panels_module.build_panel_tiles_registry(
        place_resolver=_place_resolver(),
        tile_store=store,
        cache=None,
        ttl_panel_s=60,
        release="dev",
        lat=0.0,
        lon=0.0,
        unit="C",
        panel_id="p_anim2",
        panels_manifest=manifest,
    )
    # Only one valid step survives → animation should be None (can't animate a single step)
    assert resp.panel.graphs[0].animation is None
