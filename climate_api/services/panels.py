from __future__ import annotations

from pathlib import Path
from typing import Dict, Any, List, Callable
import numpy as np
import math
from threading import Lock

from ..schemas import (
    PanelResponse,
    PanelListResponse,
    PanelPayload,
    ScoredPanelPayload,
    GraphPayload,
    GraphAnnotation,
    SeriesPayload,
    HeadlinePayload,
)
from ..cache import Cache
from ..schemas import (
    QueryPoint,
    PlaceInfo,
    DataCell,
    LocationInfo,
    PanelValidBBox,
    PanelCellIndex,
)
from ..store.place_resolver import PlaceResolver
from ..store.tile_data_store import TileDataStore
from climate.datasets.derive.series import rolling_mean_centered, linear_trend_line, c_to_f
from climate.registry.panels import DEFAULT_PANELS_PATH, load_panels
from climate.tiles.layout import GridSpec, locate_tile, cell_center_latlon

_SCORE_MAP_VALUES_CACHE: dict[str, np.ndarray] = {}
_SCORE_MAP_VALUES_CACHE_LOCK = Lock()
_HEADLINE_RECENT_YEARS = 5
_CMIP_OFFSET_METRIC = "t2m_cmip_offset_1979_2000_vs_1850_1900_mean_5models_c"


def preload_score_maps_cache(
    *,
    maps_manifest: dict[str, Any],
    tile_store: TileDataStore,
    maps_root: Path,
) -> tuple[int, int]:
    maps_specs = {
        key: spec
        for key, spec in maps_manifest.items()
        if key != "version" and isinstance(spec, dict) and spec.get("type") == "score"
    }
    loaded = 0
    skipped_constant = 0
    for map_id, map_spec in maps_specs.items():
        if map_spec.get("constant_score") is not None:
            skipped_constant += 1
            continue
        grid_id = str(map_spec.get("grid_id") or "")
        if not grid_id:
            source_metric = map_spec.get("source_metric")
            if not isinstance(source_metric, str) or not source_metric:
                raise KeyError(
                    f"Score map '{map_id}' must define grid_id or a valid source_metric."
                )
            grid_id = tile_store._metric_grid(source_metric).grid_id
        grid = _grid_from_id(grid_id)
        output = map_spec.get("output", {}) or {}
        binary_name = str(output.get("binary_filename") or f"{map_id}.i16.bin")
        bin_path = maps_root / grid.grid_id / map_id / binary_name
        expected = grid.nlat * grid.nlon
        _load_score_map_values_cached(bin_path=bin_path, expected=expected)
        loaded += 1
    return loaded, skipped_constant


def _format_delta(value_c: float, unit: str, *, decimals: int = 1, sign: bool = True) -> str:
    value = float(value_c)
    unit_upper = unit.upper()
    if unit_upper == "F":
        value = value * (9.0 / 5.0)
    if sign:
        return f"{value:+.{decimals}f}°{unit_upper}"
    return f"{value:.{decimals}f}°{unit_upper}"


def _fifty_year_caption_from_context(context: dict[str, Any]) -> str:
    data = dict(context.get("data") or {})
    place = dict(context.get("place") or {})
    unit = str(context.get("unit", "C") or "C").upper()
    city_name = str(place.get("label") or "this location")

    total_span_years_raw = data.get("total_span_years")
    total_warming_raw = data.get("total_warming")
    try:
        total_span_years = int(total_span_years_raw)
        total_warming = float(total_warming_raw)
    except Exception:
        total_span_years = 0
        total_warming = 0.0

    if total_span_years > 0:
        if abs(total_warming) < 0.15:
            change_text = (
                f"has changed very little (**{_format_delta(total_warming, unit)}**)."
            )
        elif total_warming > 0:
            change_text = (
                f"is now roughly **{_format_delta(total_warming, unit)} warmer on average** "
                f"than it was at the start of the record."
            )
        else:
            change_text = (
                f"is now roughly **{_format_delta(abs(total_warming), unit, sign=False)} cooler on average** "
                f"than it was at the start of the record."
            )

        extra_lines: list[str] = []
        cold_raw = data.get("coldest_month_trend_50y")
        warm_raw = data.get("warmest_month_trend_50y")
        if cold_raw is not None and warm_raw is not None:
            try:
                cold = float(cold_raw)
                warm = float(warm_raw)
            except Exception:
                cold = None
                warm = None
            if cold is not None and warm is not None:
                extra_lines.append(
                    "The dashed lines show how the coldest and warmest typical months behave:"
                )
                for label, value in (("coldest", cold), ("warmest", warm)):
                    if value > 0.3:
                        extra_lines.append(
                            f"- the **{label} month** is about **{_format_delta(value, unit)} warmer**."
                        )
                    elif value < -0.3:
                        extra_lines.append(
                            f"- the **{label} month** is about "
                            f"**{_format_delta(abs(value), unit, sign=False)} cooler**."
                        )
                    else:
                        extra_lines.append(
                            f"- the **{label} month** has changed by only about "
                            f"**{_format_delta(value, unit, decimals=2)}**."
                        )

        base = (
            f"When you zoom out over about **{total_span_years} years**, year-to-year noise fades. "
            f"In **{city_name}**, the climate {change_text}"
        )
        if extra_lines:
            return base + "\n\n" + "\n".join(extra_lines)
        return base

    return (
        f"When you zoom out over about **{total_span_years} years**, the data window is too short "
        f"to infer a robust long-term signal for **{city_name}**."
    )


def _caption_fn_registry() -> dict[str, Callable[[dict[str, Any]], str]]:
    return {
        "fifty_year_caption": _fifty_year_caption_from_context,
    }


def _caption_from_spec(
    spec: dict[str, Any],
    *,
    context: dict[str, Any],
) -> str | None:
    if not spec:
        return None
    ctype = spec.get("type")
    if ctype == "static":
        return str(spec.get("text", "")).strip() or None
    if ctype != "fn":
        return None

    fn_name = spec.get("fn")
    if not fn_name:
        return None

    fn_map = _caption_fn_registry()
    fn = fn_map.get(fn_name)
    if fn is None:
        raise KeyError(f"Unknown caption function: {fn_name}")

    params = spec.get("params", {})
    ctx_data = dict(context)
    ctx_data["params"] = params

    data = dict(ctx_data.get("data", {}))
    if isinstance(params, dict):
        data.update(params)
    ctx_data["data"] = data
    return fn(ctx_data)


def _series_key(series_spec: dict[str, Any]) -> str:
    key = series_spec.get("key")
    if isinstance(key, str) and key:
        return key
    metric = series_spec.get("metric", "series")
    transform = series_spec.get("transform")
    if isinstance(transform, dict):
        fn = transform.get("fn")
        if fn:
            return f"{metric}_{fn}"
    if isinstance(transform, str):
        return f"{metric}_{transform}"
    return metric


def _apply_transform(
    *,
    x: np.ndarray,
    y: np.ndarray,
    transform: dict[str, Any] | str | None,
) -> np.ndarray:
    if not transform:
        return y
    if isinstance(transform, str):
        fn = transform
        params = {}
    else:
        fn = transform.get("fn")
        params = transform.get("params", {})

    if fn == "rolling_mean":
        window = int(params.get("window", 5))
        return rolling_mean_centered(y, window=window)
    if fn == "linear_trend_line":
        return linear_trend_line(x, y)

    raise ValueError(f"Unsupported transform: {fn}")


def _convert_unit(y: np.ndarray, unit_in: str | None, unit_out: str) -> np.ndarray:
    if not unit_in:
        return y
    if unit_in.upper() == unit_out.upper():
        return y
    if unit_in.upper() == "C" and unit_out.upper() == "F":
        return c_to_f(y)
    if unit_in.upper() == "F" and unit_out.upper() == "C":
        return (y - 32.0) * (5.0 / 9.0)
    return y


def _annotation_text(kind: str, value: float, unit: str, label: str | None) -> str:
    prefix = f"{label}: " if label else ""
    return f"{prefix}{value:.2f}{unit}"


def _build_series_annotations(
    *,
    series_key: str,
    y: np.ndarray,
    unit: str,
    annotations: list[dict[str, Any]] | None,
) -> list[GraphAnnotation]:
    if not annotations:
        return []

    out: list[GraphAnnotation] = []
    finite = y[np.isfinite(y)]
    if finite.size == 0:
        return out

    for ann in annotations:
        kind = ann.get("type")
        label = ann.get("label")
        if kind == "min":
            val = float(np.min(finite))
            out.append(
                GraphAnnotation(
                    series_key=series_key,
                    text=_annotation_text("min", val, unit, label),
                )
            )
        elif kind == "max":
            val = float(np.max(finite))
            out.append(
                GraphAnnotation(
                    series_key=series_key,
                    text=_annotation_text("max", val, unit, label),
                )
            )
    return out


def _series_to_list(y: np.ndarray) -> list[float | None]:
    out: list[float | None] = []
    for v in y.tolist():
        fv = float(v)
        out.append(fv if math.isfinite(fv) else None)
    return out


def _axis_to_numeric(v: Any) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except Exception:
        pass
    try:
        dt = np.datetime64(str(v))
        return float(dt.astype("datetime64[s]").astype(np.int64))
    except Exception:
        return float("nan")


def _series_axis(tile_store: TileDataStore, metric: str, length: int) -> list[Any]:
    axis = tile_store.axis(metric)
    if axis:
        if len(axis) != length:
            # Partial/in-progress packaging can leave axis metadata temporarily out
            # of sync with tile vector length. Infer a compatible yearly axis when
            # possible instead of failing the whole panel response.
            try:
                axis_int = [int(v) for v in axis]
            except Exception:
                axis_int = []

            if axis_int:
                end_year = axis_int[-1]
                start_year = end_year - int(length) + 1
                return list(range(start_year, end_year + 1))

            if len(axis) > length:
                return list(axis[-length:])
            # Axis is shorter and non-numeric; pad deterministically from fallback.
            return list(
                range(tile_store.start_year_fallback, tile_store.start_year_fallback + length)
            )
        return list(axis)
    return list(
        range(tile_store.start_year_fallback, tile_store.start_year_fallback + length)
    )


def _to_unit_delta(value_c: float, unit: str) -> float:
    unit_upper = unit.upper()
    if unit_upper == "F":
        return value_c * (9.0 / 5.0)
    return value_c


def _compute_t2m_preindustrial_headline(
    *,
    tile_store: TileDataStore,
    lat: float,
    lon: float,
    unit: str,
) -> HeadlinePayload:
    current_metric = "t2m_yearly_mean_c"
    cmip_offset_metric = _CMIP_OFFSET_METRIC
    baseline_label = "1850-1900"
    method = "ERA5 recent 5y minus ERA5 1979-2000, plus precomputed CMIP 5-model mean offset"
    try:
        vec = tile_store.try_get_metric_vector(current_metric, lat, lon)
    except FileNotFoundError:
        vec = None
    if vec is None:
        return HeadlinePayload(
            key="t2m_vs_preindustrial_local",
            label="Air temperature change vs pre-industrial",
            value=None,
            unit=unit.upper(),
            baseline=baseline_label,
            period=f"latest {_HEADLINE_RECENT_YEARS}-year mean",
            method=method,
        )

    y = np.asarray(vec, dtype=np.float64).reshape(-1)
    axis_vals = _series_axis(tile_store, current_metric, y.size)
    year_vals = np.asarray([_axis_to_numeric(v) for v in axis_vals], dtype=np.float64)
    finite = np.isfinite(y) & np.isfinite(year_vals)
    years = year_vals.astype(np.int32, copy=False)

    finite_years = years[finite]
    if finite_years.size == 0:
        return HeadlinePayload(
            key="t2m_vs_preindustrial_local",
            label="Air temperature change vs pre-industrial",
            value=None,
            unit=unit.upper(),
            baseline=baseline_label,
            period=f"latest {_HEADLINE_RECENT_YEARS}-year mean",
            method=method,
        )
    latest_year = int(np.max(finite_years))
    recent_start = latest_year - (_HEADLINE_RECENT_YEARS - 1)
    recent_mask = finite & (years >= recent_start) & (years <= latest_year)
    era5_ref_mask = finite & (years >= 1979) & (years <= 2000)
    if int(np.count_nonzero(recent_mask)) < max(2, _HEADLINE_RECENT_YEARS - 1):
        return HeadlinePayload(
            key="t2m_vs_preindustrial_local",
            label="Air temperature change vs pre-industrial",
            value=None,
            unit=unit.upper(),
            baseline=baseline_label,
            period=f"{recent_start}-{latest_year}",
            method=method,
        )
    if int(np.count_nonzero(era5_ref_mask)) < 10:
        return HeadlinePayload(
            key="t2m_vs_preindustrial_local",
            label="Air temperature change vs pre-industrial",
            value=None,
            unit=unit.upper(),
            baseline=baseline_label,
            period=f"{recent_start}-{latest_year}",
            method=method,
        )

    era5_recent_local = float(np.mean(y[recent_mask]))
    era5_ref_local = float(np.mean(y[era5_ref_mask]))
    try:
        cmip_offset_vec = tile_store.try_get_metric_vector(cmip_offset_metric, lat, lon)
    except FileNotFoundError:
        cmip_offset_vec = None

    if cmip_offset_vec is None:
        return HeadlinePayload(
            key="t2m_vs_preindustrial_local",
            label="Air temperature change vs pre-industrial",
            value=None,
            unit=unit.upper(),
            baseline=baseline_label,
            period=f"{recent_start}-{latest_year}",
            method=method,
        )

    cmip_offset_vals = np.asarray(cmip_offset_vec, dtype=np.float64).reshape(-1)
    cmip_offset_finite = cmip_offset_vals[np.isfinite(cmip_offset_vals)]
    if cmip_offset_finite.size == 0:
        return HeadlinePayload(
            key="t2m_vs_preindustrial_local",
            label="Air temperature change vs pre-industrial",
            value=None,
            unit=unit.upper(),
            baseline=baseline_label,
            period=f"{recent_start}-{latest_year}",
            method=method,
        )

    delta_c = (era5_recent_local - era5_ref_local) + float(cmip_offset_finite[-1])
    delta = _to_unit_delta(delta_c, unit)

    return HeadlinePayload(
        key="t2m_vs_preindustrial_local",
        label="Air temperature change vs pre-industrial",
        value=float(delta),
        unit=unit.upper(),
        baseline=baseline_label,
        period=f"{recent_start}-{latest_year}",
        method=method,
    )


def build_panel_tiles_registry(
    *,
    place_resolver: PlaceResolver,
    tile_store: TileDataStore,
    cache: Cache | None,
    ttl_panel_s: int,
    release: str,
    lat: float,
    lon: float,
    unit: str,
    panel_id: str,
    panels_manifest: dict[str, Any] | None = None,
    selected_place: PlaceInfo | None = None,
) -> PanelResponse:
    unit = unit.upper()

    if panels_manifest is None:
        panels_manifest = load_panels(DEFAULT_PANELS_PATH, validate=True)

    panels = panels_manifest.get("panels", {})
    panel_spec = panels.get(panel_id)
    if panel_spec is None:
        raise KeyError(f"Unknown panel_id: {panel_id}")

    # Precompute grid cell indices for cache keying and reuse across series.
    metrics: set[str] = set()
    for graph in panel_spec.get("graphs", []):
        for series_spec in graph.get("series", []):
            metric = series_spec.get("metric")
            if metric:
                metrics.add(metric)

    grid_cells: dict[str, tuple[Any, Any, Any]] = {}
    for metric in sorted(metrics):
        grid = tile_store._metric_grid(metric)
        if grid.grid_id in grid_cells:
            continue
        cell, t = locate_tile(lat, lon, grid)
        grid_cells[grid.grid_id] = (grid, cell, t)

    cache_key_parts = [
        f"panel:{release}:registry:{panel_id}:{unit}",
        "cells",
    ]
    for grid_id in sorted(grid_cells.keys()):
        _grid, cell, _t = grid_cells[grid_id]
        cache_key_parts.append(f"{grid_id}:{cell.i_lat}:{cell.i_lon}")
    if selected_place is not None:
        cache_key_parts.append(f"selected:{int(selected_place.geonameid)}")
    cache_key = ":".join(cache_key_parts)

    if cache is not None:
        hit = cache.get_json(cache_key)
        if hit is not None:
            return PanelResponse.model_validate(hit)

    if selected_place is not None:
        place = selected_place
    else:
        place = place_resolver.resolve_place(lat, lon)

    series_payload: Dict[str, SeriesPayload] = {}
    graphs_out: List[GraphPayload] = []
    metric_vector_cache: dict[str, np.ndarray | None] = {}
    metric_axis_cache: dict[str, list[Any]] = {}
    metric_x_cache: dict[str, np.ndarray] = {}

    data_cells_map: dict[str, DataCell] = {}
    base_series_for_caption: tuple[list[int], np.ndarray] | None = None

    for graph in panel_spec.get("graphs", []):
        graph_series_keys: list[str] = []
        graph_annotations: list[GraphAnnotation] = []
        graph_caption: str | None = None
        graph_error: str | None = None
        missing = False

        for series_spec in graph.get("series", []):
            metric = series_spec.get("metric")
            if not metric:
                continue

            key = _series_key(series_spec)
            if key in series_payload:
                graph_series_keys.append(key)
                continue

            if metric in metric_vector_cache:
                vec = metric_vector_cache[metric]
            else:
                try:
                    vec = tile_store.try_get_metric_vector(metric, lat, lon)
                except FileNotFoundError:
                    metric_vector_cache[metric] = None
                    missing = True
                    continue
                metric_vector_cache[metric] = vec
            if vec is None:
                missing = True
                continue

            vec = np.asarray(vec, dtype=np.float32).reshape(-1)
            if metric in metric_axis_cache:
                axis_vals = metric_axis_cache[metric]
                x = metric_x_cache[metric]
            else:
                axis_vals = _series_axis(tile_store, metric, vec.size)
                x = np.asarray([_axis_to_numeric(v) for v in axis_vals], dtype=np.float64)
                metric_axis_cache[metric] = axis_vals
                metric_x_cache[metric] = x

            y = _apply_transform(x=x, y=vec, transform=series_spec.get("transform"))
            y = _convert_unit(y, series_spec.get("unit"), unit)

            series_payload[key] = SeriesPayload(
                x=list(axis_vals),
                y=_series_to_list(y),
                unit=unit,
                style=series_spec.get("style"),
            )
            graph_series_keys.append(key)

            if base_series_for_caption is None:
                if all(isinstance(v, (int, np.integer)) for v in axis_vals):
                    base_series_for_caption = ([int(v) for v in axis_vals], y)

            graph_annotations.extend(
                _build_series_annotations(
                    series_key=key,
                    y=y,
                    unit=unit,
                    annotations=series_spec.get("annotations"),
                )
            )

            grid = tile_store._metric_grid(metric)
            if grid.grid_id not in data_cells_map:
                if grid.grid_id in grid_cells:
                    _grid, cell, t = grid_cells[grid.grid_id]
                else:
                    cell, t = locate_tile(lat, lon, grid)
                latc, lonc = cell_center_latlon(cell.i_lat, cell.i_lon, grid)
                half = float(grid.deg) / 2.0
                data_cells_map[grid.grid_id] = DataCell(
                    grid=grid.grid_id,
                    i_lat=cell.i_lat,
                    i_lon=cell.i_lon,
                    deg=float(grid.deg),
                    lat_center=float(latc),
                    lon_center=float(lonc),
                    lat_min=float(latc - half),
                    lat_max=float(latc + half),
                    lon_min=float(lonc - half),
                    lon_max=float(lonc + half),
                    tile_r=int(t.tile_r),
                    tile_c=int(t.tile_c),
                    o_lat=int(t.o_lat),
                    o_lon=int(t.o_lon),
                )

        if missing:
            graph_error = "Missing data - graph can't be displayed."
            graph_series_keys = []
            graph_annotations = []
        elif graph.get("caption"):
            caption_ctx = _caption_context_from_series(
                axis_series=base_series_for_caption,
                unit=unit,
                place=place,
                lat=lat,
            )
            graph_caption = _caption_from_spec(graph.get("caption"), context=caption_ctx)

        graphs_out.append(
            GraphPayload(
                id=graph.get("id", ""),
                title=graph.get("title", ""),
                series_keys=graph_series_keys,
                annotations=graph_annotations,
                caption=graph_caption,
                error=graph_error,
                x_axis_label=graph.get("x_axis_label"),
                y_axis_label=graph.get("y_axis_label"),
                time_range=graph.get("time_range"),
                animation=graph.get("animation"),
            )
        )

    panel_out = PanelPayload(
        id=panel_id,
        title=panel_spec.get("title", panel_id),
        graphs=graphs_out,
        text_md=None,
    )

    panel_bbox = None
    if data_cells_map:
        lat_min = max(c.lat_min for c in data_cells_map.values())
        lat_max = min(c.lat_max for c in data_cells_map.values())
        lon_min = max(c.lon_min for c in data_cells_map.values())
        lon_max = min(c.lon_max for c in data_cells_map.values())
        panel_bbox = PanelValidBBox(
            lat_min=float(lat_min),
            lat_max=float(lat_max),
            lon_min=float(lon_min),
            lon_max=float(lon_max),
        )

    panel_cell_indices = None
    if grid_cells:
        panel_cell_indices = [
            PanelCellIndex(
                grid=grid_id,
                i_lat=int(cell.i_lat),
                i_lon=int(cell.i_lon),
            )
            for grid_id, (_grid, cell, _t) in sorted(grid_cells.items())
        ]

    loc_out = LocationInfo(
        query=QueryPoint(lat=float(lat), lon=float(lon)),
        place=PlaceInfo(
            geonameid=int(place.geonameid),
            label=place.label,
            lat=float(place.lat),
            lon=float(place.lon),
            distance_km=float(place.distance_km),
            country_code=place.country_code,
            population=place.population,
        ),
        data_cells=list(data_cells_map.values()),
        panel_valid_bbox=panel_bbox,
        panel_cell_indices=panel_cell_indices,
    )

    headlines = [
        _compute_t2m_preindustrial_headline(
            tile_store=tile_store,
            lat=lat,
            lon=lon,
            unit=unit,
        )
    ]

    resp = PanelResponse(
        release=release,
        unit=unit,
        location=loc_out,
        panel=panel_out,
        series=series_payload,
        headlines=headlines,
    )

    if cache is not None:
        cache.set_json(cache_key, resp.model_dump(mode="json"), ttl_s=ttl_panel_s)

    return resp


def build_scored_panels_tiles_registry(
    *,
    place_resolver: PlaceResolver,
    tile_store: TileDataStore,
    cache: Cache | None,
    ttl_panel_s: int,
    release: str,
    lat: float,
    lon: float,
    unit: str,
    panels_manifest: dict[str, Any],
    maps_manifest: dict[str, Any],
    maps_root: Path,
    selected_place: PlaceInfo | None = None,
) -> PanelListResponse:
    panels = panels_manifest.get("panels", {})
    if not isinstance(panels, dict):
        raise KeyError("Invalid panels manifest: missing 'panels' root object.")

    maps_specs = {
        key: spec
        for key, spec in maps_manifest.items()
        if key != "version" and isinstance(spec, dict)
    }
    scored_panel_ids: list[tuple[int, str]] = []
    for panel_id, panel_spec in panels.items():
        score_map_id = panel_spec.get("score_map_id")
        if not isinstance(score_map_id, str) or not score_map_id:
            raise KeyError(f"Panel '{panel_id}' is missing score_map_id.")
        map_spec = maps_specs.get(score_map_id)
        if map_spec is None:
            raise KeyError(f"Panel '{panel_id}' references unknown score map: {score_map_id}")
        if map_spec.get("type") != "score":
            raise KeyError(
                f"Panel '{panel_id}' references map '{score_map_id}' with unsupported type "
                f"'{map_spec.get('type')}'. Expected 'score'."
            )
        score = _read_score_value(
            lat=lat,
            lon=lon,
            map_id=score_map_id,
            map_spec=map_spec,
            tile_store=tile_store,
            maps_root=maps_root,
        )
        if score > 0:
            scored_panel_ids.append((score, panel_id))

    scored_panel_ids.sort(key=lambda item: item[0], reverse=True)

    merged_series: dict[str, SeriesPayload] = {}
    scored_panels: list[ScoredPanelPayload] = []
    location: LocationInfo | None = None
    for score, panel_id in scored_panel_ids:
        panel_resp = build_panel_tiles_registry(
            place_resolver=place_resolver,
            tile_store=tile_store,
            cache=cache,
            ttl_panel_s=ttl_panel_s,
            release=release,
            lat=lat,
            lon=lon,
            unit=unit,
            panel_id=panel_id,
            panels_manifest=panels_manifest,
            selected_place=selected_place,
        )
        if location is None:
            location = panel_resp.location
        for key, payload in panel_resp.series.items():
            if key not in merged_series:
                merged_series[key] = payload
        scored_panels.append(ScoredPanelPayload(score=score, panel=panel_resp.panel))

    if location is None:
        if selected_place is not None:
            place = selected_place
        else:
            place = place_resolver.resolve_place(lat, lon)
        location = LocationInfo(
            query=QueryPoint(lat=float(lat), lon=float(lon)),
            place=PlaceInfo(
                geonameid=int(place.geonameid),
                label=place.label,
                lat=float(place.lat),
                lon=float(place.lon),
                distance_km=float(place.distance_km),
                country_code=place.country_code,
                population=place.population,
            ),
            data_cells=[],
            panel_valid_bbox=None,
            panel_cell_indices=None,
        )
    headlines = [
        _compute_t2m_preindustrial_headline(
            tile_store=tile_store,
            lat=lat,
            lon=lon,
            unit=unit,
        )
    ]

    return PanelListResponse(
        release=release,
        unit=unit.upper(),
        location=location,
        panels=scored_panels,
        series=merged_series,
        headlines=headlines,
    )


def _grid_from_id(grid_id: str) -> GridSpec:
    if grid_id == "global_0p25":
        return GridSpec.global_0p25(tile_size=64)
    if grid_id == "global_0p05":
        return GridSpec.global_0p05(tile_size=64)
    raise KeyError(f"Unsupported map grid_id: {grid_id}")


def _read_score_value(
    *,
    lat: float,
    lon: float,
    map_id: str,
    map_spec: dict[str, Any],
    tile_store: TileDataStore,
    maps_root: Path,
) -> int:
    constant_score = map_spec.get("constant_score")
    if constant_score is not None:
        score = int(constant_score)
        if score < 0:
            return 0
        if score > 4:
            return 4
        return score

    score_values = None
    grid_id = str(map_spec.get("grid_id") or "")
    if not grid_id:
        source_metric = map_spec.get("source_metric")
        if not isinstance(source_metric, str) or not source_metric:
            raise KeyError(
                f"Score map '{map_id}' must define grid_id or a valid source_metric."
            )
        grid_id = tile_store._metric_grid(source_metric).grid_id
    grid = _grid_from_id(grid_id)
    if score_values is None:
        output = map_spec.get("output", {}) or {}
        binary_name = str(output.get("binary_filename") or f"{map_id}.i16.bin")
        bin_path = maps_root / grid.grid_id / map_id / binary_name
        expected = grid.nlat * grid.nlon
        score_values = _load_score_map_values_cached(bin_path=bin_path, expected=expected)

    cell, _tile = locate_tile(lat, lon, grid)
    idx = cell.i_lat * grid.nlon + cell.i_lon
    score = int(score_values[idx])
    if score < 0:
        return 0
    if score > 4:
        return 4
    return score


def _load_score_map_values_cached(*, bin_path: Path, expected: int) -> np.ndarray:
    cache_key = str(bin_path.resolve())
    with _SCORE_MAP_VALUES_CACHE_LOCK:
        cached = _SCORE_MAP_VALUES_CACHE.get(cache_key)
        if cached is not None:
            return cached

    if not bin_path.exists():
        raise FileNotFoundError(f"Missing score map binary: {bin_path}")
    raw = np.fromfile(bin_path, dtype="<i2")
    if raw.size != expected:
        raise ValueError(
            f"Score map '{bin_path.name}' has invalid size: {raw.size}, expected {expected}"
        )

    with _SCORE_MAP_VALUES_CACHE_LOCK:
        _SCORE_MAP_VALUES_CACHE[cache_key] = raw
    return raw


def _caption_context_from_series(
    *,
    axis_series: tuple[list[int], np.ndarray] | None,
    unit: str,
    place: PlaceInfo,
    lat: float,
) -> dict[str, Any]:
    years: list[int] = []
    y = np.array([], dtype=np.float32)
    if axis_series is not None:
        years, y = axis_series

    start_year = int(years[0]) if years else 0
    end_year = int(years[-1]) if years else 0
    total_span_years = int(end_year - start_year) if years else 0

    finite = y[np.isfinite(y)]
    total_warming = float(finite[-1] - finite[0]) if finite.size >= 2 else None

    hemisphere = "N" if lat >= 0 else "S"

    return {
        "place": {
            "geonameid": place.geonameid,
            "label": place.label,
            "lat": place.lat,
            "lon": place.lon,
        },
        "unit": unit,
        "facts": {
            "start_year": start_year,
            "end_year": end_year,
            "total_warming_50y": total_warming,
            "recent_warming_10y": None,
            "last_year_anomaly": None,
            "hemisphere": hemisphere,
        },
        "data": {
            "total_span_years": total_span_years,
            "total_warming": total_warming,
            "coldest_month_trend_50y": None,
            "warmest_month_trend_50y": None,
        },
    }
