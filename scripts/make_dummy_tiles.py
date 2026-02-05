#!/usr/bin/env python3
"""
Generate small dummy tiles for mixed-grid cache testing.

This writes a single tile for each dummy metric:
  - dummy1_yearly_mean_c (global_0p25)
  - dummy2_yearly_mean_c (global_0p05)

Use lat/lon in the same tile for testing. Defaults to (0, 0).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from climate.tiles.layout import GridSpec, locate_tile, tile_path
from climate.tiles.spec import write_tile


def _write_time_axis(metric_dir: Path, years: list[int]) -> None:
    time_dir = metric_dir / "time"
    time_dir.mkdir(parents=True, exist_ok=True)
    (time_dir / "yearly.json").write_text(
        json.dumps(years, indent=2) + "\n", encoding="utf-8"
    )


def _make_tile(
    *,
    tiles_root: Path,
    grid: GridSpec,
    metric: str,
    nyears: int,
    years: list[int],
    lat: float,
    lon: float,
    seed: int,
) -> Path:
    cell, tile = locate_tile(lat, lon, grid)
    tile_path_out = tile_path(
        tiles_root,
        grid,
        metric=metric,
        tile_r=tile.tile_r,
        tile_c=tile.tile_c,
        ext=".bin",
    )

    rng = np.random.default_rng(seed)
    data = rng.random((grid.tile_size, grid.tile_size, nyears), dtype=np.float32)

    write_tile(
        tile_path_out,
        data,
        dtype=np.float32,
        nyears=nyears,
        tile_h=grid.tile_size,
        tile_w=grid.tile_size,
    )

    metric_dir = tiles_root / grid.grid_id / metric
    _write_time_axis(metric_dir, years)

    return tile_path_out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--tiles-root",
        type=Path,
        default=Path("data/releases/dev/series"),
        help='Tiles root (default: "data/releases/dev/series").',
    )
    ap.add_argument(
        "--lat",
        type=float,
        default=0.0,
        help="Latitude to select a tile (default: 0.0).",
    )
    ap.add_argument(
        "--lon",
        type=float,
        default=0.0,
        help="Longitude to select a tile (default: 0.0).",
    )
    ap.add_argument(
        "--start-year",
        type=int,
        default=2000,
        help="Start year for the yearly axis.",
    )
    ap.add_argument(
        "--nyears",
        type=int,
        default=25,
        help="Number of years in the series.",
    )
    ap.add_argument(
        "--seed",
        type=int,
        default=1234,
        help="Random seed base for dummy values.",
    )
    args = ap.parse_args()

    tiles_root = Path(args.tiles_root)
    years = list(range(int(args.start_year), int(args.start_year) + int(args.nyears)))

    grid_025 = GridSpec.global_0p25(tile_size=64)
    grid_005 = GridSpec.global_0p05(tile_size=64)

    p1 = _make_tile(
        tiles_root=tiles_root,
        grid=grid_025,
        metric="dummy1_yearly_mean_c",
        nyears=args.nyears,
        years=years,
        lat=args.lat,
        lon=args.lon,
        seed=args.seed + 1,
    )
    p2 = _make_tile(
        tiles_root=tiles_root,
        grid=grid_005,
        metric="dummy2_yearly_mean_c",
        nyears=args.nyears,
        years=years,
        lat=args.lat,
        lon=args.lon,
        seed=args.seed + 2,
    )

    print(f"[ok] wrote tile: {p1}")
    print(f"[ok] wrote tile: {p2}")
    print(
        "Use lat/lon within the same tiles for testing (e.g. 0.0, 0.0 and 0.0, 0.1)."
    )


if __name__ == "__main__":
    main()
