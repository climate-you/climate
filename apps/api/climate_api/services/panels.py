from __future__ import annotations

from typing import Dict, Any, List, Tuple
import numpy as np
import xarray as xr
import pandas as pd
import math

from ..registry import Registry
from ..schemas import (
    PanelResponse,
    PanelPayload,
    GraphPayload,
    GraphAnnotation,
    SeriesPayload,
    LocationInfo,
)
from ..units import convert_series
from ..textgen import make_panel_caption
from ..store.base import Store
from ..cache import Cache
from ..config import Settings
from ..grids import snap_cell
from ..schemas import QueryPoint, PlaceInfo, DataCell, LocationInfo
from ..captions.t2m_demo import caption_t2m_demo
from .derive import linear_trend
from ..store.place_resolver import PlaceResolver
from ..store.tile_data_store import (
    TileDataStore,
    rolling_mean_centered,
    linear_trend_line,
    c_to_f,
)
from climate.tiles.layout import locate_tile, cell_center_latlon
from climate.tiles.layout import tile_path


def _ensure_t2m_last50_derived(ds: xr.Dataset) -> tuple[xr.Dataset, dict[str, float]]:
    """
    Adds derived variables to ds (in-memory):
      - t2m_yearly_mean_trend_c
      - t2m_yearly_coldest_month_trend_c
      - t2m_yearly_warmest_month_trend_c

    Returns (ds, deltas) where deltas are the trend deltas in C over the period.
    """
    needed = {
        "t2m_yearly_mean_trend_c",
        "t2m_yearly_coldest_month_trend_c",
        "t2m_yearly_warmest_month_trend_c",
    }
    if all(k in ds for k in needed):
        return ds, {}

    # 1) Yearly mean trend from existing yearly series
    if "t2m_yearly_mean_c" not in ds:
        return ds, {}

    y_year = ds["t2m_yearly_mean_c"].values.astype(float)
    tr = linear_trend(y_year)
    ds["t2m_yearly_mean_trend_c"] = xr.DataArray(
        tr.yhat.astype("float32"),
        dims=ds["t2m_yearly_mean_c"].dims,
        coords=ds["t2m_yearly_mean_c"].coords,
    )

    # 2) Coldest/warmest month per year based on monthly series
    # We compute annual min/max of monthly means, then fit a trend line over years.
    if "t2m_monthly_mean_c" in ds and "time_monthly" in ds["t2m_monthly_mean_c"].coords:
        tm = pd.to_datetime(ds["time_monthly"].values)
        y_month = ds["t2m_monthly_mean_c"].values.astype(float)

        df = pd.DataFrame({"time": tm, "y": y_month})
        df["year"] = df["time"].dt.year

        per_year_min = df.groupby("year")["y"].min().to_numpy()
        per_year_max = df.groupby("year")["y"].max().to_numpy()

        # Align to the same year axis as your yearly series if possible
        years_yearly = (
            pd.to_datetime(ds["time_yearly"].values).year
            if "time_yearly" in ds.coords
            else None
        )
        if years_yearly is not None:
            # build a mapping year -> min/max
            g = df.groupby("year")["y"]
            min_map = g.min().to_dict()
            max_map = g.max().to_dict()
            per_year_min = np.array(
                [min_map.get(int(y), np.nan) for y in years_yearly], dtype=float
            )
            per_year_max = np.array(
                [max_map.get(int(y), np.nan) for y in years_yearly], dtype=float
            )

        tr_min = linear_trend(per_year_min)
        tr_max = linear_trend(per_year_max)

        # Use yearly axis coords (time_yearly) for the trend series
        if "time_yearly" in ds.coords:
            coords = {"time_yearly": ds["time_yearly"].values}
            dims = ("time_yearly",)
        else:
            # fallback
            coords = {}
            dims = ds["t2m_yearly_mean_c"].dims

        ds["t2m_yearly_coldest_month_trend_c"] = xr.DataArray(
            tr_min.yhat.astype("float32"), dims=dims, coords=coords
        )
        ds["t2m_yearly_warmest_month_trend_c"] = xr.DataArray(
            tr_max.yhat.astype("float32"), dims=dims, coords=coords
        )

        return ds, {
            "mean": float(tr.delta),
            "coldest": float(tr_min.delta),
            "warmest": float(tr_max.delta),
        }

    return ds, {"mean": float(tr.delta)}


def _series_xy_from_da(da: xr.DataArray) -> tuple[list[Any], list[float]]:
    """
    Extract (x, y) from a DataArray with any of:
      - time coord
      - year coord
      - month coord
    No assumptions about length.
    """
    # Choose the first coordinate that matches common names
    for coord in (
        "time_yearly",
        "time_monthly",
        "time",
        "time_ocean",
        "year",
        "year_ocean",
        "month",
    ):
        if coord in da.coords:
            x = da[coord].values
            # Convert numpy datetime64 to ISO strings for JSON safety
            if np.issubdtype(x.dtype, np.datetime64):
                x_out = [str(v)[:10] for v in x.astype("datetime64[D]")]
            else:
                x_list = x.tolist()
                x_out = [
                    (
                        int(v)
                        if isinstance(v, (int, np.integer))
                        else float(v) if isinstance(v, (float, np.floating)) else str(v)
                    )  # e.g. if it's something odd, keep it JSON-safe
                    for v in x_list
                ]
            y = da.values
            y_list = np.asarray(y).reshape(-1).tolist()
            y_out: list[float | None] = []
            for v in y_list:
                fv = float(v)
                y_out.append(fv if math.isfinite(fv) else None)
            return x_out, y_out

    # Fallback: 0..N-1
    y = da.values
    y_list = np.asarray(y).reshape(-1).tolist()
    y_out: list[float | None] = []
    for v in y_list:
        fv = float(v)
        y_out.append(fv if math.isfinite(fv) else None)
    x_out = list(range(len(y_out)))
    return x_out, y_out


def build_panel_tiles_t2m_50y(
    *,
    place_resolver: PlaceResolver,
    tile_store: TileDataStore,
    cache: Cache | None,
    ttl_panel_s: int,
    release: str,
    lat: float,
    lon: float,
    unit: str,
) -> PanelResponse:
    """
    Build a tile-backed panel for v0:
      annual mean t2m + 5y mean + trend
    """
    unit = unit.upper()

    # Snap to the tile grid cell using the grid spec (single source of truth)
    grid = tile_store.grid
    cell, t = locate_tile(lat, lon, grid)
    i_lat, i_lon = cell.i_lat, cell.i_lon

    latc, lonc = cell_center_latlon(i_lat, i_lon, grid)
    latc = float(latc)
    lonc = float(lonc)

    half = float(grid.deg) / 2.0
    lat_min = latc - half
    lat_max = latc + half
    lon_min = lonc - half
    lon_max = lonc + half

    cache_key = f"panel:{release}:t2m_50y:{unit}:{i_lat}:{i_lon}"

    if cache is not None:
        hit = cache.get_json(cache_key)
        if hit is not None:
            return PanelResponse.model_validate(hit)

    # Place label (nearest from locations.csv)
    place = place_resolver.resolve_place(lat, lon)

    metric = "t2m_yearly_mean_c"
    expected = tile_path(
        tile_store.tiles_root,
        grid,
        metric=metric,
        tile_r=t.tile_r,
        tile_c=t.tile_c,
        ext=".bin.zst",
    )

    y_c = tile_store.try_get_metric_vector(metric, lat, lon)
    if y_c is None:
        raise FileNotFoundError(
            f"No tile data for metric={metric} at "
            f"(i_lat={cell.i_lat}, i_lon={cell.i_lon}) "
            f"tile=(r={t.tile_r}, c={t.tile_c}) "
            f"cell_offset=(o_lat={t.o_lat}, o_lon={t.o_lon}); "
            f"expected file: {expected}"
        )

    y_c = np.asarray(y_c, dtype=np.float32).reshape(-1)

    years = tile_store.yearly_axis(
        metric
    )  # per-metric yearly.json (you just implemented this)
    if not years:
        # dev fallback if axis missing
        years = list(
            range(
                tile_store.start_year_fallback,
                tile_store.start_year_fallback + int(y_c.size),
            )
        )

    x = np.asarray(years, dtype=np.int32)
    if x.size != y_c.size:
        raise RuntimeError(
            f"Year axis length {x.size} != series length {y_c.size} for {metric}"
        )

    # Derived: 5y mean + trend line
    y5_c = rolling_mean_centered(y_c, window=5)
    ytrend_c = linear_trend_line(x, y_c)

    if unit == "F":
        y = c_to_f(y_c)
        y5 = c_to_f(y5_c)
        ytrend = c_to_f(ytrend_c)
        unit_out = "F"
    else:
        y, y5, ytrend = y_c, y5_c, ytrend_c
        unit_out = "C"

    def to_list(a: np.ndarray) -> list[float | None]:
        out: list[float | None] = []
        for v in a.tolist():
            fv = float(v)
            out.append(fv if math.isfinite(fv) else None)
        return out

    x_list = [int(v) for v in x.tolist()]

    series_payload: Dict[str, SeriesPayload] = {
        "t2m_yearly_mean": SeriesPayload(x=x_list, y=to_list(y), unit=unit_out),
        "t2m_yearly_mean_5y": SeriesPayload(x=x_list, y=to_list(y5), unit=unit_out),
        "t2m_yearly_trend": SeriesPayload(x=x_list, y=to_list(ytrend), unit=unit_out),
    }

    graphs_out: List[GraphPayload] = [
        GraphPayload(
            id="t2m_annual_mean",
            title="Annual mean + 5-year mean + trend",
            series_keys=["t2m_yearly_mean", "t2m_yearly_mean_5y", "t2m_yearly_trend"],
            annotations=[],
        )
    ]

    caption = make_panel_caption(panel_id="t2m_50y", slug=place.slug)

    panel_out = PanelPayload(
        id="t2m_50y",
        title="Air temperature",
        graphs=graphs_out,
        text_md=caption,
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
        data_cells=[
            DataCell(
                grid=grid.grid_id,  # e.g. "global_0p25"
                i_lat=i_lat,
                i_lon=i_lon,
                deg=float(grid.deg),
                lat_center=latc,
                lon_center=lonc,
                lat_min=float(lat_min),
                lat_max=float(lat_max),
                lon_min=float(lon_min),
                lon_max=float(lon_max),
                tile_r=int(t.tile_r),
                tile_c=int(t.tile_c),
                o_lat=int(t.o_lat),
                o_lon=int(t.o_lon),
            )
        ],
    )

    resp = PanelResponse(
        release=release,
        unit=unit_out,
        location=loc_out,
        panel=panel_out,
        series=series_payload,
    )

    if cache is not None:
        cache.set_json(cache_key, resp.model_dump(mode="json"), ttl_s=ttl_panel_s)

    return resp


def build_panel(
    store: Store,
    registry: Registry,
    cache: Cache | None,
    ttl_panel_s: int,
    release: str,
    lat: float,
    lon: float,
    panel_id: str,
    unit: str,
) -> PanelResponse:
    place_slug, place_d_km = store.resolve_place(lat, lon)
    cache_key = f"panel:{release}:{panel_id}:{unit.upper()}:{place_slug}"
    if cache is not None:
        hit = cache.get_json(cache_key)
        if hit is not None:
            # Pydantic v2:
            return PanelResponse.model_validate(hit)
    meta = store.location_meta(place_slug)
    ds = store.load_location_dataset(place_slug)

    panel_spec = registry.panel(panel_id)
    graph_specs = registry.panel_graphs(panel_id)

    # If this panel includes the last50 graph, compute derived series in-memory
    deltas_c: dict[str, float] = {}
    if any(g.id == "t2m_last50_monthly_trend" for g in graph_specs):
        ds, deltas_c = _ensure_t2m_last50_derived(ds)

    data_cells = []
    if panel_id == "overview":
        i_lat, i_lon, latc, lonc = snap_cell(lat, lon, grid_deg=0.25, lon_mode="pm180")
        data_cells.append(
            DataCell(
                grid="era5_025",
                i_lat=i_lat,
                i_lon=i_lon,
                lat_center=latc,
                lon_center=lonc,
            )
        )
    elif panel_id == "ocean":
        # oisst is pm180 and 0.25, CRW is degrees_east and effectively 0.05
        i_lat, i_lon, latc, lonc = snap_cell(lat, lon, grid_deg=0.25, lon_mode="pm180")
        data_cells.append(
            DataCell(
                grid="oisst_025",
                i_lat=i_lat,
                i_lon=i_lon,
                lat_center=latc,
                lon_center=lonc,
            )
        )
        i_lat, i_lon, latc, lonc = snap_cell(lat, lon, grid_deg=0.05, lon_mode="east")
        data_cells.append(
            DataCell(
                grid="crw_005",
                i_lat=i_lat,
                i_lon=i_lon,
                lat_center=latc,
                lon_center=lonc,
            )
        )

    # Collect unique series keys
    needed: List[tuple[str, str]] = []  # (key, unit_kind)
    for g in graph_specs:
        for s in g.series:
            needed.append((s.key, s.unit_kind))

    series_payload: Dict[str, SeriesPayload] = {}
    missing: List[str] = []

    for key, unit_kind in needed:
        if key in series_payload:
            continue

        if key not in ds:
            missing.append(key)
            continue

        da = ds[key]
        x, y = _series_xy_from_da(da)
        y2, unit_out = convert_series(unit=unit, unit_kind=unit_kind, y=y)

        series_payload[key] = SeriesPayload(x=x, y=y2, unit=unit_out)

    # For v0, don’t error if some ocean series aren’t present for inland slugs; just omit those graphs later.
    # Filter out graphs that have missing required series.
    graphs_out: List[GraphPayload] = []
    for g in graph_specs:
        keys = [s.key for s in g.series]
        if any(k not in series_payload for k in keys):
            continue

        annotations: List[GraphAnnotation] = []
        if g.id == "t2m_last50_monthly_trend" and deltas_c:
            # show as “+0.3°C in 46y”
            # number of years = len(yearly)-1 if yearly series is present
            n_years = 0
            if "t2m_yearly_mean_c" in series_payload:
                n_years = max(0, len(series_payload["t2m_yearly_mean_c"].x) - 1)

            def fmt(delta_c: float) -> str:
                sign = "+" if delta_c >= 0 else ""
                # if unit=F, convert delta as delta (no +32)
                if unit.upper() == "F":
                    delta = delta_c * 9.0 / 5.0
                    return f"{sign}{delta:.1f}°F in {n_years}y"
                return f"{sign}{delta_c:.1f}°C in {n_years}y"

            if "mean" in deltas_c:
                annotations.append(
                    GraphAnnotation(
                        series_key="t2m_yearly_mean_trend_c", text=fmt(deltas_c["mean"])
                    )
                )
            if "coldest" in deltas_c:
                annotations.append(
                    GraphAnnotation(
                        series_key="t2m_yearly_coldest_month_trend_c",
                        text=fmt(deltas_c["coldest"]),
                    )
                )
            if "warmest" in deltas_c:
                annotations.append(
                    GraphAnnotation(
                        series_key="t2m_yearly_warmest_month_trend_c",
                        text=fmt(deltas_c["warmest"]),
                    )
                )

        graphs_out.append(
            GraphPayload(
                id=g.id, title=g.title, series_keys=keys, annotations=annotations
            )
        )

    if panel_id == "t2m_demo":
        caption = caption_t2m_demo(
            unit=unit.upper(),
            series={
                k: v.model_dump(mode="json") for k, v in series_payload.items()
            },  # or just series_payload if it's already dict-like
            place_label=meta.get("label"),
        )
    else:
        caption = make_panel_caption(panel_id=panel_id, slug=place_slug)

    panel_out = PanelPayload(
        id=panel_spec.id,
        title=panel_spec.title,
        graphs=graphs_out,
        text_md=caption,
    )

    loc_out = LocationInfo(
        query=QueryPoint(lat=float(lat), lon=float(lon)),
        place=PlaceInfo(
            slug=place_slug,
            label=meta.get("label"),
            lat=float(meta["lat"]),
            lon=float(meta["lon"]),
            distance_km=float(place_d_km),
        ),
        data_cells=data_cells,
    )

    resp = PanelResponse(
        release=release,
        unit=unit.upper(),
        location=loc_out,
        panel=panel_out,
        series=series_payload,
    )

    if cache is not None:
        cache.set_json(cache_key, resp.model_dump(mode="json"), ttl_s=ttl_panel_s)

    return resp
