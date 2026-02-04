from __future__ import annotations

from typing import Dict, Any, List, Callable
import numpy as np
import xarray as xr
import math
from datetime import date

from ..schemas import (
    PanelResponse,
    PanelPayload,
    GraphPayload,
    GraphAnnotation,
    SeriesPayload,
)
from ..cache import Cache
from ..schemas import QueryPoint, PlaceInfo, DataCell, LocationInfo
from ..store.place_resolver import PlaceResolver
from ..store.tile_data_store import TileDataStore
from climate.datasets.derive.series import rolling_mean_centered, linear_trend_line, c_to_f
from climate.registry.panels import DEFAULT_PANELS_PATH, load_panels
from climate.models import StoryContext, StoryFacts
from climate.panels.zoomout import fifty_year_caption
from climate.tiles.layout import locate_tile, cell_center_latlon


def _caption_fn_registry() -> dict[str, Callable[..., str]]:
    return {
        "fifty_year_caption": fifty_year_caption,
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
    facts_data = ctx_data.get("facts", {})
    place = ctx_data.get("place", {})
    unit = ctx_data.get("unit", "C")

    ctx = StoryContext(
        today=date.today(),
        slug=str(place.get("slug", "")),
        location_label=str(place.get("label", "")),
        city_name=str(place.get("label", "")),
        location_lat=float(place.get("lat", 0.0)),
        location_lon=float(place.get("lon", 0.0)),
        unit=str(unit),
        ds=xr.Dataset(),
    )
    facts = StoryFacts(
        data_start_year=int(facts_data.get("start_year", 0)),
        data_end_year=int(facts_data.get("end_year", 0)),
        total_warming_50y=facts_data.get("total_warming_50y"),
        recent_warming_10y=facts_data.get("recent_warming_10y"),
        last_year_anomaly=facts_data.get("last_year_anomaly"),
        hemisphere=str(facts_data.get("hemisphere", "")),
    )

    return fn(ctx, facts, data)


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


def _series_year_axis(tile_store: TileDataStore, metric: str, length: int) -> list[int]:
    axis = tile_store.axis(metric)
    if axis:
        return [int(v) for v in axis]
    return list(
        range(tile_store.start_year_fallback, tile_store.start_year_fallback + length)
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
) -> PanelResponse:
    unit = unit.upper()
    cache_key = f"panel:{release}:registry:{panel_id}:{unit}:{lat:.4f}:{lon:.4f}"

    if cache is not None:
        hit = cache.get_json(cache_key)
        if hit is not None:
            return PanelResponse.model_validate(hit)

    if panels_manifest is None:
        panels_manifest = load_panels(DEFAULT_PANELS_PATH, validate=True)

    panels = panels_manifest.get("panels", {})
    panel_spec = panels.get(panel_id)
    if panel_spec is None:
        raise KeyError(f"Unknown panel_id: {panel_id}")

    place = place_resolver.resolve_place(lat, lon)

    series_payload: Dict[str, SeriesPayload] = {}
    graphs_out: List[GraphPayload] = []

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

            try:
                vec = tile_store.try_get_metric_vector(metric, lat, lon)
            except FileNotFoundError:
                missing = True
                continue
            if vec is None:
                missing = True
                continue

            vec = np.asarray(vec, dtype=np.float32).reshape(-1)
            axis_years = _series_year_axis(tile_store, metric, vec.size)
            x = np.asarray(axis_years, dtype=np.int32)
            if x.size != vec.size:
                raise RuntimeError(
                    f"Axis length {x.size} != series length {vec.size} for {metric}"
                )

            y = _apply_transform(x=x, y=vec, transform=series_spec.get("transform"))
            y = _convert_unit(y, series_spec.get("unit"), unit)

            series_payload[key] = SeriesPayload(
                x=[int(v) for v in x.tolist()],
                y=_series_to_list(y),
                unit=unit,
                style=series_spec.get("style"),
            )
            graph_series_keys.append(key)

            if base_series_for_caption is None:
                base_series_for_caption = (axis_years, y)

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
            )
        )

    panel_out = PanelPayload(
        id=panel_id,
        title=panel_spec.get("title", panel_id),
        graphs=graphs_out,
        text_md=None,
    )

    loc_out = LocationInfo(
        query=QueryPoint(lat=float(lat), lon=float(lon)),
        place=PlaceInfo(
            slug=place.slug,
            label=place.label,
            lat=float(place.lat),
            lon=float(place.lon),
            distance_km=float(place.distance_km),
        ),
        data_cells=list(data_cells_map.values()),
    )

    resp = PanelResponse(
        release=release,
        unit=unit,
        location=loc_out,
        panel=panel_out,
        series=series_payload,
    )

    if cache is not None:
        cache.set_json(cache_key, resp.model_dump(mode="json"), ttl_s=ttl_panel_s)

    return resp


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
            "slug": place.slug,
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
