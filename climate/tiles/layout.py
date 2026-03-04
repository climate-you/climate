# climate/tiles/layout.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import math

from climate.geo import normalize_lon_pm180


@dataclass(frozen=True)
class GridSpec:
    """
    Defines a regular lat/lon grid and how we map (lat,lon) to cell indices.

    Conventions:
    - lat in [-90, +90], lon in [-180, +180] (we normalize lon into that range)
    - "containing-cell" snap:
        lat cell covers [lat0, lat0+deg) (except edge handling)
        lon cell covers [lon0, lon0+deg)
    - i_lat increases from north to south (row 0 is the northernmost band)
    - i_lon increases from west to east (col 0 is -180..)
    """

    grid_id: str
    deg: float
    nlat: int
    nlon: int
    tile_size: int

    lat_max: float = 90.0
    lon_min: float = -180.0
    lon_max: float = 180.0

    @staticmethod
    def global_0p25(tile_size: int = 64) -> "GridSpec":
        # Strict global cell grid at 0.25°:
        # lat: 720 cells (centers 89.875..-89.875, edges at +/-90)
        # lon: 1440 cells (-180..180 exclusive)
        return GridSpec(
            grid_id="global_0p25",
            deg=0.25,
            nlat=720,
            nlon=1440,
            tile_size=tile_size,
        )

    @staticmethod
    def global_0p05(tile_size: int = 64) -> "GridSpec":
        # Strict global cell grid at 0.05°:
        # lat: 3600 cells (centers 89.975..-89.975, edges at +/-90)
        # lon: 7200 cells (-180..180 exclusive)
        return GridSpec(
            grid_id="global_0p05",
            deg=0.05,
            nlat=3600,
            nlon=7200,
            tile_size=tile_size,
        )


@dataclass(frozen=True)
class CellIndex:
    i_lat: int
    i_lon: int


@dataclass(frozen=True)
class TileIndex:
    tile_r: int
    tile_c: int
    o_lat: int
    o_lon: int


def snap_to_cell_indices(lat: float, lon: float, grid: GridSpec) -> CellIndex:
    """
    Snap (lat,lon) to the containing cell indices (i_lat, i_lon) for the grid.

    i_lat: 0..nlat-1, north->south
    i_lon: 0..nlon-1, west->east
    """
    deg = float(grid.deg)

    # Clamp latitude to just inside the valid range to avoid falling off the edge
    # when lat == +90 or lat == -90.
    lat_clamped = max(-grid.lat_max + 1e-12, min(grid.lat_max - 1e-12, float(lat)))

    lon_norm = normalize_lon_pm180(lon)
    # lon is in [-180,180). If lon == 180, it becomes -180 via normalize.
    # Now compute west->east index
    i_lon = int(math.floor((lon_norm - grid.lon_min) / deg))
    # Defensive clamp
    if i_lon < 0:
        i_lon = 0
    elif i_lon >= grid.nlon:
        i_lon = grid.nlon - 1

    # For i_lat we use north->south: row 0 corresponds to [90-deg, 90)
    # Compute distance from the "north edge" downwards.
    # lat bands are deg tall; containing cell = floor((lat_max - lat) / deg)
    i_lat = int(math.floor((grid.lat_max - lat_clamped) / deg))
    if i_lat < 0:
        i_lat = 0
    elif i_lat >= grid.nlat:
        i_lat = grid.nlat - 1

    return CellIndex(i_lat=i_lat, i_lon=i_lon)


def cell_to_tile(cell: CellIndex, grid: GridSpec) -> TileIndex:
    """
    Convert global cell indices into:
      - tile_r, tile_c: which tile file
      - o_lat, o_lon: offset inside tile
    """
    ts = int(grid.tile_size)

    tile_r = cell.i_lat // ts
    tile_c = cell.i_lon // ts
    o_lat = cell.i_lat % ts
    o_lon = cell.i_lon % ts

    return TileIndex(tile_r=tile_r, tile_c=tile_c, o_lat=o_lat, o_lon=o_lon)


def tile_counts(grid: GridSpec) -> tuple[int, int]:
    """
    Number of tiles in (lat, lon) directions, rounding up.
    """
    ts = int(grid.tile_size)
    n_tiles_lat = (grid.nlat + ts - 1) // ts
    n_tiles_lon = (grid.nlon + ts - 1) // ts
    return n_tiles_lat, n_tiles_lon


def tile_path(
    root: str | Path,
    grid: GridSpec,
    *,
    metric: str,
    tile_r: int,
    tile_c: int,
    ext: str = ".bin.zst",
) -> Path:
    """
    Build a path like:
      {root}/{grid_id}/{metric}/z{tile_size}/r{tile_r:03d}_c{tile_c:03d}.bin.zst

    Example:
      data/releases/2026-01/series/global_0p25/t2m_yearly_mean_c/z64/r002_c014.bin.zst
    """
    root = Path(root)
    zdir = f"z{int(grid.tile_size)}"
    fname = f"r{int(tile_r):03d}_c{int(tile_c):03d}{ext}"
    return root / grid.grid_id / metric / zdir / fname


def interest_tile_path(
    root: str | Path,
    grid: GridSpec,
    *,
    tile_r: int,
    tile_c: int,
    ext: str = ".bin.zst",
) -> Path:
    """
    Build a path like:
      {root}/{grid_id}/interest/z{tile_size}/r{tile_r:03d}_c{tile_c:03d}.bin.zst

    Example:
      data/releases/2026-01/grids/global_0p25/interest/z64/r002_c014.bin.zst
    """
    root = Path(root)
    zdir = f"z{int(grid.tile_size)}"
    fname = f"r{int(tile_r):03d}_c{int(tile_c):03d}{ext}"
    return root / grid.grid_id / "interest" / zdir / fname


def locate_tile(
    lat: float,
    lon: float,
    grid: GridSpec,
) -> tuple[CellIndex, TileIndex]:
    """
    Convenience: (lat,lon) -> (cell indices, tile indices)
    """
    cell = snap_to_cell_indices(lat, lon, grid)
    tile = cell_to_tile(cell, grid)
    return cell, tile


def cell_center_latlon(i_lat: int, i_lon: int, grid: GridSpec) -> tuple[float, float]:
    deg = float(grid.deg)
    lat = grid.lat_max - (float(i_lat) + 0.5) * deg
    lon = grid.lon_min + (float(i_lon) + 0.5) * deg
    # lon is already in [-180,180) for our grid
    return lat, lon
