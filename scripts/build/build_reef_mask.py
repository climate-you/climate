#!/usr/bin/env python3
"""
Build a global reef-domain mask raster from reef polygons.

Output NPZ fields:
  - data: 2D uint8 mask (1=reef, 0=non-reef)
  - deg: grid resolution in degrees
  - lat_max: northern origin latitude
  - lon_min: western origin longitude
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import shutil
import zipfile

import fiona
import numpy as np
from rasterio.features import rasterize
from rasterio.transform import from_origin

from climate.datasets.sources.http import download_to
from climate.tiles.layout import GridSpec, grid_from_id

NATURAL_EARTH_REEF_FALLBACK_URLS = [
    "https://naciscdn.org/naturalearth/10m/physical/ne_10m_reefs.zip",
    "https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_reefs.zip",
]
UNEP_WCMC_REEF_FALLBACK_URLS = [
    "https://wcmc.io/WCMC_008",
]


def _pick_best_shapefile(candidates: list[Path]) -> Path:
    polygon_files: list[tuple[int, Path]] = []
    non_point_files: list[tuple[int, Path]] = []
    for p in candidates:
        try:
            with fiona.open(str(p), "r") as src:
                geom = str(src.schema.get("geometry", "")).lower()
                if "polygon" in geom:
                    polygon_files.append((len(src), p))
                elif "point" not in geom:
                    non_point_files.append((len(src), p))
        except Exception:
            continue
    if polygon_files:
        # Prefer the polygon layer with the largest feature count.
        polygon_files.sort(key=lambda x: x[0], reverse=True)
        return polygon_files[0][1]
    if non_point_files:
        # Fallback for Natural Earth reefs (LineString geometry).
        non_point_files.sort(key=lambda x: x[0], reverse=True)
        return non_point_files[0][1]
    raise RuntimeError(
        "No usable shapefile found in input. Expected polygon/line geometry layers."
    )


def _resolve_read_path(input_path: Path) -> Path:
    if input_path.is_dir():
        shp_files = [p for p in input_path.rglob("*.shp") if not p.name.startswith(".")]
        if not shp_files:
            raise RuntimeError(f"No shapefiles found in directory: {input_path}")
        return _pick_best_shapefile(shp_files)

    if input_path.suffix.lower() == ".zip":
        if not zipfile.is_zipfile(input_path):
            raise RuntimeError(f"Input zip is invalid: {input_path}")
        extract_dir = input_path.parent / f"{input_path.stem}_extracted"
        stamp_path = extract_dir / ".source_stamp"
        src_stamp = f"{input_path.resolve()}::{input_path.stat().st_size}::{int(input_path.stat().st_mtime)}"
        needs_extract = True
        if extract_dir.exists() and stamp_path.exists():
            try:
                needs_extract = stamp_path.read_text().strip() != src_stamp
            except Exception:
                needs_extract = True
        if needs_extract and extract_dir.exists():
            shutil.rmtree(extract_dir)
        if needs_extract:
            extract_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(input_path, "r") as zf:
                zf.extractall(extract_dir)
            stamp_path.write_text(src_stamp + "\n")
        shp_files = [
            p for p in extract_dir.rglob("*.shp") if not p.name.startswith(".")
        ]
        if not shp_files:
            # Handle stale/partial extraction defensively.
            if extract_dir.exists():
                shutil.rmtree(extract_dir)
            extract_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(input_path, "r") as zf:
                zf.extractall(extract_dir)
            stamp_path.write_text(src_stamp + "\n")
            shp_files = [
                p for p in extract_dir.rglob("*.shp") if not p.name.startswith(".")
            ]
        if not shp_files:
            raise RuntimeError(f"No shapefiles found in archive: {input_path}")
        return _pick_best_shapefile(shp_files)
    return input_path


def _iter_shapes(input_path: Path) -> list[tuple[dict, int]]:
    read_path = _resolve_read_path(input_path)

    shapes: list[tuple[dict, int]] = []
    with fiona.open(str(read_path), "r") as src:
        for feat in src:
            geom = feat.get("geometry")
            if not geom:
                continue
            shapes.append((geom, 1))
    if not shapes:
        raise RuntimeError(f"No reef geometries found in {input_path}")
    return shapes



def _prepare_input(
    *,
    input_path: Path | None,
    source: str,
    source_url: str | None,
    cache_dir: Path,
) -> Path:
    if input_path is not None:
        return input_path

    cache_dir.mkdir(parents=True, exist_ok=True)
    if source_url:
        out_name = f"reef_polygons_{source}_custom_source.zip"
    else:
        out_name = f"reef_polygons_{source}_source.zip"
    dest = cache_dir / out_name
    if dest.exists() and dest.stat().st_size > 0:
        if zipfile.is_zipfile(dest):
            print(f"[cache] using {dest}", file=sys.stderr)
            return dest
        print(f"[cache] invalid zip, redownloading: {dest}", file=sys.stderr)
        dest.unlink()

    urls: list[str]
    if source_url:
        urls = [source_url]
    elif source == "natural_earth":
        urls = NATURAL_EARTH_REEF_FALLBACK_URLS
    elif source == "unep_wcmc":
        urls = UNEP_WCMC_REEF_FALLBACK_URLS
    else:
        raise ValueError(f"Unsupported source: {source}")

    last_err: Exception | None = None
    for url in urls:
        try:
            print(f"[download] {url} -> {dest}", file=sys.stderr)
            download_to(url, dest, retries=3, timeout=(30, 120))
            if not zipfile.is_zipfile(dest):
                snippet = ""
                try:
                    snippet = dest.read_bytes()[:180].decode("utf-8", errors="replace")
                except Exception:
                    snippet = "<unreadable>"
                raise RuntimeError(
                    f"Downloaded file is not a valid zip archive: {dest} "
                    f"(url={url}, head={snippet!r})"
                )
            return dest
        except Exception as exc:
            last_err = exc
            try:
                if dest.exists():
                    dest.unlink()
            except Exception:
                pass
            continue

    raise RuntimeError(
        "Failed to download reef polygons from all configured URLs. "
        "You can provide --input /path/to/reef_polygons.{geojson|zip|shp} "
        "or --source-url <direct-download-url>."
    ) from last_err


def build_reef_mask(
    *,
    input_path: Path,
    output_npz: Path,
    grid: GridSpec,
    all_touched: bool,
) -> None:
    shapes = _iter_shapes(input_path)
    transform = from_origin(grid.lon_min, grid.lat_max, grid.deg, grid.deg)
    mask = rasterize(
        shapes=shapes,
        out_shape=(grid.nlat, grid.nlon),
        transform=transform,
        fill=0,
        dtype="uint8",
        all_touched=all_touched,
    )

    output_npz.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output_npz,
        data=mask.astype(np.uint8, copy=False),
        deg=np.float64(grid.deg),
        lat_max=np.float64(grid.lat_max),
        lon_min=np.float64(grid.lon_min),
    )
    valid = int(np.count_nonzero(mask))
    total = int(mask.size)
    print(
        f"[ok] wrote reef mask: {output_npz} "
        f"shape={mask.shape} valid={valid}/{total} ({(valid/total)*100:.5f}%)"
    )


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Rasterize reef polygons to a regular grid mask NPZ."
    )
    ap.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Optional input reef polygons (GeoJSON/Shapefile/zip). "
        "If omitted, file is downloaded and cached.",
    )
    ap.add_argument(
        "--source",
        type=str,
        default="natural_earth",
        choices=["natural_earth", "unep_wcmc"],
        help='Built-in source used when --input is omitted (default: "natural_earth").',
    )
    ap.add_argument(
        "--source-url",
        type=str,
        default=None,
        help="Optional direct download URL override for reef polygons.",
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
        default=Path("data/masks/reef_global_0p05_mask.npz"),
        help='Output NPZ path (default: "data/masks/reef_global_0p05_mask.npz").',
    )
    ap.add_argument(
        "--grid-id",
        type=str,
        default="global_0p05",
        choices=["global_0p05", "global_0p25"],
        help='Target grid id (default: "global_0p05").',
    )
    ap.add_argument(
        "--tile-size",
        type=int,
        default=64,
        help="Tile size used to instantiate GridSpec (default: 64).",
    )
    ap.add_argument(
        "--all-touched",
        action="store_true",
        help="Use rasterio all_touched=True for more inclusive polygon edges.",
    )
    args = ap.parse_args()

    grid = grid_from_id(args.grid_id, tile_size=int(args.tile_size))
    input_path = _prepare_input(
        input_path=args.input,
        source=str(args.source),
        source_url=args.source_url,
        cache_dir=args.cache_dir,
    )
    build_reef_mask(
        input_path=input_path,
        output_npz=args.output_npz,
        grid=grid,
        all_touched=bool(args.all_touched),
    )


if __name__ == "__main__":
    main()
