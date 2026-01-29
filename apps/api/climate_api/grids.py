from __future__ import annotations
import math

def wrap_lon_pm180(lon: float) -> float:
    # [-180, 180)
    x = ((lon + 180.0) % 360.0) - 180.0
    # treat +180 as -180
    return -180.0 if x == 180.0 else x

def clamp_lat(lat: float) -> float:
    return max(-90.0, min(90.0, lat))

def snap_cell(
    lat: float,
    lon: float,
    *,
    grid_deg: float,
    lon_mode: str = "pm180",   # "pm180" or "east"
) -> tuple[int, int, float, float]:
    """
    Returns (i_lat, i_lon, lat_center, lon_center) for a global regular grid.

    - lat is clamped to [-90,90]
    - lon normalized per lon_mode:
        pm180: [-180,180)
        east:  [0,360)
    """
    lat = clamp_lat(lat)
    if lon_mode == "pm180":
        lon = wrap_lon_pm180(lon)
        lon0 = -180.0
        lon_span = 360.0
    elif lon_mode == "east":
        lon = lon % 360.0
        lon0 = 0.0
        lon_span = 360.0
    else:
        raise ValueError(f"Unknown lon_mode: {lon_mode}")

    lat0 = -90.0
    lat_span = 180.0

    n_lat = int(round(lat_span / grid_deg))
    n_lon = int(round(lon_span / grid_deg))

    # containing-cell (floor)
    i_lat = int(math.floor((lat - lat0) / grid_deg))
    i_lon = int(math.floor((lon - lon0) / grid_deg))

    # clamp
    i_lat = max(0, min(n_lat - 1, i_lat))
    i_lon = max(0, min(n_lon - 1, i_lon))

    lat_center = lat0 + (i_lat + 0.5) * grid_deg
    lon_center = lon0 + (i_lon + 0.5) * grid_deg
    return i_lat, i_lon, lat_center, lon_center
