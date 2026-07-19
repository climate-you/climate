#!/usr/bin/env python3
"""Build a compact coastline + country-border overlay for story maps.

Story maps (web/src/components/story/AnomalyMap.tsx) draw a crop of a global
mercator anomaly texture onto a canvas. The textures carry no geography, so this
script emits the polylines drawn on top for reference.

Reads Natural Earth data via cartopy's shapereader (downloaded and cached on
first run) and writes a minimal JSON, clipped to a bounding box and simplified:

    {"bbox": [w, s, e, n], "coast": [[[lon, lat], ...], ...], "borders": [...]}

Natural Earth is public domain; see web/public/THIRD_PARTY_NOTICES.md.

Usage:
    python scripts/make_coastline_overlay.py
    python scripts/make_coastline_overlay.py --bbox -30 25 55 72 --out web/public/story/europe-lines.json
    python scripts/make_coastline_overlay.py --resolution 10m --simplify 0.01
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cartopy.io import shapereader
from shapely.geometry import LineString, MultiLineString, box

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# Europe frame used by the June–July 2026 heat story, with margin for reframing.
_DEFAULT_BBOX = (-30.0, 25.0, 55.0, 72.0)
_DEFAULT_OUT = REPO_ROOT / "web" / "public" / "story" / "europe-lines.json"
# ~2 km at these latitudes: invisible at story map sizes, but a large size win.
_DEFAULT_SIMPLIFY = 0.02
_COORD_PRECISION = 3


def _clipped_lines(
    category: str,
    name: str,
    resolution: str,
    clip: box,
    simplify: float,
) -> list[list[list[float]]]:
    """Return simplified polylines from a Natural Earth layer, clipped to bbox."""
    path = shapereader.natural_earth(
        resolution=resolution, category=category, name=name
    )
    lines: list[list[list[float]]] = []
    for geom in shapereader.Reader(path).geometries():
        clipped = geom.intersection(clip)
        if clipped.is_empty:
            continue
        if simplify > 0:
            clipped = clipped.simplify(simplify, preserve_topology=False)

        parts: list[LineString] = []
        if isinstance(clipped, LineString):
            parts = [clipped]
        elif isinstance(clipped, MultiLineString):
            parts = list(clipped.geoms)
        else:
            # GeometryCollection, or polygons from an odd intersection.
            for sub in getattr(clipped, "geoms", []):
                if isinstance(sub, LineString):
                    parts.append(sub)
                elif isinstance(sub, MultiLineString):
                    parts.extend(sub.geoms)

        for part in parts:
            coords = [
                [round(x, _COORD_PRECISION), round(y, _COORD_PRECISION)]
                for x, y in part.coords
            ]
            if len(coords) >= 2:
                lines.append(coords)
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        metavar=("WEST", "SOUTH", "EAST", "NORTH"),
        default=list(_DEFAULT_BBOX),
        help=f"Clip bounding box in degrees (default: {' '.join(str(v) for v in _DEFAULT_BBOX)})",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=_DEFAULT_OUT,
        help=f"Output JSON path (default: {_DEFAULT_OUT.relative_to(REPO_ROOT)})",
    )
    ap.add_argument(
        "--resolution",
        default="50m",
        choices=("10m", "50m", "110m"),
        help="Natural Earth resolution (default: 50m)",
    )
    ap.add_argument(
        "--simplify",
        type=float,
        default=_DEFAULT_SIMPLIFY,
        help=f"Simplification tolerance in degrees, 0 to disable (default: {_DEFAULT_SIMPLIFY})",
    )
    args = ap.parse_args()

    west, south, east, north = args.bbox
    if west >= east or south >= north:
        print("error: bbox must be WEST < EAST and SOUTH < NORTH", file=sys.stderr)
        return 1

    clip = box(west, south, east, north)
    payload = {
        "bbox": [west, south, east, north],
        "coast": _clipped_lines(
            "physical", "coastline", args.resolution, clip, args.simplify
        ),
        "borders": _clipped_lines(
            "cultural",
            "admin_0_boundary_lines_land",
            args.resolution,
            clip,
            args.simplify,
        ),
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as fh:
        json.dump(payload, fh, separators=(",", ":"))

    size_kb = args.out.stat().st_size / 1024
    print(
        f"Wrote {args.out.relative_to(REPO_ROOT)} "
        f"({len(payload['coast'])} coastline + {len(payload['borders'])} border "
        f"polylines, {size_kb:.0f} KB) at {args.resolution}, "
        f"bbox {west},{south},{east},{north}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
