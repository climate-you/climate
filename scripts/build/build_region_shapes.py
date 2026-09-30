#!/usr/bin/env python3
"""
Polygonise the region masks into the outlines the explorer draws on the map.

Reads the 0.05° country and ocean masks — the same rasters the regional
aggregates are computed over — and writes one GeoJSON geometry per region to
data/locations/region_shapes.json, keyed by region id ("country:FR").

The masks, not the Natural Earth polygons they were rasterised from, because a
mask is exactly what its regional average covers: an outline drawn from it can
never claim an island the average left out, or a stretch of sea that a
neighbouring basin took. See docs/plans/region-panels-and-area-overlay-plan.md §5.

The outline follows the 0.05° cells, the finest grid any layer is drawn on, so
it is never coarser than the data inside it. It is not simplified: exactness is
the point, and a staircase of 0.05° steps compresses well on the wire.

Run it after the masks it reads:

    python scripts/build/build_locations.py --write-country-mask ...
    python scripts/build/build_ocean_mask.py
    python scripts/build/build_region_shapes.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
from rasterio.features import shapes
from rasterio.transform import from_origin
from scipy.ndimage import find_objects

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from climate.geo.regions import country_region_id, ocean_region_id  # noqa: E402

LOCATIONS = REPO_ROOT / "data" / "locations"

# Every vertex lies on a 0.05° cell corner, which two decimals represent
# exactly; more would only carry floating-point noise into the file.
_COORD_DECIMALS = 2


def _load_mask(path: Path) -> tuple[np.ndarray, float, float, float]:
    """The mask array and its grid: (data, deg, lat_max, lon_min)."""
    with np.load(path, allow_pickle=False) as z:
        return (
            np.asarray(z["data"]),
            float(z["deg"]),
            float(z["lat_max"]),
            float(z["lon_min"]),
        )


def polygonise_regions(
    mask: np.ndarray,
    *,
    deg: float,
    lat_max: float,
    lon_min: float,
    region_ids: dict[int, str],
) -> dict[str, dict[str, Any]]:
    """One GeoJSON MultiPolygon per region with at least one cell in `mask`.

    `region_ids` maps a mask value to its region id; values it does not name
    are skipped, as is 0, the background. Each region is polygonised within its
    own bounding box, found for every region in one pass, rather than across
    the whole grid.
    """
    out: dict[str, dict[str, Any]] = {}
    for value, window in enumerate(find_objects(mask), start=1):
        if window is None or value not in region_ids:
            continue
        cells = mask[window] == value
        rows, cols = window
        transform = from_origin(
            lon_min + cols.start * deg, lat_max - rows.start * deg, deg, deg
        )
        polygons = [
            [
                [
                    [round(x, _COORD_DECIMALS), round(y, _COORD_DECIMALS)]
                    for x, y in ring
                ]
                for ring in geometry["coordinates"]
            ]
            for geometry, inside in shapes(
                cells.astype(np.uint8), mask=cells, transform=transform
            )
            if inside == 1
        ]
        if polygons:
            out[region_ids[value]] = {"type": "MultiPolygon", "coordinates": polygons}
    return out


def _country_region_ids(codes_json: Path) -> dict[int, str]:
    codes = json.loads(codes_json.read_text(encoding="utf-8"))
    return {int(k): country_region_id(v) for k, v in codes.items() if v}


def _ocean_region_ids(names_json: Path) -> dict[int, str]:
    names = json.loads(names_json.read_text(encoding="utf-8"))
    return {int(k): ocean_region_id(v) for k, v in names.items() if v}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--country-mask", type=Path, default=LOCATIONS / "country_mask.npz")
    ap.add_argument(
        "--country-codes", type=Path, default=LOCATIONS / "country_codes.json"
    )
    ap.add_argument("--ocean-mask", type=Path, default=LOCATIONS / "ocean_mask.npz")
    ap.add_argument("--ocean-names", type=Path, default=LOCATIONS / "ocean_names.json")
    ap.add_argument(
        "--ocean-overlay-mask",
        type=Path,
        default=LOCATIONS / "ocean_overlay_mask.npz",
        help="Seas lying inside another sea (the Great Barrier Reef); skipped if absent",
    )
    ap.add_argument("--out", type=Path, default=LOCATIONS / "region_shapes.json")
    args = ap.parse_args()

    ocean_region_ids = _ocean_region_ids(args.ocean_names)
    masks = [
        (args.country_mask, _country_region_ids(args.country_codes)),
        (args.ocean_mask, ocean_region_ids),
    ]
    # Last, so an overlay sea's full extent replaces whatever the partition
    # left it — the same precedence the aggregates give it.
    if args.ocean_overlay_mask.exists():
        masks.append((args.ocean_overlay_mask, ocean_region_ids))

    shapes_by_region: dict[str, dict[str, Any]] = {}
    for mask_path, region_ids in masks:
        mask, deg, lat_max, lon_min = _load_mask(mask_path)
        found = polygonise_regions(
            mask, deg=deg, lat_max=lat_max, lon_min=lon_min, region_ids=region_ids
        )
        print(f"[ok] {mask_path.name}: {len(found)} regions outlined", file=sys.stderr)
        shapes_by_region.update(found)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(shapes_by_region, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    size_kb = args.out.stat().st_size / 1024
    print(
        f"[ok] wrote {args.out} ({len(shapes_by_region)} regions, {size_kb:,.0f} KB)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
