from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import json
import pandas as pd
import numpy as np
import xarray as xr

from climate.tiles.layout import GridSpec, snap_to_cell_indices, cell_to_tile, tile_path
from climate.tiles.spec import write_tile


@dataclass(frozen=True)
class LocationRow:
    slug: str
    lat: float
    lon: float


def read_locations_csv(path: Path) -> list[LocationRow]:
    rows: list[LocationRow] = []
    with path.open("r", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for d in r:
            rows.append(
                LocationRow(
                    slug=d["slug"],
                    lat=float(d["lat"]),
                    lon=float(d["lon"]),
                )
            )
    return rows


def load_city_yearly_mean(nc_path: Path) -> np.ndarray:
    """
    Return yearly mean series as float32 array, shape (nyears,).
    """
    ds = xr.open_dataset(nc_path)
    try:
        da = ds["t2m_yearly_mean_c"]
        y = np.asarray(da.values, dtype=np.float32).reshape(-1)
        return y
    finally:
        ds.close()


def infer_years_from_any_city(clim_dir: Path, locs: list[LocationRow]) -> list[int]:
    for loc in locs:
        p = clim_dir / f"clim_{loc.slug}.nc"
        if not p.exists():
            continue
        ds = xr.open_dataset(p)
        try:
            if "time_yearly" not in ds.coords:
                raise RuntimeError(f"{p} missing coord time_yearly")
            t = ds["time_yearly"].values
            years = pd.to_datetime(t).year.astype(int).tolist()
            return years
        finally:
            ds.close()
    raise RuntimeError(f"No clim_*.nc found in {clim_dir} to infer yearly axis")


def write_yearly_axis_json(
    out_root: Path, grid: GridSpec, metric: str, years: list[int]
) -> Path:
    p = out_root / grid.grid_id / metric / "time" / "yearly.json"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(years, indent=2) + "\n", encoding="utf-8")
    return p


def main(
    *,
    locations_csv: Path,
    clim_dir: Path,
    out_root: Path,
    grid: GridSpec,
    metric: str = "t2m_yearly_mean_c",
    # choose the tile you want to build
    target_tile_r: int,
    target_tile_c: int,
) -> None:
    locs = read_locations_csv(locations_csv)

    years = infer_years_from_any_city(clim_dir, locs)
    axis_path = write_yearly_axis_json(out_root, grid, metric, years)
    print(f"Year axis: {axis_path} ({years[0]}..{years[-1]}, n={len(years)})")
    nyears = len(years)

    ts = grid.tile_size
    tile_h = ts
    tile_w = ts

    # Initialize tile with NaNs (unknown cells)
    tile = np.full((tile_h, tile_w, nyears), np.nan, dtype=np.float32)

    filled = 0
    for loc in locs:
        nc_path = clim_dir / f"clim_{loc.slug}.nc"
        if not nc_path.exists():
            continue

        cell = snap_to_cell_indices(loc.lat, loc.lon, grid)
        t = cell_to_tile(cell, grid)
        if (t.tile_r, t.tile_c) != (target_tile_r, target_tile_c):
            continue

        y = load_city_yearly_mean(nc_path)
        if y.size != nyears:
            # if you ever have mismatched year ranges, you’ll need alignment;
            # for dev harness we keep it strict.
            raise RuntimeError(f"{nc_path} nyears={y.size} != expected {nyears}")

        tile[t.o_lat, t.o_lon, :] = y
        filled += 1

    out_path = tile_path(
        out_root,
        grid,
        metric=metric,
        tile_r=target_tile_r,
        tile_c=target_tile_c,
        ext=".bin.zst",
    )

    write_tile(
        out_path,
        tile,
        dtype=np.dtype("float32"),
        nyears=nyears,
        tile_h=tile_h,
        tile_w=tile_w,
        compress_level=10,
    )

    print(f"Wrote {out_path}")
    print(f"Filled {filled} cells from city NetCDFs in this tile (others remain NaN).")


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(
        description="Dev packager: build one 64x64 tile from existing city NetCDFs."
    )
    p.add_argument(
        "--locations-csv", type=Path, default=Path("locations/locations.csv")
    )
    p.add_argument("--clim-dir", type=Path, default=Path("data/story_climatology"))
    p.add_argument("--out-root", type=Path, default=Path("data/releases/dev/series"))
    p.add_argument("--metric", type=str, default="t2m_yearly_mean_c")
    p.add_argument(
        "--tile-size", type=int, default=64, help="Tile size (cells), default 64"
    )
    p.add_argument(
        "--tile-r",
        type=int,
        required=True,
        help="Target tile row (latitude tile index)",
    )
    p.add_argument(
        "--tile-c",
        type=int,
        required=True,
        help="Target tile col (longitude tile index)",
    )
    args = p.parse_args()

    main(
        locations_csv=args.locations_csv,
        clim_dir=args.clim_dir,
        out_root=args.out_root,
        grid=GridSpec.global_0p25(tile_size=args.tile_size),
        metric=args.metric,
        target_tile_r=args.tile_r,
        target_tile_c=args.tile_c,
    )
