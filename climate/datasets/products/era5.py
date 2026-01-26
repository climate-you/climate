import cdsapi
import json
from pathlib import Path
from typing import List, Tuple


def download_monthly_means(
    out_nc: Path,
    years: List[str],
    grid_deg: float,
    area: Tuple[float, float, float, float] | None,
) -> str:
    """Download monthly 2m temperature from CDS into out_nc and return the request dict as JSON string."""

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
