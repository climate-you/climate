#!/usr/bin/env python3
"""
Build a global water mask (1=water, 0=land) raster from Natural Earth land polygons.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import numpy as np
import requests

from climate.tiles.layout import GridSpec

NATURAL_EARTH_LAND_URLS = [
    "https://naciscdn.org/naturalearth/10m/physical/ne_10m_land.zip",
    "https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_land.zip",
]


def _grid_from_id(grid_id: str, tile_size: int) -> GridSpec:
    if grid_id == "global_0p25":
        return GridSpec.global_0p25(tile_size=tile_size)
    if grid_id == "global_0p05":
        return GridSpec.global_0p05(tile_size=tile_size)
    raise ValueError(f"Unsupported grid_id: {grid_id}")


def _http_download(url: str, dest: Path, *, timeout: int = 120) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        with tmp.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                if chunk:
                    f.write(chunk)
        tmp.replace(dest)


def _prepare_input(input_path: Path | None, cache_dir: Path) -> Path:
    if input_path is not None:
        return input_path

    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / "natural_earth_land_source.zip"
    if dest.exists() and dest.stat().st_size > 0:
        print(f"[cache] using {dest}", file=sys.stderr)
        return dest

    last_err: Exception | None = None
    for url in NATURAL_EARTH_LAND_URLS:
        try:
            print(f"[download] {url} -> {dest}", file=sys.stderr)
            _http_download(url, dest)
            return dest
        except Exception as exc:
            last_err = exc
            continue
    raise RuntimeError("Failed to download Natural Earth land polygons") from last_err


def _iter_shapes(input_path: Path) -> list[tuple[dict, int]]:
    try:
        import fiona
    except Exception as exc:
        raise RuntimeError(
            "fiona is required to read vector files. Install with: pip install fiona"
        ) from exc

    read_path: str | Path
    if input_path.suffix.lower() == ".zip":
        read_path = f"zip://{input_path}"
    else:
        read_path = input_path

    shapes: list[tuple[dict, int]] = []
    with fiona.open(str(read_path), "r") as src:
        for feat in src:
            geom = feat.get("geometry")
            if not geom:
                continue
            shapes.append((geom, 1))
    if not shapes:
        raise RuntimeError(f"No land geometries found in {input_path}")
    return shapes


def build_water_mask(
    *,
    input_path: Path,
    output_npz: Path,
    grid: GridSpec,
    all_touched_land: bool,
) -> None:
    try:
        from rasterio.features import rasterize
        from rasterio.transform import from_origin
    except Exception as exc:
        raise RuntimeError(
            "rasterio is required to rasterize polygons. Install with: pip install rasterio"
        ) from exc

    shapes = _iter_shapes(input_path)
    transform = from_origin(grid.lon_min, grid.lat_max, grid.deg, grid.deg)
    land = rasterize(
        shapes=shapes,
        out_shape=(grid.nlat, grid.nlon),
        transform=transform,
        fill=0,
        dtype="uint8",
        all_touched=all_touched_land,
    ).astype(bool)
    water = (~land).astype(np.uint8)

    output_npz.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output_npz,
        data=water,
        deg=np.float64(grid.deg),
        lat_max=np.float64(grid.lat_max),
        lon_min=np.float64(grid.lon_min),
    )
    valid = int(np.count_nonzero(water))
    total = int(water.size)
    print(
        f"[ok] wrote water mask: {output_npz} "
        f"shape={water.shape} water={valid}/{total} ({(valid/total)*100:.5f}%)"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Build a global water mask NPZ.")
    ap.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Optional local land polygons source (zip/shp/geojson).",
    )
    ap.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("data/cache/geojson"),
        help='Download cache directory (default: "data/cache/geojson").',
    )
    ap.add_argument(
        "--output-npz",
        type=Path,
        default=Path("data/masks/water_global_0p05_mask.npz"),
        help='Output NPZ path (default: "data/masks/water_global_0p05_mask.npz").',
    )
    ap.add_argument(
        "--grid-id",
        type=str,
        default="global_0p05",
        choices=["global_0p05", "global_0p25"],
    )
    ap.add_argument("--tile-size", type=int, default=64)
    ap.add_argument(
        "--all-touched-land",
        action="store_true",
        help="Rasterize land polygons with all_touched=True.",
    )
    args = ap.parse_args()

    grid = _grid_from_id(args.grid_id, int(args.tile_size))
    input_path = _prepare_input(args.input, args.cache_dir)
    build_water_mask(
        input_path=input_path,
        output_npz=args.output_npz,
        grid=grid,
        all_touched_land=bool(args.all_touched_land),
    )


if __name__ == "__main__":
    main()

