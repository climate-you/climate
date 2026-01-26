import pandas as pd
from pathlib import Path

from .erddap_specs import ERDDAP_DATASETS
from ..sources.erddap import (
    make_griddap_url,
    read_csv,
)

from ..sources.http import download_to

CRW_BASE = "https://coastwatch.noaa.gov/erddap"

# -------------------------
# Helpers
# -------------------------


def _year_blocks(start: str, end: str, block_years: int):
    y0 = int(start[:4])
    y1 = int(end[:4])
    for y in range(y0, y1 + 1, block_years):
        a = f"{y:04d}-01-01"
        b = f"{min(y + block_years - 1, y1):04d}-12-31"
        a = max(a, start)
        b = min(b, end)
        yield a, b


# -------------------------
# Fetch
# -------------------------


def fetch_box_mean(
    lat: float, lon: float, box_half_deg: float, start: str, end: str, cache_dir: Path
) -> pd.Series:
    """
    Fetch Coral Reef Watch DHW (degree_heating_week) for a small lat/lon box and return
    daily box-mean (NaNs ignored).

    Uses the ERDDAP dataset spec so we don't forget:
    - dataset id + variable name
    - dataset start date (CRW starts at 1985-03-25)
    - recommended chunking (1-year blocks to avoid 500/502 proxy errors)
    """
    spec = ERDDAP_DATASETS["crw_dhw_daily"]
    dataset_id = spec["dataset_id"]
    var = spec["var"]
    time_hms = spec.get("time_hms", "12:00:00Z")

    # Clamp to dataset availability
    start = max(start, spec.get("dataset_start", start))

    # Chunking rule (spike learning)
    block_years = int(spec.get("recommended_block_years", 1))

    lat0, lat1 = lat - box_half_deg, lat + box_half_deg
    lon0, lon1 = lon - box_half_deg, lon + box_half_deg

    series_parts = []
    for a, b in _year_blocks(start, end, block_years=block_years):
        query = (
            f"{var}[({a}T{time_hms}):1:({b}T{time_hms})]"
            f"[({lat0}):1:({lat1})]"
            f"[({lon0}):1:({lon1})]"
        )
        url = make_griddap_url(CRW_BASE, dataset_id, query, "csv")
        cache_path = (
            cache_dir
            / "crw"
            / f"crw_{dataset_id}_{lat:.4f}_{lon:.4f}_{box_half_deg:.3f}_{a}_{b}.csv"
        )

        download_to(
            url, cache_path, retries=10, timeout=(30, 300), label=f"[CRW {a[:4]}]"
        )
        df = read_csv(cache_path)

        tcol = "time" if "time" in df.columns else df.columns[0]
        df[tcol] = pd.to_datetime(df[tcol], utc=True, errors="coerce")
        df = df.dropna(subset=[tcol])

        if var not in df.columns:
            raise RuntimeError(
                f"CRW CSV missing '{var}' column; columns={list(df.columns)}"
            )

        g = df.groupby(tcol)[var].mean()
        s = pd.Series(g.values, index=pd.to_datetime(g.index.values))
        s = s.sort_index()
        s.name = "dhw"
        series_parts.append(s)

    dhw = pd.concat(series_parts).sort_index()
    dhw = dhw[~dhw.index.duplicated(keep="first")]
    return dhw
