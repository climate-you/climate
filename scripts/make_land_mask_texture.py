#!/usr/bin/env python3
"""Build a Mercator land-mask PNG matching the release's map textures.

Story maps of a land quantity (rainfall as a percentage of normal, say) carry
a great deal of ocean that is not part of the argument and is much noisier than
the land, which makes the land pattern hard to pick out. This writes a mask in
exactly the projection the textures use, so a page can crop it with the same
rectangle and knock the ocean out with one composite operation.

Alpha is 255 over land and 0 over sea; the RGB channels are unused.

Usage:
    python scripts/make_land_mask_texture.py \\
        --out web/public/story/land-mask-mercator.png
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# Must match the textures' projection_bounds, which the packager derives from
# the grid centres rather than the full Mercator limit.
DEFAULT_LAT_MAX = 84.875
DEFAULT_MASK = REPO_ROOT / "data" / "locations" / "country_mask.npz"
DEFAULT_OUT = REPO_ROOT / "web" / "public" / "story" / "land-mask-mercator.png"


def build(mask_path: Path, width: int, height: int, lat_max: float) -> Image.Image:
    with np.load(mask_path) as f:
        data = np.asarray(f["data"])
        deg = float(f["deg"])
        src_lat_max = float(f["lat_max"])
        src_lon_min = float(f["lon_min"])
    land = data > 0
    nlat, nlon = land.shape

    max_m = math.log(math.tan(math.pi / 4 + math.radians(lat_max) / 2))
    # Row centres in Mercator y -> latitude -> source row.
    ys = (np.arange(height) + 0.5) / height
    merc = max_m - ys * 2 * max_m
    lats = np.degrees(2 * np.arctan(np.exp(merc)) - math.pi / 2)
    rows = np.clip(((src_lat_max - lats) / deg).astype(int), 0, nlat - 1)

    lons = -180.0 + (np.arange(width) + 0.5) / width * 360.0
    cols = np.clip(((lons - src_lon_min) / deg).astype(int), 0, nlon - 1)

    sampled = land[np.ix_(rows, cols)]
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    # Mid grey so any viewer that ignores alpha still sees a neutral plate.
    rgba[..., :3] = 128
    rgba[..., 3] = np.where(sampled, 255, 0)
    return Image.fromarray(rgba, mode="RGBA")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mask", type=Path, default=DEFAULT_MASK)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=2150)
    ap.add_argument("--lat-max", type=float, default=DEFAULT_LAT_MAX)
    args = ap.parse_args()

    img = build(args.mask, args.width, args.height, args.lat_max)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    img.save(args.out, "PNG", optimize=True)
    size_kb = args.out.stat().st_size / 1024
    print(f"Wrote {args.out} ({img.width}x{img.height}, {size_kb:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
