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

import numpy as np
import requests

from climate.tiles.layout import GridSpec

NATURAL_EARTH_REEF_FALLBACK_URLS = [
    "https://naciscdn.org/naturalearth/10m/physical/ne_10m_reefs.zip",
    "https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_reefs.zip",
]
UNEP_WCMC_REEF_FALLBACK_URLS = [
    "https://data.unep-wcmc.org/datasets/1/download?type=shp",
    "https://data.unep-wcmc.org/datasets/1/download?format=SHP",
    "https://data.unep-wcmc.org/datasets/1/download",
]


def _grid_from_id(grid_id: str, tile_size: int) -> GridSpec:
    if grid_id == "global_0p25":
        return GridSpec.global_0p25(tile_size=tile_size)
    if grid_id == "global_0p05":
        return GridSpec.global_0p05(tile_size=tile_size)
    raise ValueError(f"Unsupported grid_id: {grid_id}")


def _iter_shapes(input_path: Path) -> list[tuple[dict, int]]:
    try:
        import fiona
    except Exception as exc:
        raise RuntimeError(
            "fiona is required to read vector files. Install with: pip install fiona"
        ) from exc

    if input_path.suffix.lower() == ".zip":
        read_path: Path | str = f"zip://{input_path}"
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
        raise RuntimeError(f"No reef geometries found in {input_path}")
    return shapes


def _http_download(
    url: str,
    dest: Path,
    *,
    timeout: int = 120,
    verify_ssl: bool = True,
) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=timeout, verify=verify_ssl) as r:
        r.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        with tmp.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                if chunk:
                    f.write(chunk)
        tmp.replace(dest)


def _prepare_input(
    *,
    input_path: Path | None,
    source: str,
    source_url: str | None,
    cache_dir: Path,
    verify_ssl: bool,
) -> Path:
    if input_path is not None:
        return input_path

    cache_dir.mkdir(parents=True, exist_ok=True)
    out_name = "reef_polygons_source.zip"
    dest = cache_dir / out_name
    if dest.exists() and dest.stat().st_size > 0:
        print(f"[cache] using {dest}", file=sys.stderr)
        return dest

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
            _http_download(url, dest, verify_ssl=verify_ssl)
            return dest
        except Exception as exc:
            last_err = exc
            continue

    raise RuntimeError(
        "Failed to download reef polygons from all configured URLs. "
        "You can provide --input /path/to/reef_polygons.{geojson|zip|shp} "
        "or --source-url <direct-download-url>. "
        "If failures are TLS-cert related on trusted sources, retry with --insecure."
    ) from last_err


def build_reef_mask(
    *,
    input_path: Path,
    output_npz: Path,
    grid: GridSpec,
    all_touched: bool,
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
        "--insecure",
        action="store_true",
        help="Disable TLS certificate verification for source downloads (last resort).",
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

    grid = _grid_from_id(args.grid_id, int(args.tile_size))
    input_path = _prepare_input(
        input_path=args.input,
        source=str(args.source),
        source_url=args.source_url,
        cache_dir=args.cache_dir,
        verify_ssl=not bool(args.insecure),
    )
    build_reef_mask(
        input_path=input_path,
        output_npz=args.output_npz,
        grid=grid,
        all_touched=bool(args.all_touched),
    )


if __name__ == "__main__":
    main()
