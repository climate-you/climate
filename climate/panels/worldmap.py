from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Tuple

import numpy as np
import xarray as xr

import folium
from folium.raster_layers import ImageOverlay
import branca.colormap as bcm

import matplotlib.cm as cm
import matplotlib.colors as mcolors

from climate.models import StoryContext, StoryFacts


def build_world_map_data(ctx: StoryContext) -> dict:
    """
    Load the latest warming map raster + manifest.
    Expects files created by scripts/make_warming_map_cds.py:
      data/world/warming_map_*_to_*.nc
      data/world/warming_map_*_to_*.manifest.json
    """
    data_dir = Path("data/world")
    nc_files = sorted(data_dir.glob("warming_map_*_to_*.nc"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not nc_files:
        raise FileNotFoundError("No warming_map_*.nc found in data/world. Run scripts/make_warming_map_cds.py first.")

    nc_path = nc_files[0]
    manifest_path = nc_path.with_suffix(".manifest.json")
    if not manifest_path.exists():
        # tolerate older naming schemes
        manifest_candidates = list(data_dir.glob(nc_path.stem + "*.manifest.json"))
        manifest_path = manifest_candidates[0] if manifest_candidates else manifest_path

    manifest: dict = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())

    ds = xr.open_dataset(nc_path)

    # choose the first data variable (robust to naming)
    var = next(iter(ds.data_vars))
    da = ds[var]

    lat_name = "lat" if "lat" in da.coords else ("latitude" if "latitude" in da.coords else None)
    lon_name = "lon" if "lon" in da.coords else ("longitude" if "longitude" in da.coords else None)
    if lat_name is None or lon_name is None:
        raise RuntimeError(f"Warming map is missing lat/lon coords. coords={list(da.coords)}")

    lats = da[lat_name].values
    lons = da[lon_name].values

    # Convert lon 0..360 -> -180..180 for folium, keep sorted
    if np.nanmax(lons) > 180:
        lons = ((lons + 180) % 360) - 180
        da = da.assign_coords({lon_name: lons}).sortby(lon_name)
        lons = da[lon_name].values

    # Ensure lat ascending for image generation
    if lats[0] > lats[-1]:
        da = da.sortby(lat_name)
        lats = da[lat_name].values

    return dict(
        da=da,
        var_name=var,
        manifest=manifest,
        lat_name=lat_name,
        lon_name=lon_name,
    )


def build_world_map_figure(ctx: StoryContext, facts: StoryFacts, data: dict) -> Tuple[folium.Map, str]:
    da: xr.DataArray = data["da"]
    manifest: dict = data["manifest"]
    lat_name = data["lat_name"]
    lon_name = data["lon_name"]

    arr = da.values.astype("float64")
    # Handle missing values
    arr_mask = np.isfinite(arr)

    # Color scaling: prefer manifest min/max; else robust quantiles
    vmin = manifest.get("vmin")
    vmax = manifest.get("vmax")
    if vmin is None or vmax is None:
        if arr_mask.any():
            vmin = float(np.nanquantile(arr, 0.02))
            vmax = float(np.nanquantile(arr, 0.98))
        else:
            vmin, vmax = -1.0, 1.0

    # Build RGBA image from values
    norm = mcolors.Normalize(vmin=vmin, vmax=vmax, clip=True)
    cmap = cm.get_cmap("RdYlBu_r")  # diverging-ish, warm colors for positive warming
    rgba = cmap(norm(np.where(arr_mask, arr, vmin)))
    rgba[..., 3] = np.where(arr_mask, 0.65, 0.0)  # transparent where missing
    img = (rgba * 255).astype("uint8")

    lats = da[lat_name].values
    lons = da[lon_name].values
    south, north = float(np.min(lats)), float(np.max(lats))
    west, east = float(np.min(lons)), float(np.max(lons))
    bounds = [[south, west], [north, east]]

    m = folium.Map(location=[20, 0], zoom_start=2, tiles="CartoDB positron")

    ImageOverlay(
        image=img,
        bounds=bounds,
        opacity=1.0,  # alpha handled in RGBA already
        interactive=False,
        cross_origin=False,
        zindex=1,
    ).add_to(m)

    # Legend
    col = bcm.LinearColormap(
        colors=["#2c7bb6", "#abd9e9", "#ffffbf", "#fdae61", "#d7191c"],
        vmin=vmin,
        vmax=vmax,
    )
    col.caption = f"Warming (ΔT, °C) relative to baseline"
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

    # Caption text (no filesystem mention)
    # Try to extract baseline periods from manifest if present
    base_a = manifest.get("baseline_a") or manifest.get("period_a") or manifest.get("past_period")
    base_b = manifest.get("baseline_b") or manifest.get("period_b") or manifest.get("recent_period")

    if base_a and base_b:
        tiny = f"ERA5 2m temperature warming: {base_b} minus {base_a}."
    else:
        tiny = "ERA5 2m temperature warming relative to a baseline period."

    return m, tiny


def world_map_caption(ctx: StoryContext, facts: StoryFacts, data: dict) -> str:
    manifest: dict = data["manifest"]
    base_a = manifest.get("baseline_a") or manifest.get("period_a") or manifest.get("past_period")
    base_b = manifest.get("baseline_b") or manifest.get("period_b") or manifest.get("recent_period")

    if base_a and base_b:
        return (
            f"This map shows how much each grid cell has warmed (**{base_b} − {base_a}**) "
            "using ERA5 near-surface (2m) air temperature. Your selected location is highlighted."
        )
    return (
        "This map shows how much each grid cell has warmed relative to a baseline period "
        "using ERA5 near-surface (2m) air temperature. Your selected location is highlighted."
    )
