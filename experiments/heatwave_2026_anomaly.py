#!/usr/bin/env python3
"""Compute the June-2026 t2m anomaly vs the 1991-2020 June climatology and
render anomaly maps (global + Europe).

Reads the two NetCDF files produced by heatwave_2026_download.py, computes
    anomaly = June-2026 mean  -  mean(June 1991..2020)
(a temperature difference, so Kelvin and Celsius are interchangeable), prints
summary statistics, and writes PNG maps to experiments/output/.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import xarray as xr

REPO_ROOT = Path(__file__).resolve().parents[1]
CACHE = REPO_ROOT / "data" / "cache" / "heatwave_2026"
OUT = REPO_ROOT / "experiments" / "output"

# Rough Europe bounding box (lat N->S, lon W->E)
EUROPE = dict(lat=(72, 34), lon=(-13, 40))


def _open_t2m(path: Path) -> xr.DataArray:
    ds = xr.open_dataset(path)
    da = ds["t2m"]
    # Collapse the singleton ensemble/expver coords if present.
    for c in ("number", "expver"):
        if c in da.coords and da.coords[c].size == 1:
            da = da.reset_coords(c, drop=True)
    return da


def main() -> int:
    clim_da = _open_t2m(CACHE / "t2m_monthly_june_1991_2020.nc")
    h1_da = _open_t2m(CACHE / "t2m_monthly_2026_h1.nc")

    tname = "valid_time"
    clim_june = clim_da.mean(tname)  # 1991-2020 June mean
    june_2026 = h1_da.sel({tname: h1_da[tname].dt.month == 6}).squeeze(tname)

    anomaly = (june_2026 - clim_june).rename("t2m_anomaly_c")
    anomaly.attrs["units"] = "degC"

    lat = anomaly["latitude"]
    lon = anomaly["longitude"]

    # Area weights (cos-lat) for honest regional means.
    w = np.cos(np.deg2rad(lat))

    def _regional_mean(da, box=None):
        d = da
        if box:
            d = d.sel(
                latitude=slice(box["lat"][0], box["lat"][1]),
                longitude=slice(box["lon"][0], box["lon"][1]),
            )
        ww = np.cos(np.deg2rad(d["latitude"]))
        return float(d.weighted(ww).mean(("latitude", "longitude")))

    global_mean = _regional_mean(anomaly)
    europe_mean = _regional_mean(anomaly, EUROPE)

    eu = anomaly.sel(
        latitude=slice(EUROPE["lat"][0], EUROPE["lat"][1]),
        longitude=slice(EUROPE["lon"][0], EUROPE["lon"][1]),
    )
    eu_max = float(eu.max())
    argmax = eu.where(eu == eu_max, drop=True)
    hot_lat = float(argmax["latitude"].values.ravel()[0])
    hot_lon = float(argmax["longitude"].values.ravel()[0])

    print("June 2026 t2m anomaly vs 1991-2020 June climatology")
    print(f"  Global area-weighted mean : {global_mean:+.2f} C")
    print(f"  Europe area-weighted mean : {europe_mean:+.2f} C")
    print(f"  Europe peak cell          : {eu_max:+.2f} C at "
          f"{hot_lat:.2f}N {hot_lon:.2f}E")

    _render_maps(anomaly, europe_mean, eu_max)
    return 0


def _render_maps(anomaly, europe_mean, eu_max):
    import matplotlib

    matplotlib.use("Agg")
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature
    import matplotlib.pyplot as plt

    OUT.mkdir(parents=True, exist_ok=True)
    lon = anomaly["longitude"].values
    lat = anomaly["latitude"].values
    vals = anomaly.values
    vlim = 8.0  # +/- C color range
    cmap = "RdBu_r"

    for name, extent in [
        ("global", None),
        ("europe", [EUROPE["lon"][0], EUROPE["lon"][1],
                    EUROPE["lat"][1], EUROPE["lat"][0]]),
    ]:
        fig = plt.figure(figsize=(11, 6))
        ax = plt.axes(projection=ccrs.PlateCarree())
        if extent:
            ax.set_extent(extent, crs=ccrs.PlateCarree())
        mesh = ax.pcolormesh(
            lon, lat, vals, transform=ccrs.PlateCarree(),
            cmap=cmap, vmin=-vlim, vmax=vlim, shading="auto",
        )
        ax.add_feature(cfeature.COASTLINE, linewidth=0.4)
        ax.add_feature(cfeature.BORDERS, linewidth=0.25, edgecolor="0.4")
        cb = plt.colorbar(mesh, ax=ax, orientation="horizontal",
                          pad=0.05, shrink=0.8, extend="both")
        cb.set_label("June 2026 temperature anomaly vs 1991-2020 (degC)")
        ax.set_title(
            f"June 2026 air-temperature anomaly ({name})\n"
            f"Europe mean {europe_mean:+.1f} degC, peak {eu_max:+.1f} degC"
        )
        out_path = OUT / f"heatwave_2026_anomaly_{name}.png"
        fig.savefig(out_path, dpi=130, bbox_inches="tight")
        plt.close(fig)
        print(f"  wrote {out_path}")


if __name__ == "__main__":
    raise SystemExit(main())
