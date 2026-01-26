import pandas as pd
import xarray as xr
from typing import Optional
from pathlib import Path
from typing import Tuple


from .erddap_specs import ERDDAP_DATASETS
from ..sources.erddap import (
    read_csv,
    build_griddap_query,
    make_griddap_url,
)
from ..sources.http import download_to

# OISST v2.1 daily via ERDDAP
OISST_BASES = [
    "https://coastwatch.pfeg.noaa.gov/erddap",
    "https://upwell.pfeg.noaa.gov/erddap",
]


# -------------------------
# Helpers
# -------------------------


def _lon_pm180(lon: float) -> float:
    lon_q = lon
    if lon_q > 180:
        lon_q -= 360
    if lon_q < -180:
        lon_q += 360
    return lon_q


def _year_blocks(start: str, end: str, block_years: int):
    y0 = int(start[:4])
    y1 = int(end[:4])
    for y in range(y0, y1 + 1, block_years):
        a = f"{y:04d}-01-01"
        b = f"{min(y + block_years - 1, y1):04d}-12-31"
        a = max(a, start)
        b = min(b, end)
        yield a, b


def _pick_first_present(cols: list[str], candidates: list[str]) -> str | None:
    s = set(cols)
    for c in candidates:
        if c in s:
            return c
    return None


# -------------------------
# Fetch functions
# -------------------------


def fetch_daily_point(
    lat: float,
    lon: float,
    start: str,
    end: str,
    cache_dir: Path,
) -> pd.Series:
    """
    Fetch OISST daily SST via ERDDAP (Spike-style robust approach):

    - Request a small bbox around the target point.
    - Then pick the nearest (lat, lon) row per timestamp locally.

    IMPORTANT:
    Some ERDDAP griddap datasets have latitude axis descending.
    ERDDAP expects range constraints to follow the axis order; otherwise it can return
    404 "no matching results". So we try both lat-range orders (and lon-range orders
    as a safeguard) when we hit a 404.
    """
    lon_pm = _lon_pm180(lon)

    half = 0.26
    lat0, lat1 = lat - half, lat + half
    lon0, lon1 = lon_pm - half, lon_pm + half

    spec = ERDDAP_DATASETS["oisst_sst_v21_daily"]

    # Clamp to dataset availability (don’t force callers to remember dataset starts)
    start = max(start, spec.get("dataset_start", start))

    def build_query(
        a: str, b: str, la0: float, la1: float, lo0: float, lo1: float
    ) -> str:
        return build_griddap_query(
            spec,
            a_date=a,
            b_date=b,
            lat0=la0,
            lat1=la1,
            lon0=lo0,
            lon1=lo1,
        )

    series_parts = []
    for a, b in _year_blocks(start, end, block_years=5):
        ok = False
        last_err: Optional[Exception] = None

        # try lat order normal then flipped; lon normal then flipped (lon flip is rarely needed)
        variants = [
            (lat0, lat1, lon0, lon1),
            (lat1, lat0, lon0, lon1),
            (lat0, lat1, lon1, lon0),
            (lat1, lat0, lon1, lon0),
        ]

        dataset_id = spec["dataset_id"]
        for base in OISST_BASES:
            for la0, la1, lo0, lo1 in variants:
                query = build_query(a, b, la0, la1, lo0, lo1)
                url = make_griddap_url(base, dataset_id, query, "csv")
                cache_path = (
                    cache_dir
                    / "oisst"
                    / f"oisst_{dataset_id}_{lat:.4f}_{lon:.4f}_{a}_{b}.csv"
                )

                try:
                    download_to(
                        url,
                        cache_path,
                        retries=6,
                        timeout=(30, 300),
                        label=f"[OISST {a[:4]}]",
                    )
                    df = read_csv(cache_path)

                    tcol = "time" if "time" in df.columns else df.columns[0]
                    df[tcol] = pd.to_datetime(df[tcol], utc=True, errors="coerce")
                    df = df.dropna(subset=[tcol])

                    var = spec["var"]
                    if var not in df.columns:
                        raise RuntimeError(
                            f"OISST CSV missing '{var}' column; columns={list(df.columns)}"
                        )

                    lat_col = _pick_first_present(
                        list(df.columns),
                        spec.get("lat_col_candidates", ["latitude", "lat"]),
                    )
                    lon_col = _pick_first_present(
                        list(df.columns),
                        spec.get("lon_col_candidates", ["longitude", "lon"]),
                    )
                    if lat_col is None or lon_col is None:
                        raise RuntimeError(
                            f"OISST CSV missing lat/lon columns; columns={list(df.columns)}"
                        )

                    df["d2"] = (df[lat_col] - lat) ** 2 + (df[lon_col] - lon_pm) ** 2
                    df = df.sort_values("d2").drop_duplicates(
                        subset=[tcol], keep="first"
                    )

                    s = pd.Series(df[var].values, index=pd.to_datetime(df[tcol].values))
                    s = s.sort_index()
                    s = s[~s.index.duplicated(keep="first")]
                    s.name = "sst_c"
                    series_parts.append(s)

                    ok = True
                    break

                except Exception as e:
                    last_err = e
                    # If it's a 404, try next variant/base; otherwise also try (since PFEL can be flaky).
                    # But 404 is the main signal for "bad constraint ordering / no matches".
                    continue

            if ok:
                break

        if not ok:
            raise RuntimeError(f"OISST failed for {a}..{b}. Last error: {last_err}")

    sst = pd.concat(series_parts).sort_index()
    sst = sst[~sst.index.duplicated(keep="first")]
    sst = sst.dropna()
    return sst


def fetch_grid_mean(
    lat: float,
    lon: float,
    start: str,
    end: str,
    *,
    span_deg: float,
    stride_time: int,
    stride_lat: int,
    stride_lon: int,
    cache_dir: Path,
) -> xr.DataArray:
    """
    Fetch a small OISST gridded subset around (lat, lon) and return time-mean SST (°C).

    This is used to build a cached left-side SST anomaly map (recent mean minus baseline mean).
    We intentionally sample coarsely (stride_time, stride_lat/lon) to keep downloads small.
    """
    spec = ERDDAP_DATASETS["oisst_sst_v21_daily"]
    dataset_id = spec["dataset_id"]
    var = spec["var"]

    lon_pm = _lon_pm180(lon)

    # Clamp to dataset availability
    start = max(start, spec.get("dataset_start", start))

    lat0, lat1 = lat - span_deg, lat + span_deg
    lon0, lon1 = lon_pm - span_deg, lon_pm + span_deg

    # Safeguard against invalid ranges
    lat0 = max(-89.9, float(lat0))
    lat1 = min(89.9, float(lat1))

    variants = [
        (lat0, lat1, lon0, lon1),
        (lat1, lat0, lon0, lon1),
        (lat0, lat1, lon1, lon0),
        (lat1, lat0, lon1, lon0),
    ]

    last_err: Optional[Exception] = None

    for base in OISST_BASES:
        for la0, la1, lo0, lo1 in variants:
            query = build_griddap_query(
                spec,
                a_date=start,
                b_date=end,
                lat0=la0,
                lat1=la1,
                lon0=lo0,
                lon1=lo1,
                stride_time=stride_time,
                stride_lat=stride_lat,
                stride_lon=stride_lon,
            )
            url = make_griddap_url(base, dataset_id, query, "nc")

            cache_path = (
                cache_dir
                / "oisst_grid"
                / f"oisst_grid_{dataset_id}_{lat:.4f}_{lon:.4f}_span{span_deg:.2f}"
                / f"{start}_{end}_t{int(stride_time)}_xy{int(stride_lat)}.nc"
            )

            try:
                download_to(
                    url,
                    cache_path,
                    retries=6,
                    timeout=(30, 300),
                    label=f"[OISST-GRID {start[:4]}]",
                )
                ds = xr.open_dataset(cache_path)
                if var not in ds:
                    raise RuntimeError(
                        f"OISST grid nc missing '{var}'. vars={list(ds.data_vars)}"
                    )

                da = ds[var]
                # OISST uses zlev; it should be length-1
                if "zlev" in da.dims:
                    da = da.isel(zlev=0)

                # Mean over time; keep lat/lon as provided
                if "time" in da.dims:
                    da = da.mean("time", skipna=True)

                da = da.load()
                ds.close()
                return da

            except Exception as e:
                last_err = e
                continue

    raise RuntimeError(f"OISST grid fetch failed for {start}..{end}: {last_err}")
