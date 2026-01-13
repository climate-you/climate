# climate/panels/worldmap.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Tuple, Dict, Any
import math

import numpy as np
import xarray as xr

import folium
from folium.raster_layers import ImageOverlay
import branca.colormap as bcm

import matplotlib.cm as cm
import matplotlib.colors as mcolors

import plotly.graph_objects as go

from climate.models import StoryContext, StoryFacts
from climate.units import convert_delta_array_to_unit, is_fahrenheit, fmt_unit

MERC_MAX_LAT = 85.05112878  # Web Mercator valid latitude limit

WORLD_DATA_DIR = Path("data/world")

# -------------------------
# Public API
# -------------------------

def build_world_map_data(ctx: StoryContext, *, grid_deg: float | None = None) -> dict:
    """
    Load latest warming map raster + manifest produced by scripts/make_warming_map_cds.py.

    Expected:
      data/world/warming_map_*_to_*.nc
      data/world/warming_map_*_to_*.manifest.json
    """

    nc_files = sorted(
        WORLD_DATA_DIR.glob("warming_map_*_to_*_grid*.nc"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if grid_deg is not None:
        tag = str(grid_deg).replace(".", "p")
        nc_files = [p for p in nc_files if f"_grid{tag}" in p.name]

    # fallback to any warming_map if none matched
    if not nc_files:
        nc_files = sorted(
            WORLD_DATA_DIR.glob("warming_map_*_to_*.nc"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    if not nc_files:
        raise FileNotFoundError(
            "No warming_map_*.nc found in data/world. Run scripts/make_warming_map_cds.py first."
        )

    nc_path = nc_files[0]
    manifest_path = nc_path.with_suffix(".manifest.json")
    if not manifest_path.exists():
        # tolerate older naming
        cand = list(WORLD_DATA_DIR.glob(nc_path.stem + "*.manifest.json"))
        if cand:
            manifest_path = cand[0]

    manifest: dict = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())

    ds = xr.open_dataset(nc_path)

    # choose the first data variable (robust to naming)
    var = next(iter(ds.data_vars))
    da = ds[var]

    lat_name = _pick_coord_name(da, ["latitude", "lat"])
    lon_name = _pick_coord_name(da, ["longitude", "lon"])
    if lat_name is None or lon_name is None:
        raise RuntimeError(
            f"Warming map missing latitude/longitude coords. coords={list(da.coords)}"
        )

    # Ensure [lat, lon] ordering for image creation.
    if tuple(da.dims) != (lat_name, lon_name):
        da = da.transpose(lat_name, lon_name)

    # Normalize longitude to [-180, 180) and sort
    da = _normalize_longitude(da, lon_name)

    return dict(
        da=da,
        var_name=var,
        manifest=manifest,
        lat_name=lat_name,
        lon_name=lon_name,
    )


def build_world_map_figure(ctx: StoryContext, facts: StoryFacts, data: dict) -> Tuple[folium.Map, str]:
    da: xr.DataArray = data["da"]
    manifest: dict = data.get("manifest", {})
    lat_name: str = data["lat_name"]
    lon_name: str = data["lon_name"]

    # Pull array and coords
    arr = np.asarray(da.values, dtype="float64")
    lats = np.asarray(da[lat_name].values, dtype="float64")
    lons = np.asarray(da[lon_name].values, dtype="float64")

    # Warp from Plate Carrée (regular lat spacing) to Web Mercator y spacing
    arr_w, lats_w = _warp_lat_to_mercator(arr, lats)

    # Convert warming deltas to selected unit (Δ°F = Δ°C * 9/5)
    arr_u = convert_delta_array_to_unit(arr_w, ctx.unit)

    # Build RGBA image from values (in selected unit)
    rgba, vmin_used, vmax_used = _to_rgba(arr_u)
    vmin_leg, vmax_leg = _nice_bounds(vmin_used, vmax_used)
    img = (rgba * 255).astype("uint8")

    # Bounds for Web Mercator tile basemap
    bounds = [[-MERC_MAX_LAT, -180.0], [MERC_MAX_LAT, 180.0]]

    # Folium map with no horizontal wrapping of tiles (overlay doesn't wrap)
    m = folium.Map(location=[20, 0], zoom_start=2, tiles=None, max_bounds=True)
    folium.TileLayer("CartoDB positron", no_wrap=True).add_to(m)

    ImageOverlay(
        image=img,
        bounds=bounds,
        opacity=1.0,       # alpha is already in the RGBA
        interactive=False,
        cross_origin=False,
        zindex=1,
    ).add_to(m)

    # Legend
    col = bcm.LinearColormap(
        colors=["#ffffcc", "#ffeda0", "#feb24c", "#f03b20", "#bd0026"],
        vmin=vmin_leg,
        vmax=vmax_leg,
    )
    ticks = _legend_ticks_sequential(vmin_leg, vmax_leg)
    # Branca: keep gradient, override tick labels
    col.tick_labels = [f"{t:.0f}" for t in ticks]
    col.ticks = ticks
    col.caption = f"Warming (ΔT, {fmt_unit(ctx.unit)}) — sequential scale"

    col.add_to(m)

    # Location marker
    folium.CircleMarker(
        location=[ctx.location_lat, ctx.location_lon],
        radius=6,
        color="#d73027",
        fill=True,
        fill_opacity=0.95,
        weight=2,
    ).add_to(m)

    # Small caption (no filesystem mention)
    pa = _fmt_period(manifest.get("baseline_a"))
    pb = _fmt_period(manifest.get("baseline_b"))
    grid = manifest.get("grid_deg")
    grid_txt = f" (grid: {grid}°)" if grid else ""

    if pa and pb:
        tiny = f"ERA5 warming: {pb} - {pa}{grid_txt}."
    else:
        tiny = f"ERA5 warming relative to a baseline period{grid_txt}."

    return m, tiny


def world_map_caption(ctx: StoryContext, facts: StoryFacts, data: dict) -> str:
    manifest: dict = data.get("manifest", {})
    pa = _fmt_period(manifest.get("baseline_a"))
    pb = _fmt_period(manifest.get("baseline_b"))

    if pa and pb:
        return (
            f"This map shows how much each grid cell has warmed (**{pb} - {pa}**) "
            "using ERA5 near-surface (2m) air temperature. Most places warmed; a few "
            "regions show slight cooling relative to the baseline and appear at the "
            "lightest end of the scale.\n\n"
            "Your selected location is highlighted."
        )
    return (
        "This map shows how much each grid cell has warmed relative to a baseline period "
        "using ERA5 near-surface (2m) air temperature. Most places warmed; a few regions "
        "show slight cooling relative to the baseline and appear at the lightest end of "
        "the scale.\n\n"
        "Your selected location is highlighted."
    )


def build_local_inset_data(
    ctx: StoryContext,
    world_data: dict,
    *,
    half_width_deg: float = 20.0,
    half_height_deg: float = 20.0,
    nearby_radius_cells: int = 2,
) -> dict:
    """
    Prepare a cropped local window around the user's location from the world warming raster.

    - Uses the same underlying world map DataArray (coarse 1° is fine for v1).
    - Handles longitude wrap-around near the dateline.
    - Computes simple neighborhood stats for dynamic captioning.
    """
    da: xr.DataArray = world_data["da"]
    lat_name: str = world_data["lat_name"]
    lon_name: str = world_data["lon_name"]

    # Normalize user lon into same convention as the DA (typically [-180, 180))
    lons = np.asarray(da[lon_name].values, dtype="float64")
    if np.nanmin(lons) < 0:
        user_lon = ((float(ctx.location_lon) + 180) % 360) - 180
    else:
        user_lon = float(ctx.location_lon) % 360

    user_lat = float(ctx.location_lat)

    # Crop latitude (easy; no wrap)
    lat_min = max(-90.0, user_lat - half_height_deg)
    lat_max = min(90.0, user_lat + half_height_deg)

    lats = np.asarray(da[lat_name].values, dtype="float64")
    lat_desc = lats[0] > lats[-1]
    if lat_desc:
        da_lat = da.sel({lat_name: slice(lat_max, lat_min)})
    else:
        da_lat = da.sel({lat_name: slice(lat_min, lat_max)})

    # Crop longitude (handle wrap if window crosses -180/180)
    lon_min = user_lon - half_width_deg
    lon_max = user_lon + half_width_deg

    if np.nanmin(lons) < 0:
        # coords in [-180, 180)
        if lon_min < -180 or lon_max > 180:
            # split and concat
            a_min = ((lon_min + 180) % 360) - 180
            a_max = ((lon_max + 180) % 360) - 180
            # Example: lon_min=170, lon_max=210 -> a_min=170, a_max=-150
            left = da_lat.sel({lon_name: slice(a_min, 180.0)})
            right = da_lat.sel({lon_name: slice(-180.0, a_max)})
            da_win = xr.concat([left, right], dim=lon_name)
        else:
            da_win = da_lat.sel({lon_name: slice(lon_min, lon_max)})
    else:
        # coords in [0, 360)
        lon_min2 = lon_min % 360
        lon_max2 = lon_max % 360
        if lon_min2 > lon_max2:
            left = da_lat.sel({lon_name: slice(lon_min2, 360.0)})
            right = da_lat.sel({lon_name: slice(0.0, lon_max2)})
            da_win = xr.concat([left, right], dim=lon_name)
        else:
            da_win = da_lat.sel({lon_name: slice(lon_min2, lon_max2)})

    # Convert to selected unit (Δ°F = Δ°C * 9/5)
    arr_c = np.asarray(da_win.values, dtype="float64")
    arr = convert_delta_array_to_unit(arr_c, ctx.unit)

    # Find nearest cell to user for "nearby" stats
    win_lats = np.asarray(da_win[lat_name].values, dtype="float64")
    win_lons = np.asarray(da_win[lon_name].values, dtype="float64")

    # choose nearest indices
    i0 = int(np.argmin(np.abs(win_lats - user_lat)))
    # lon distance with wrap-awareness in [-180,180) case
    if np.nanmin(win_lons) < 0:
        dlon = np.abs(((win_lons - user_lon + 180) % 360) - 180)
    else:
        dlon = np.abs((win_lons - (user_lon % 360)))
    j0 = int(np.argmin(dlon))

    r = int(max(1, nearby_radius_cells))
    i1, i2 = max(0, i0 - r), min(arr.shape[0], i0 + r + 1)
    j1, j2 = max(0, j0 - r), min(arr.shape[1], j0 + r + 1)
    near = arr[i1:i2, j1:j2]

    def _nan_stats(a: np.ndarray) -> dict:
        a = a[np.isfinite(a)]
        if a.size == 0:
            return dict(mean=np.nan, std=np.nan, p10=np.nan, p90=np.nan, min=np.nan, max=np.nan)
        return dict(
            mean=float(np.mean(a)),
            std=float(np.std(a)),
            p10=float(np.quantile(a, 0.10)),
            p90=float(np.quantile(a, 0.90)),
            min=float(np.min(a)),
            max=float(np.max(a)),
        )

    stats_near = _nan_stats(near)
    stats_window = _nan_stats(arr)

    return dict(
        da_window=da_win,           # still in °C in values; unit conversion is in arr_window
        arr_window=arr,             # numeric array in ctx.unit
        lat_name=lat_name,
        lon_name=lon_name,
        unit=ctx.unit,
        user_lat=user_lat,
        user_lon=user_lon,
        stats_near=stats_near,
        stats_window=stats_window,
        window_half_width_deg=half_width_deg,
        window_half_height_deg=half_height_deg,
        nearby_radius_cells=r,
    )

def build_local_inset_figure(
    ctx: StoryContext,
    facts: StoryFacts,
    inset_data: dict,
) -> tuple[go.Figure, str]:
    da_win: xr.DataArray = inset_data["da_window"]
    lat_name: str = inset_data["lat_name"]
    lon_name: str = inset_data["lon_name"]
    arr = inset_data["arr_window"]

    lats = np.asarray(da_win[lat_name].values, dtype="float64")
    lons = np.asarray(da_win[lon_name].values, dtype="float64")

    # Make y axis increasing (south->north) for a conventional plot
    if lats[0] > lats[-1]:
        lats_plot = lats[::-1]
        z_plot = arr[::-1, :]
    else:
        lats_plot = lats
        z_plot = arr

    # Robust colorscale bounds for local window contrast
    finite = z_plot[np.isfinite(z_plot)]
    if finite.size:
        vmin = float(np.quantile(finite, 0.05))
        vmax = float(np.quantile(finite, 0.98))
        if vmin >= vmax:
            vmin, vmax = float(np.min(finite)), float(np.max(finite))
    else:
        vmin, vmax = 0.0, 1.0

    fig = go.Figure(
        go.Heatmap(
            x=lons,
            y=lats_plot,
            z=z_plot,
            zmin=vmin,
            zmax=vmax,
            colorscale="YlOrRd",
            colorbar=dict(title=f"ΔT ({fmt_unit(ctx.unit)})"),
            hovertemplate="Lon %{x:.1f}°, Lat %{y:.1f}°<br>ΔT %{z:.2f}" + fmt_unit(ctx.unit) + "<extra></extra>",
        )
    )

    # Mark user location
    fig.add_trace(
        go.Scatter(
            x=[inset_data["user_lon"]],
            y=[inset_data["user_lat"]],
            mode="markers",
            marker=dict(size=10, symbol="x"),
            showlegend=False,
            hovertemplate=f"{ctx.location_label}<extra></extra>",
        )
    )

    fig.update_layout(
        width=320,
        height=320,
        margin=dict(l=50, r=20, t=40, b=40),
        title=dict(text=f"<b>Local area around {ctx.location_label}</b>", x=0, xanchor="left"),
    )
    # Keep degrees square (no stretching)
    fig.update_yaxes(
        title_text="Latitude",
        scaleanchor="x",
        scaleratio=1,
    )
    fig.update_xaxes(title_text="Longitude")
    fig.update_yaxes(title_text="Latitude")

    tiny = (
        f"Window: ±{inset_data['window_half_width_deg']:.0f}° lon, ±{inset_data['window_half_height_deg']:.0f}° lat "
        f"around your location. Values in {fmt_unit(ctx.unit)}."
    )
    return fig, tiny

def local_inset_caption(ctx: StoryContext, facts: StoryFacts, inset_data: dict) -> str:
    s = inset_data["stats_near"]
    w = inset_data["stats_window"]

    def fmt(x: float) -> str:
        return "n/a" if not np.isfinite(x) else f"{x:.2f}{fmt_unit(ctx.unit)}"

    mean_near = s["mean"]
    std_near = s["std"]
    spread_near = (s["p90"] - s["p10"]) if (np.isfinite(s["p90"]) and np.isfinite(s["p10"])) else np.nan

    # Heuristics (tweakable)
    high_variance = np.isfinite(spread_near) and (spread_near > (1.0 if not is_fahrenheit(ctx.unit) else 1.8))
    strong_warming = np.isfinite(mean_near) and (mean_near > (1.5 if not is_fahrenheit(ctx.unit) else 2.7))

    lines = []
    if np.isfinite(mean_near):
        if strong_warming:
            lines.append(f"Your surrounding region shows **strong warming**: about **{fmt(mean_near)}** on average nearby.")
        else:
            lines.append(f"Your surrounding region has warmed by about **{fmt(mean_near)}** on average nearby.")
    else:
        lines.append("We couldn’t estimate local warming around your location (missing data in this window).")

    if high_variance:
        lines.append(
            f"Warming varies quite a bit within this window (nearby spread ~**{fmt(spread_near)}** between the 10th–90th percentiles), "
            "which often happens near coasts, mountains, or strong ocean/land contrasts."
        )
    elif np.isfinite(std_near):
        lines.append(f"Warming is fairly uniform locally (nearby variability ~**{fmt(std_near)}** standard deviation).")

    # Optional: include window context (quietly)
    if np.isfinite(w["mean"]):
        lines.append(f"(In this whole local window, values range from **{fmt(w['min'])}** to **{fmt(w['max'])}**.)")

    return "\n\n".join(lines)

# -------------------------
# Helpers
# -------------------------

def _pick_coord_name(da: xr.DataArray, names: list[str]) -> str | None:
    for n in names:
        if n in da.coords:
            return n
    return None


def _normalize_longitude(da: xr.DataArray, lon_name: str) -> xr.DataArray:
    """
    Convert 0..360 style longitude to -180..180 and sort.
    If already -180..180-ish, still sort.
    """
    lons = np.asarray(da[lon_name].values, dtype="float64")
    if np.nanmax(lons) > 180:
        lons2 = ((lons + 180) % 360) - 180  # -> [-180, 180)
        da = da.assign_coords({lon_name: lons2}).sortby(lon_name)
    else:
        da = da.sortby(lon_name)
    return da

def _fmt_period(p: dict | None) -> str | None:
    if not isinstance(p, dict):
        return None
    a = p.get("start_year")
    b = p.get("end_year")
    if isinstance(a, int) and isinstance(b, int):
        return f"{a}–{b}"
    return None


def _choose_scale_sequential(arr: np.ndarray) -> tuple[float, float, any, any]:
    arr = np.asarray(arr, dtype="float64")
    m = np.isfinite(arr)
    if not m.any():
        vmin, vmax = 0.0, 1.0
        cmap = cm.get_cmap("YlOrRd")
        norm = mcolors.Normalize(vmin=vmin, vmax=vmax, clip=True)
        return vmin, vmax, cmap, norm

    vmin = float(np.nanquantile(arr, 0.05))
    vmax = float(np.nanquantile(arr, 0.98))
    if not np.isfinite(vmin) or not np.isfinite(vmax) or vmin >= vmax:
        vmin = float(np.nanmin(arr))
        vmax = float(np.nanmax(arr))
        if vmin >= vmax:
            vmin, vmax = vmin - 1.0, vmax + 1.0

    cmap = cm.get_cmap("YlOrRd")
    norm = mcolors.Normalize(vmin=vmin, vmax=vmax, clip=True)
    return vmin, vmax, cmap, norm


def _to_rgba(arr: np.ndarray) -> tuple[np.ndarray, float, float]:
    arr = np.asarray(arr, dtype="float64")
    mask = np.isfinite(arr)

    vmin, vmax, cmap, norm = _choose_scale_sequential(arr)
    filled = np.where(mask, arr, vmin)

    rgba = cmap(norm(filled))
    rgba[..., 3] = np.where(mask, 0.75, 0.0)
    return rgba, vmin, vmax

def _legend_ticks_sequential(vmin: float, vmax: float) -> list[float]:
    lo = float(math.floor(vmin))
    hi = float(math.ceil(vmax))
    ticks = [float(x) for x in range(int(lo), int(hi) + 1)]
    if 0.0 not in ticks:
        ticks.append(0.0)
        ticks.sort()
    return ticks

def _nice_bounds(vmin: float, vmax: float) -> tuple[float, float]:
    # Round legend endpoints to clean integers for readability
    vmin2 = math.floor(vmin)  # e.g. -0.1 -> -1
    vmax2 = math.ceil(vmax)   # e.g.  3.8 ->  4

    # Optional: if you want the legend to be “warming magnitude”, pin at 0
    # vmin2 = 0.0

    # Safety: avoid degenerate bounds
    if vmin2 >= vmax2:
        vmax2 = vmin2 + 1.0

    return float(vmin2), float(vmax2)

def _warp_lat_to_mercator(arr_latlon: np.ndarray, lats: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Resample a [lat, lon] array from regular-lat spacing to regular Web Mercator y spacing.

    Why: Leaflet/Folium basemap tiles are Web Mercator. ImageOverlay doesn't reproject,
    so we warp the raster ourselves so coastlines line up.

    Returns:
      arr_warped: [H, W] where H equals number of clipped lat rows
      lats_out:   clipped lats (mostly for debugging; bounds use MERC_MAX_LAT)
    """
    arr = np.asarray(arr_latlon, dtype="float64")
    lats = np.asarray(lats, dtype="float64")

    # Clip to Mercator-valid range
    m = (lats <= MERC_MAX_LAT) & (lats >= -MERC_MAX_LAT)
    if not m.any():
        # fallback: if something is wrong, return original
        return arr, lats

    arr = arr[m, :]
    lats = lats[m]

    # Mercator y coordinate for each latitude
    phi = np.deg2rad(lats)
    y_src = np.log(np.tan(np.pi / 4 + phi / 2))  # mercator y

    # Target grid: uniform in mercator y, same number of rows
    y_min, y_max = float(np.min(y_src)), float(np.max(y_src))
    y_tgt = np.linspace(y_min, y_max, num=len(lats))

    # Interpolate each longitude column along y
    out = np.full((len(lats), arr.shape[1]), np.nan, dtype="float64")

    # np.interp requires ascending x
    order = np.argsort(y_src)
    y_src_a = y_src[order]

    for j in range(arr.shape[1]):
        col = arr[:, j].astype("float64")
        col_a = col[order]
        ok = np.isfinite(col_a)
        if ok.sum() >= 2:
            out[:, j] = np.interp(y_tgt, y_src_a[ok], col_a[ok], left=np.nan, right=np.nan)

    # Leaflet expects row 0 = north/top.
    # Our y_tgt is ascending (south->north), so flip to north->south.
    out = out[::-1, :]

    # lats_out is not used for bounds; keep for debugging (north->south)
    lats_sorted = np.sort(lats)[::-1]
    return out, lats_sorted
