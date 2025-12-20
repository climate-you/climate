#!/usr/bin/env python3
"""
Make a single equirectangular (lon/lat) warming texture for a globe.

Input:  NetCDF warming map (e.g. warming_map_1979-1988_to_2016-2025_grid1p0.nc)
Output: WebP texture + JSON manifest (baseline periods, scaling, etc.)

Texture convention:
- Equirectangular mapping (lon -180..180, lat 90..-90)
- Image top = North, bottom = South
- X increases eastward, centered at 0° lon
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import xarray as xr

from PIL import Image
import matplotlib.cm as cm
import matplotlib.colors as mcolors


def _roll_lon_0_to_180(lon0_360: np.ndarray, arr: np.ndarray):
    """
    Input lon in [0..359] (or generally 0..360) and data (lat, lon).
    Output lon in [-180..180) and rolled array so Greenwich is centered.
    """
    lon = np.asarray(lon0_360, dtype="float64")
    n = lon.shape[0]
    # find index closest to 180
    i180 = int(np.argmin(np.abs(lon - 180.0)))
    arr2 = np.roll(arr, -i180, axis=1)
    lon2 = ((lon - 180.0 + 180.0) % 360.0) - 180.0  # -> [-180, 180)
    lon2 = np.roll(lon2, -i180)
    return lon2, arr2


def _normalize_to_rgb(arr: np.ndarray, *, cmap_name: str, vmin: float, vmax: float) -> np.ndarray:
    """
    Map numeric array to uint8 RGB image (H,W,3).
    NaNs become transparent-ish background color (we'll just paint them black here).
    """
    arr = np.asarray(arr, dtype="float64")
    mask = np.isfinite(arr)

    cmap = cm.get_cmap(cmap_name)
    norm = mcolors.Normalize(vmin=vmin, vmax=vmax, clip=True)

    filled = np.where(mask, arr, vmin)
    rgba = cmap(norm(filled))  # float 0..1 (H,W,4)
    rgb = (rgba[..., :3] * 255.0).astype(np.uint8)
    # Optional: if you want NaNs to be dark/transparent on globe:
    rgb[~mask] = 0
    return rgb


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nc", required=True, help="Input warming map NetCDF")
    ap.add_argument("--var", default="warming_c", help="Variable name in NetCDF (default: warming_c)")
    ap.add_argument("--out", required=True, help="Output basename (no extension). Writes .webp + .json")
    ap.add_argument("--cmap", default="YlOrRd", help="Matplotlib colormap name (default: YlOrRd)")
    ap.add_argument("--qlo", type=float, default=0.05, help="Lower quantile for scaling (default: 0.05)")
    ap.add_argument("--qhi", type=float, default=0.98, help="Upper quantile for scaling (default: 0.98)")
    ap.add_argument("--size", default="4096x2048", help="Texture size WxH (default: 4096x2048)")
    ap.add_argument("--quality", type=int, default=85, help="WebP quality (default: 85)")
    args = ap.parse_args()

    in_nc = Path(args.nc)
    out_base = Path(args.out)
    out_webp = out_base.with_suffix(".webp")
    out_json = out_base.with_suffix(".manifest.json")

    W, H = (int(x) for x in args.size.lower().split("x"))

    ds = xr.open_dataset(in_nc)
    if args.var not in ds:
        raise RuntimeError(f"Variable {args.var!r} not found. Vars: {list(ds.data_vars)}")

    da = ds[args.var]
    # Expect dims (latitude, longitude) or similar; infer names
    lat_name = "latitude" if "latitude" in da.dims else da.dims[0]
    lon_name = "longitude" if "longitude" in da.dims else da.dims[1]

    lats = np.asarray(da[lat_name].values, dtype="float64")
    lons = np.asarray(da[lon_name].values, dtype="float64")
    arr = np.asarray(da.values, dtype="float64")  # (lat, lon)

    # Ensure lat goes north->south (top to bottom)
    if lats[0] < lats[-1]:
        lats = lats[::-1]
        arr = arr[::-1, :]

    # Convert lon 0..360 to -180..180 centered
    if np.nanmin(lons) >= 0.0 and np.nanmax(lons) > 180.0:
        lons2, arr2 = _roll_lon_0_to_180(lons, arr)
    else:
        lons2, arr2 = lons, arr

    finite = arr2[np.isfinite(arr2)]
    if finite.size == 0:
        vmin, vmax = 0.0, 1.0
    else:
        vmin = float(np.quantile(finite, args.qlo))
        vmax = float(np.quantile(finite, args.qhi))
        if not np.isfinite(vmin) or not np.isfinite(vmax) or vmin >= vmax:
            vmin = float(np.min(finite))
            vmax = float(np.max(finite))
            if vmin >= vmax:
                vmin, vmax = vmin - 1.0, vmax + 1.0

    rgb = _normalize_to_rgb(arr2, cmap_name=args.cmap, vmin=vmin, vmax=vmax)

    # Resize to a “globe-friendly” texture size
    im = Image.fromarray(rgb, mode="RGB")
    im = im.resize((W, H), resample=Image.BILINEAR)
    im.save(out_webp, format="WEBP", quality=int(args.quality), method=6)

    # Manifest: keep it simple + useful for front-end
    manifest = {
        "type": "equirectangular_texture",
        "source_nc": str(in_nc),
        "var": args.var,
        "units": ds[args.var].attrs.get("units", "degC"),
        "cmap": args.cmap,
        "scale": {"vmin": vmin, "vmax": vmax, "qlo": args.qlo, "qhi": args.qhi},
        "texture": {"path": str(out_webp), "width": W, "height": H},
        "coords": {
            "lon_range": [-180.0, 180.0],
            "lat_range": [90.0, -90.0],
            "note": "Top is north, bottom is south. X is lon centered at 0°.",
        },
    }

    # If your NetCDF has baseline attrs in its manifest already, you can manually add them later
    out_json.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"Wrote {out_webp}")
    print(f"Wrote {out_json}")


if __name__ == "__main__":
    main()
