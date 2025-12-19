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

from climate.models import StoryContext, StoryFacts
from climate.units import convert_delta_array_to_unit

MERC_MAX_LAT = 85.05112878  # Web Mercator valid latitude limit


# -------------------------
# Public API
# -------------------------

def build_world_map_data(ctx: StoryContext) -> dict:
    """
    Load latest warming map raster + manifest produced by scripts/make_warming_map_cds.py.

    Expected:
      data/world/warming_map_*_to_*.nc
      data/world/warming_map_*_to_*.manifest.json
    """
    data_dir = Path("data/world")
    nc_files = sorted(
        data_dir.glob("warming_map_*_to_*.nc"),
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
        cand = list(data_dir.glob(nc_path.stem + "*.manifest.json"))
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
    col.caption = f"Warming (ΔT, {ctx.unit}) — sequential scale"

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

def _is_fahrenheit(unit: str) -> bool:
    return "F" in (unit or "").upper()

def _convert_delta_c_to_unit(arr_c: np.ndarray, unit: str) -> np.ndarray:
    """Convert a temperature *difference* from °C to the requested unit."""
    if _is_fahrenheit(unit):
        return np.asarray(arr_c, dtype="float64") * (9.0 / 5.0)
    return np.asarray(arr_c, dtype="float64")

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
