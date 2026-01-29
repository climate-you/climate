from __future__ import annotations

from climate.tiles.layout import GridSpec, locate_tile, cell_center_latlon

def show(name: str, lat: float, lon: float) -> None:
    grid = GridSpec.global_0p25(tile_size=64)
    cell, tile = locate_tile(lat, lon, grid)
    c_lat, c_lon = cell_center_latlon(cell.i_lat, cell.i_lon, grid)
    print(f"{name}: lat={lat}, lon={lon}")
    print(f"  cell: i_lat={cell.i_lat}, i_lon={cell.i_lon}  (center={c_lat:.4f}, {c_lon:.4f})")
    print(f"  tile: tile_r={tile.tile_r}, tile_c={tile.tile_c}  offsets: o_lat={tile.o_lat}, o_lon={tile.o_lon}")
    print()

if __name__ == "__main__":
    # London (approx)
    show("London", 51.5074, -0.1278)

    # Mauritius / Tamarin (from your CSV)
    show("Tamarin", -20.32556, 57.37056)
