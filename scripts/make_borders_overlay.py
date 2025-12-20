#!/usr/bin/env python3
"""
Generate an equirectangular borders overlay (transparent PNG) for globe texturing.

- Uses Natural Earth via Cartopy (downloads cached data on first run).
- Output is a transparent PNG with coastlines + country borders.
- Projection is PlateCarree, extent [-180..180, -90..90], so it maps directly to a sphere texture.

Example:
  python scripts/make_borders_overlay.py --out data/world/borders_4096x2048.png --size 4096x2048 --scale 50m
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="Output PNG path (transparent)")
    ap.add_argument("--size", default="4096x2048", help="Output size WxH (default: 4096x2048)")
    ap.add_argument(
        "--scale",
        default="50m",
        choices=["110m", "50m", "10m"],
        help="Natural Earth scale (110m coarser, 10m finest). Default: 50m",
    )
    ap.add_argument("--coast-lw", type=float, default=1.2, help="Coastline line width (default: 1.2)")
    ap.add_argument("--borders-lw", type=float, default=0.7, help="Country borders line width (default: 0.7)")
    ap.add_argument("--alpha", type=float, default=0.85, help="Line alpha (default: 0.85)")
    args = ap.parse_args()

    out = Path(args.out)
    W, H = (int(x) for x in args.size.lower().split("x"))

    # Choose DPI so we hit exact pixel size reliably
    dpi = 200
    fig_w = W / dpi
    fig_h = H / dpi

    fig = plt.figure(figsize=(fig_w, fig_h), dpi=dpi)
    ax = plt.axes(projection=ccrs.PlateCarree())

    # Fill the figure completely, no margins
    ax.set_position([0, 0, 1, 1])
    ax.set_global()
    ax.set_extent([-180, 180, -90, 90], crs=ccrs.PlateCarree())

    # Transparent background
    fig.patch.set_alpha(0.0)
    ax.patch.set_alpha(0.0)

    # Hide axes entirely (cartopy version differences)
    ax.set_axis_off()
    # Some cartopy versions have outline_patch; others don't.
    outline = getattr(ax, "outline_patch", None)
    if outline is not None:
        outline.set_visible(False)
    # Also hide the standard Matplotlib frame, just in case
    for spine in ax.spines.values():
        spine.set_visible(False)

    # Features: coastlines + borders
    # Note: Cartopy will download/caches Natural Earth shapefiles the first time.
    coast = cfeature.COASTLINE.with_scale(args.scale)
    borders = cfeature.BORDERS.with_scale(args.scale)

    ax.add_feature(
        coast,
        edgecolor=(0, 0, 0, args.alpha),
        facecolor="none",
        linewidth=args.coast_lw,
        zorder=10,
    )
    ax.add_feature(
        borders,
        edgecolor=(0, 0, 0, args.alpha),
        facecolor="none",
        linewidth=args.borders_lw,
        zorder=11,
    )

    out.parent.mkdir(parents=True, exist_ok=True)

    # IMPORTANT: do NOT use bbox_inches="tight" (it changes the output size)
    # Ensure no padding/margins are added
    plt.subplots_adjust(left=0, right=1, bottom=0, top=1)
    fig.savefig(out, format="png", transparent=True, dpi=dpi)
    plt.close(fig)

    print(f"Wrote {out} ({W}x{H}) using Natural Earth scale={args.scale}")


if __name__ == "__main__":
    main()
