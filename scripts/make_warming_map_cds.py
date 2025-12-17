#!/usr/bin/env python3
"""Compute a baseline-to-baseline warming map from ERA5 monthly means via CDS.

This is the "real" version of the World warming raster:
warming(lat, lon) = mean(T2m over baseline_B) - mean(T2m over baseline_A)

Defaults (tweakable):
- Baseline A: 1979-1988
- Baseline B: 2016-2025
- Grid: 1.0° x 1.0° (keeps download size manageable)

Requires:
- cdsapi (`pip install cdsapi`)
- A configured ~/.cdsapirc key (Copernicus CDS API)

Dataset:
- reanalysis-era5-single-levels-monthly-means

Outputs:
- data/world/warming_map_<A>_to_<B>.nc
- data/world/warming_map_<A>_to_<B>.manifest.json

Note: This can still be a multi-GB download at fine resolution; keep grid coarse
during iteration.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Tuple

import numpy as np
import xarray as xr


@dataclass
class Baseline:
    start_year: int
    end_year: int

    def label(self) -> str:
        return f"{self.start_year}-{self.end_year}"


def _parse_baseline(s: str) -> Baseline:
    parts = s.replace("–", "-").split("-")
    if len(parts) != 2:
        raise ValueError(f"Baseline must be like '1979-1988', got: {s}")
    a, b = int(parts[0]), int(parts[1])
    if b < a:
        raise ValueError(f"Baseline end must be >= start, got: {s}")
    return Baseline(a, b)


def _years(b: Baseline) -> List[str]:
    return [str(y) for y in range(b.start_year, b.end_year + 1)]


def _download_era5_monthly_means(out_nc: Path, years: List[str], grid_deg: float, area: Tuple[float, float, float, float] | None) -> str:
    """Download monthly 2m temperature from CDS into out_nc and return the request dict as JSON string."""
    import cdsapi  # import here so the script can print a helpful error if missing

    c = cdsapi.Client()

    req = {
        "product_type": "monthly_averaged_reanalysis",
        "format": "netcdf",
        "variable": ["2m_temperature"],
        "year": years,
        "month": [f"{m:02d}" for m in range(1, 13)],
        "time": ["00:00"],
        # Coarsen the native 0.25° grid to keep files reasonable for a web app.
        "grid": [grid_deg, grid_deg],
    }
    if area is not None:
        # CDS uses [N, W, S, E]
        req["area"] = [area[0], area[1], area[2], area[3]]

    out_nc.parent.mkdir(parents=True, exist_ok=True)
    c.retrieve("reanalysis-era5-single-levels-monthly-means", req, str(out_nc))
    return json.dumps(req, indent=2)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline-a", type=str, default="1979-1988")
    ap.add_argument("--baseline-b", type=str, default="2016-2025")
    ap.add_argument("--grid-deg", type=float, default=1.0, help="Output grid resolution in degrees (e.g. 1.0)")
    ap.add_argument("--out-dir", type=Path, default=Path("data/world"))
    ap.add_argument("--area", type=str, default=None, help="Optional subset as N,W,S,E (e.g. '90,-180,-90,180')")
    args = ap.parse_args()

    bA = _parse_baseline(args.baseline_a)
    bB = _parse_baseline(args.baseline_b)

    area = None
    if args.area:
        parts = [float(x) for x in args.area.split(",")]
        if len(parts) != 4:
            raise ValueError("--area must be N,W,S,E")
        area = (parts[0], parts[1], parts[2], parts[3])

    # Download both baselines
    tmp_a = args.out_dir / f"_tmp_era5_t2m_{bA.label()}.nc"
    tmp_b = args.out_dir / f"_tmp_era5_t2m_{bB.label()}.nc"

    try:
        req_a = _download_era5_monthly_means(tmp_a, _years(bA), args.grid_deg, area)
        req_b = _download_era5_monthly_means(tmp_b, _years(bB), args.grid_deg, area)
    except ModuleNotFoundError as e:
        raise SystemExit("cdsapi is required. Install with: pip install cdsapi\nThen configure ~/.cdsapirc") from e

    # Compute warming (convert K -> °C)
    dsA = xr.open_dataset(tmp_a)
    dsB = xr.open_dataset(tmp_b)

    # ERA5 variable name is usually 't2m' in CDS netCDF; be robust.
    varA = "t2m" if "t2m" in dsA.data_vars else list(dsA.data_vars)[0]
    varB = "t2m" if "t2m" in dsB.data_vars else list(dsB.data_vars)[0]

    tA = dsA[varA] - 273.15
    tB = dsB[varB] - 273.15

    # time dimension name varies: 'time' is typical
    dim_time = "time" if "time" in tA.dims else tA.dims[0]

    meanA = tA.mean(dim=dim_time, skipna=True)
    meanB = tB.mean(dim=dim_time, skipna=True)

    warming = (meanB - meanA).astype(np.float32)
    warming.name = "warming_c"
    warming.attrs.update({
        "units": "degC",
        "long_name": f"Warming: {bB.label()} minus {bA.label()} (ERA5 monthly means)",
    })

    out_nc = args.out_dir / f"warming_map_{bA.label()}_to_{bB.label()}.nc"
    out_nc.parent.mkdir(parents=True, exist_ok=True)
    warming.to_dataset().to_netcdf(out_nc)

    # Manifest
    lat_name = "latitude" if "latitude" in warming.coords else ("lat" if "lat" in warming.coords else None)
    lon_name = "longitude" if "longitude" in warming.coords else ("lon" if "lon" in warming.coords else None)

    lat = warming[lat_name].values if lat_name else None
    lon = warming[lon_name].values if lon_name else None

    manifest = {
        "created_utc": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "dataset": "reanalysis-era5-single-levels-monthly-means",
        "variable": "2m_temperature",
        "baseline_a": asdict(bA),
        "baseline_b": asdict(bB),
        "grid_deg": args.grid_deg,
        "area": list(area) if area else None,
        "source_requests": {"baseline_a": json.loads(req_a), "baseline_b": json.loads(req_b)},
        "output": {
            "netcdf": str(out_nc),
            "value_min": float(np.nanmin(warming.values)),
            "value_max": float(np.nanmax(warming.values)),
            "lat": {"name": lat_name, "min": float(lat.min()) if lat is not None else None, "max": float(lat.max()) if lat is not None else None},
            "lon": {"name": lon_name, "min": float(lon.min()) if lon is not None else None, "max": float(lon.max()) if lon is not None else None},
        },
    }

    out_manifest = args.out_dir / f"warming_map_{bA.label()}_to_{bB.label()}.manifest.json"
    out_manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"Wrote {out_nc}")
    print(f"Wrote {out_manifest}")
    print("Tip: once you're happy with the map, you can delete the _tmp_*.nc files.")


if __name__ == "__main__":
    main()
