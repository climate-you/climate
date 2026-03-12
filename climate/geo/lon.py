from __future__ import annotations

import numpy as np
import xarray as xr


def normalize_lon_pm180(lon: float) -> float:
    """
    Normalize longitude into [-180, 180).
    """
    x = float(lon)
    x = ((x + 180.0) % 360.0) - 180.0
    if x == 180.0:
        x = -180.0
    return x


def ensure_lon_pm180(ds: xr.Dataset, lon_name: str) -> xr.Dataset:
    lon = np.asarray(ds[lon_name].values, dtype=np.float64)
    if lon.min() >= 0.0 and lon.max() > 180.0:
        lon_pm180 = ((lon + 180.0) % 360.0) - 180.0
        ds = ds.assign_coords({lon_name: lon_pm180})
        ds = ds.sortby(lon_name)
    return ds


def ensure_lon_pm180_da(da: xr.DataArray, lon_name: str) -> xr.DataArray:
    lon_raw = np.asarray(da[lon_name].values, dtype=np.float64)
    lon_norm = ((lon_raw + 180.0) % 360.0) - 180.0
    if np.any(np.abs(lon_raw - lon_norm) > 1e-10):
        da = da.assign_coords({lon_name: lon_norm})
    return da.sortby(lon_name)
