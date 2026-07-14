#!/usr/bin/env python3
"""Download ERA5/ERA5T monthly-mean t2m for the June-2026 heatwave spike.

Two small CDS requests against the monthly-means product (which includes
preliminary ERA5T data for recent months):
  1. June monthly means 1991-2020  -> climatology baseline
  2. Jan-June 2026 monthly means   -> the heatwave period

Files land in data/cache/heatwave_2026/. Deliberately does not touch the
release tiles - this is the exploration path, not the ingestion pipeline.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from climate.datasets.sources.cds import retrieve
from climate.datasets.products.era5 import ERA5_MONTHLY_MEANS_DATASET

CACHE = REPO_ROOT / "data" / "cache" / "heatwave_2026"


def main() -> int:
    base = {
        "product_type": "monthly_averaged_reanalysis",
        "data_format": "netcdf",
        "variable": ["2m_temperature"],
        "time": ["00:00"],
        "grid": [0.25, 0.25],
    }

    print("[1/2] June climatology 1991-2020 ...", flush=True)
    retrieve(
        ERA5_MONTHLY_MEANS_DATASET,
        {**base, "year": [str(y) for y in range(1991, 2021)], "month": ["06"]},
        CACHE / "t2m_monthly_june_1991_2020.nc",
    )
    print("[2/2] Jan-June 2026 ...", flush=True)
    retrieve(
        ERA5_MONTHLY_MEANS_DATASET,
        {**base, "year": ["2026"], "month": [f"{m:02d}" for m in range(1, 7)]},
        CACHE / "t2m_monthly_2026_h1.nc",
    )
    print("done:", *CACHE.glob("*.nc"), sep="\n  ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
