#!/usr/bin/env python3
"""
Create Monte Carlo sampling experiments from ERA5 daily mean 2m temperature NetCDFs
downloaded from CDS (derived-era5-single-levels-daily-statistics).

Inputs (preferred, split-by-year):
  data/mc/era5_daily_t2m_1979-1988_gridX.meta.json   # lists year_files
  data/mc/era5_daily_t2m_2016-2025_gridX.meta.json   # lists year_files
  data/mc/era5_daily_t2m_<YEAR>_gridX.nc             # one per year listed above

Inputs (fallback, if you built combined files yourself):
  data/mc/era5_daily_t2m_1979-1988_gridX.nc
  data/mc/era5_daily_t2m_2016-2025_gridX.nc

Outputs:
  data/mc/experiments/experiment_01_samples.parquet              # 2 * n_samples rows (past + recent)
  data/mc/experiments/experiment_01_samples.meta.json
  data/mc/experiments/experiment_01_convergence.png              # only when --visualise is set
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

import matplotlib.pyplot as plt

def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _guess_lat_lon_names(da: xr.DataArray) -> tuple[str, str]:
    # Common CDS / CF names
    for lat in ("latitude", "lat"):
        if lat in da.coords or lat in da.dims:
            lat_name = lat
            break
    else:
        raise RuntimeError(f"Could not find latitude coord. coords={list(da.coords)} dims={list(da.dims)}")

    for lon in ("longitude", "lon"):
        if lon in da.coords or lon in da.dims:
            lon_name = lon
            break
    else:
        raise RuntimeError(f"Could not find longitude coord. coords={list(da.coords)} dims={list(da.dims)}")

    return lat_name, lon_name


def _guess_time_name(da: xr.DataArray, *, lat_name: str, lon_name: str) -> str:
    # Prefer common names
    for t in ("time", "valid_time", "date"):
        if t in da.coords or t in da.dims:
            return t

    # Fallback: assume the "other" dimension (not lat/lon) is time
    other_dims = [d for d in da.dims if d not in (lat_name, lon_name)]
    if len(other_dims) == 1:
        return other_dims[0]

    raise RuntimeError(
        f"Could not infer time dimension. dims={list(da.dims)} "
        f"(lat={lat_name}, lon={lon_name})"
    )


def _open_era_dataset(data_dir: Path, *, era_label: str, grid_deg: float) -> xr.Dataset:
    """
    Prefer the era meta json (split-by-year), else fall back to a combined nc file.
    """
    g = f"{grid_deg}"
    meta = data_dir / f"era5_daily_t2m_{era_label}_grid{g}.meta.json"
    nc = data_dir / f"era5_daily_t2m_{era_label}_grid{g}.nc"

    if meta.exists():
        j = json.loads(meta.read_text(encoding="utf-8"))
        year_files = [Path(p) for p in j.get("year_files", [])]
        if not year_files:
            raise RuntimeError(f"{meta} exists but has no year_files")

        missing = [p for p in year_files if not p.exists()]
        if missing:
            raise RuntimeError(f"{meta} lists missing year files (first 5): {missing[:5]}")

        ds = xr.open_mfdataset([str(p) for p in year_files], combine="by_coords")
        if "time" in ds.coords:
            ds = ds.sortby("time")
        elif "valid_time" in ds.coords:
            ds = ds.sortby("valid_time")
        return ds

    if nc.exists():
        return xr.open_dataset(nc)

    raise FileNotFoundError(
        f"Missing inputs for era={era_label}. Expected:\n  {meta}\n  {nc}\n"
        f"Run download_era5_daily_t2m_cds.py first."
    )


def _guess_var_t2m(ds: xr.Dataset) -> str:
    # CDS often uses "t2m" for 2m temperature; be defensive.
    for cand in ("t2m", "2m_temperature", "t2m_daily_mean", "t2m_mean"):
        if cand in ds.data_vars:
            return cand
    if len(ds.data_vars) == 1:
        return list(ds.data_vars)[0]
    raise RuntimeError(f"Could not guess 2m temp variable. Vars: {list(ds.data_vars)}")


def _to_celsius(da: xr.DataArray) -> xr.DataArray:
    units = (da.attrs.get("units") or "").lower()
    if units in ("k", "kelvin"):
        out = da - 273.15
        out.attrs["units"] = "degC"
        return out
    # Some files might already be degC.
    return da


def _lon_to_180(lon0_360: np.ndarray) -> np.ndarray:
    # -> [-180, 180)
    lon = np.asarray(lon0_360, dtype="float64")
    return ((lon + 180.0) % 360.0) - 180.0



def _build_equal_area_lat_bands(lat_vals: np.ndarray, n_bands: int) -> list[np.ndarray]:
    """
    Split latitude indices into ~equal-area bands.
    Uses cos(lat) as the per-lat-row area proxy (lon spacing assumed uniform).
    Returns a list of index arrays, one per band.
    """
    lats = np.asarray(lat_vals, dtype="float64")
    w = np.cos(np.deg2rad(lats))
    w = np.clip(w, 0.0, None)
    if not np.isfinite(w).all() or w.sum() <= 0:
        raise ValueError("Bad latitude weights for latbands")

    cum = np.cumsum(w)
    edges = np.linspace(0.0, cum[-1], n_bands + 1)

    # band id for each latitude index (0..n_bands-1)
    band_id = np.searchsorted(edges[1:-1], cum, side="right")
    bands = [np.where(band_id == b)[0] for b in range(n_bands)]
    # Guard against empty bands (can happen with tiny n_bands / weird grids)
    bands = [b for b in bands if b.size > 0]
    return bands


def _sample_lat_lon_indices_latbands(
    rng: np.random.Generator,
    *,
    lat_vals: np.ndarray,
    n_lon: int,
    n: int,
    n_bands: int,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Draw (lat_idx, lon_idx) so that:
      - we take ~equal counts from ~equal-area latitude bands
      - within a band, lat indices are chosen proportional to cos(lat)
      - lon is uniform
    Net effect: close to uniform-on-sphere sampling, with lower variance.
    """
    bands = _build_equal_area_lat_bands(lat_vals, n_bands=n_bands)

    lats = np.asarray(lat_vals, dtype="float64")
    w_lat = np.cos(np.deg2rad(lats))
    w_lat = np.clip(w_lat, 0.0, None)

    base = n // len(bands)
    rem = n - base * len(bands)

    lat_idx_parts = []
    for bi, lat_ix in enumerate(bands):
        k = base + (1 if bi < rem else 0)
        p = w_lat[lat_ix]
        p = p / p.sum()
        lat_idx_parts.append(rng.choice(lat_ix, size=k, replace=True, p=p))

    lat_idx = np.concatenate(lat_idx_parts, axis=0)
    lon_idx = rng.integers(0, n_lon, size=n, endpoint=False)

    # Shuffle so bands aren't clumped (optional, but nice)
    perm = rng.permutation(n)
    return lat_idx[perm], lon_idx[perm]


def _sample_time_indices_doy_stratified(
    rng: np.random.Generator, times: pd.DatetimeIndex, n: int
) -> np.ndarray:
    """
    Sample time indices with day-of-year stratification.

    Allocate sample counts per day-of-year proportional to how many times that
    DOY appears in the dataset (e.g., Feb 29 appears only in leap years).
    This preserves the target distribution "uniform over days in the dataset"
    while strongly reducing seasonal imbalance across seeds.
    """
    doy = times.dayofyear.to_numpy()

    # indices per doy
    max_doy = int(doy.max())  # 365 or 366
    idx_by = {d: np.flatnonzero(doy == d) for d in range(1, max_doy + 1)}
    sizes = np.array([len(idx_by[d]) for d in range(1, max_doy + 1)], dtype=np.int64)

    if sizes.sum() == 0:
        raise RuntimeError("No time indices found for day-of-year stratification")

    weights = sizes / sizes.sum()
    expected = weights * float(n)
    base = np.floor(expected).astype(np.int64)
    rem = int(n - base.sum())
    if rem > 0:
        frac = expected - base
        order = np.argsort(-frac)
        base[order[:rem]] += 1

    out = np.empty(n, dtype=np.int32)
    pos = 0
    for di, d in enumerate(range(1, max_doy + 1)):
        k = int(base[di])
        if k <= 0:
            continue
        choices = rng.choice(idx_by[d], size=k, replace=True).astype(np.int32, copy=False)
        out[pos : pos + k] = choices
        pos += k

    rng.shuffle(out)
    return out


def _sample_time_indices_month_stratified(
    rng: np.random.Generator, times: pd.DatetimeIndex, n: int
) -> np.ndarray:
    """
    Sample time indices with month stratification.

    We allocate sample counts per month proportional to the number of available
    days in that month in the dataset. This keeps the target distribution
    "uniform over days", but reduces seasonal imbalance across random seeds.
    """
    months = times.month.to_numpy()

    # Indices per month
    idx_by_month = {m: np.flatnonzero(months == m) for m in range(1, 13)}
    sizes = np.array([len(idx_by_month[m]) for m in range(1, 13)], dtype=np.int64)
    if sizes.sum() == 0:
        raise RuntimeError("No time indices found for month stratification")

    # Allocate counts proportional to available days (so Feb naturally gets fewer than Jan)
    weights = sizes / sizes.sum()
    expected = weights * float(n)
    base = np.floor(expected).astype(np.int64)
    rem = int(n - base.sum())
    if rem > 0:
        frac = expected - base
        # Deterministic: give the remaining samples to the largest fractional parts
        order = np.argsort(-frac)
        base[order[:rem]] += 1

    # Draw within each month (with replacement)
    out = np.empty(n, dtype=np.int32)
    pos = 0
    for mi, m in enumerate(range(1, 13)):
        k = int(base[mi])
        if k <= 0:
            continue
        choices = rng.choice(idx_by_month[m], size=k, replace=True).astype(np.int32, copy=False)
        out[pos : pos + k] = choices
        pos += k

    # Shuffle so time indices are not month-blocked (keeps downstream behavior “random”)
    rng.shuffle(out)
    return out


def _sample_lat_indices_area_weighted(rng: np.random.Generator, lats: np.ndarray, n: int) -> np.ndarray:
    # weight proportional to cos(lat)
    w = np.cos(np.deg2rad(lats))
    w = np.clip(w, 0.0, None)
    w = w / w.sum()
    cdf = np.cumsum(w)
    u = rng.random(n)
    return np.searchsorted(cdf, u, side="right").astype(np.int32)


@dataclass(frozen=True)
class EraSpec:
    name: str
    start_year: int
    end_year: int
    nc_path: str


def _sample_from_ds(
    *,
    ds: xr.Dataset,
    era_name: str,
    era_id: int,
    n: int,
    rng: np.random.Generator,
    time_sampling: str,
    space_sampling: str,
    n_lat_bands: int,
) -> pd.DataFrame:
    var = _guess_var_t2m(ds)
    da = _to_celsius(ds[var])

    lat_name, lon_name = _guess_lat_lon_names(da)
    time_name = _guess_time_name(da, lat_name=lat_name, lon_name=lon_name)

    lats = da[lat_name].values.astype("float64")
    lons0 = da[lon_name].values.astype("float64")
    lons180 = _lon_to_180(lons0)
    times = pd.to_datetime(da[time_name].values)

    n_time = times.shape[0]
    n_lat = lats.shape[0]
    n_lon = lons0.shape[0]

    # Indices: time uniform, lon uniform, lat area-weighted
    if time_sampling == "month":
        time_idx = _sample_time_indices_month_stratified(rng, times, n)
    elif time_sampling == "doy":
        time_idx = _sample_time_indices_doy_stratified(rng, times, n)
    else:
        time_idx = rng.integers(0, n_time, size=n, dtype=np.int32)
    lon_idx = rng.integers(0, n_lon, size=n, dtype=np.int32)
    if space_sampling == "latbands":
        lat_idx, lon_idx = _sample_lat_lon_indices_latbands(
            rng,
            lat_vals=lats,
            n_lon=n_lon,
            n=n,
            n_bands=n_lat_bands,
        )
    else:
        lat_idx = _sample_lat_indices_area_weighted(rng, lats, n)
    lon_idx = rng.integers(0, n_lon, size=n, endpoint=False)

    # Efficient-ish IO: group by time, read each day's 2D slice once
    tvals = np.empty(n, dtype=np.float32)

    order = np.argsort(time_idx)
    time_sorted = time_idx[order]
    lat_sorted = lat_idx[order]
    lon_sorted = lon_idx[order]

    unique_t, start_pos = np.unique(time_sorted, return_index=True)
    # compute stop positions
    stop_pos = np.append(start_pos[1:], time_sorted.size)

    for t_i, s0, s1 in zip(unique_t, start_pos, stop_pos):
        if (t_i%100 == 0):
            print("[%s] %d->%d" % (era_name, s0, s1))
        slab = da.isel({time_name: int(t_i)}).values  # (lat, lon)
        # gather in this chunk
        li = lat_sorted[s0:s1]
        lo = lon_sorted[s0:s1]
        tvals_sorted = slab[li, lo].astype(np.float32, copy=False)
        tvals[order[s0:s1]] = tvals_sorted

    df = pd.DataFrame(
        {
            "era": era_name,
            "era_id": np.int8(era_id),
            "time": times[time_idx].astype("datetime64[ns]"),
            "cell_lat": lats[lat_idx].astype(np.float32),
            "cell_lon_0_360": lons0[lon_idx].astype(np.float32),
            "lat": lats[lat_idx].astype(np.float32),
            "lon": lons180[lon_idx].astype(np.float32),
            "t_c": tvals,
        }
    )

    return df


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid-deg", type=float, default=1.0)
    ap.add_argument("--n-samples", type=int, default=50_000, help="Samples per era (total rows = 2 * n_samples)")
    ap.add_argument("--experiment-id", type=int, default=1)
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--shuffle-first", type=int, default=200, help="Only shuffle first K rows in playback order (for varying early detail)")
    ap.add_argument("--visualise", action="store_true", help="Write a convergence plot PNG after sampling.")
    ap.add_argument("--skip-write", action="store_true", help="Skip writing Parquet samples (still writes meta + optional plots)")
    ap.add_argument("--viz-out", type=Path, default=None, help="Optional output PNG path.")
    ap.add_argument("--in-dir", type=Path, default=Path("data/mc"))
    ap.add_argument("--out-dir", type=Path, default=Path("data/mc/experiments"))
    ap.add_argument("--time-sampling",
        choices=["random", "month", "doy"],
        default="month",
        help="How to sample time indices. "
            "'random' = uniform over days, "
            "'month' = stratified by month proportional to available days, "
            "'doy' = stratified by day-of-year proportional to available days.",
    )
    ap.add_argument(
        "--space-sampling",
        choices=["area", "latbands"],
        default="area",
        help="How to sample space. 'area' = your current cos(lat) area-weighted sampling. "
            "'latbands' = equal-area latitude-band stratification (lower variance).",
    )
    ap.add_argument(
        "--n-lat-bands",
        type=int,
        default=18,
        help="Number of equal-area latitude bands for --space-sampling latbands.",
    )
    args = ap.parse_args()

    in_dir = args.in_dir
    out_dir = args.out_dir
    _ensure_dir(out_dir)

    n_each = int(args.n_samples)
    rng = np.random.default_rng(args.seed)

    era_past = "1979-1988"
    era_recent = "2016-2025"

    print(f"[open] era={era_past} grid={args.grid_deg}")
    ds_past = _open_era_dataset(in_dir, era_label=era_past, grid_deg=args.grid_deg)

    print(f"[open] era={era_recent} grid={args.grid_deg}")
    ds_recent = _open_era_dataset(in_dir, era_label=era_recent, grid_deg=args.grid_deg)

    print(f"[sample] {n_each} past + {n_each} recent (total={2*n_each}, seed={args.seed}, sampling={args.time_sampling})")
    if args.space_sampling == "latbands":
        print(f"[sampling] time={args.time_sampling} space={args.space_sampling} n_lat_bands={args.n_lat_bands}")
    else:
        print(f"[sampling] time={args.time_sampling} space={args.space_sampling}")
    df_past = _sample_from_ds(ds=ds_past, era_name="past", era_id=0, n=n_each, rng=rng, time_sampling=args.time_sampling, space_sampling=args.space_sampling, n_lat_bands=args.n_lat_bands)
    df_recent = _sample_from_ds(ds=ds_recent, era_name="recent", era_id=1, n=n_each, rng=rng, time_sampling=args.time_sampling, space_sampling=args.space_sampling, n_lat_bands=args.n_lat_bands)

    # Running means per era (in the per-era draw order; order doesn't matter for convergence)
    past_vals = df_past["t_c"].to_numpy(dtype=np.float64)
    recent_vals = df_recent["t_c"].to_numpy(dtype=np.float64)

    sd_p = past_vals.std(ddof=1)
    sd_r = recent_vals.std(ddof=1)
    n = len(past_vals)

    se_delta = (sd_p**2 / n + sd_r**2 / n) ** 0.5
    ci95 = 1.96 * se_delta

    # Running means (can be huge; avoid OOM)
    n = len(past_vals)

    # If we're not visualising, we only need final means
    if not args.visualise and args.skip_write:
        past_mean = float(past_vals.mean(dtype=np.float64))
        recent_mean = float(recent_vals.mean(dtype=np.float64))
        past_running = np.array([past_mean], dtype=np.float64)
        recent_running = np.array([recent_mean], dtype=np.float64)
        delta_running = np.array([recent_mean - past_mean], dtype=np.float64)
    else:
        past_running = np.cumsum(past_vals, dtype=np.float64) / np.arange(1, n + 1, dtype=np.float64)
        recent_running = np.cumsum(recent_vals, dtype=np.float64) / np.arange(1, n + 1, dtype=np.float64)
        delta_running = recent_running - past_running

    print(f"sd_past={sd_p:.2f}°C sd_recent={sd_r:.2f}°C")
    print(f"delta={delta_running[-1]:.6f}°C  SE={se_delta:.6f}°C  95%±{ci95:.6f}°C")

    if args.visualise:
        x = np.arange(1, len(past_running) + 1)

        # Resolve output paths
        out_means = args.viz_out
        if out_means is None:
            out_means = out_dir / f"experiment_{args.experiment_id:02d}_convergence_means.png"
        else:
            out_means = Path(out_means)
            if out_means.suffix.lower() == ".png":
                pass
            else:
                # treat as directory-like prefix
                out_means = out_means / f"experiment_{args.experiment_id:02d}_convergence_means.png"

        out_delta = out_means.with_name(out_means.stem.replace("_means", "") + "_delta.png")

        # Plot 1: past + recent running means
        fig1 = plt.figure(figsize=(8, 4.5))
        plt.plot(x, past_running, label="Past (area-weighted)")
        plt.plot(x, recent_running, label="Recent (area-weighted)")
        plt.xlabel("Samples per era")
        plt.ylabel("Temperature (°C)")
        plt.title(f"Monte Carlo convergence (means) — exp {args.experiment_id}, grid {args.grid_deg}°")
        plt.legend()
        fig1.tight_layout()
        fig1.savefig(out_means, dpi=150)
        plt.close(fig1)
        print(f"[viz] {out_means}")

        # Plot 2: delta only (readable scale)
        fig2 = plt.figure(figsize=(8, 4.5))
        plt.plot(x, delta_running, label="Δ (recent − past)")
        plt.axhline(float(delta_running[-1]), linestyle="--", linewidth=1.0, label=f"final ≈ {delta_running[-1]:.2f}°C")
        plt.xlabel("Samples per era")
        plt.ylabel("Δ Temperature (°C)")
        plt.title(f"Monte Carlo convergence (delta) — exp {args.experiment_id}, grid {args.grid_deg}°")
        plt.legend()
        fig2.tight_layout()
        fig2.savefig(out_delta, dpi=150)
        plt.close(fig2)
        print(f"[viz] {out_delta}")
 
    if not args.skip_write:
        # Interleave (past/recent alternating) so both eras appear early in the animation
        df_past["__k"] = np.arange(len(df_past), dtype=np.int32)
        df_recent["__k"] = np.arange(len(df_recent), dtype=np.int32)

        merged = []
        for i in range(max(len(df_past), len(df_recent))):
            if i < len(df_past):
                merged.append(df_past.iloc[i])
            if i < len(df_recent):
                merged.append(df_recent.iloc[i])

        df = pd.DataFrame(merged).reset_index(drop=True)
        df.drop(columns=["__k"], inplace=True, errors="ignore")

        # Playback order: shuffle only first K
        K = int(args.shuffle_first)
        perm = np.arange(len(df), dtype=np.int32)
        if K > 1:
            perm_first = perm[:K].copy()
            rng.shuffle(perm_first)
            perm[:K] = perm_first

        df = df.iloc[perm].reset_index(drop=True)
        df.insert(0, "seq", np.arange(len(df), dtype=np.int32))
        df["detail"] = df["seq"] < K

        out_parquet = out_dir / f"experiment_{args.experiment_id:02d}_samples.parquet"

        print(f"[write] {out_parquet} ({len(df)} rows)")
        df.to_parquet(out_parquet, index=False)

        n_samples_total = len(df)
    else:
        n_samples_total = 2*n_each

    meta_past = in_dir / f"era5_daily_t2m_{era_past}_grid{args.grid_deg}.meta.json"
    meta_recent = in_dir / f"era5_daily_t2m_{era_recent}_grid{args.grid_deg}.meta.json"

    meta = {
        "experiment_id": args.experiment_id,
        "seed": args.seed,
        "shuffle_first": int(args.shuffle_first),
        "n_samples_total": int(n_samples_total),
        "grid_deg": float(args.grid_deg),
        "eras": [
            asdict(EraSpec("past", 1979, 1988, str(meta_past if meta_past.exists() else (in_dir / f"era5_daily_t2m_{era_past}_grid{args.grid_deg}.nc")))),
            asdict(EraSpec("recent", 2016, 2025, str(meta_recent if meta_recent.exists() else (in_dir / f"era5_daily_t2m_{era_recent}_grid{args.grid_deg}.nc")))),
        ],
        "variable": "2m_temperature",
        "statistic": "daily_mean",
        "units": "degC",
        "time_sampling" : args.time_sampling,
        "running_mean_final": {
            "past_c": float(past_running[-1]),
            "recent_c": float(recent_running[-1]),
            "delta_c": float(delta_running[-1]),
        },
    }
    out_meta = out_dir / f"experiment_{args.experiment_id:02d}_samples.meta.json"
    out_meta.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"[meta]  {out_meta}")


if __name__ == "__main__":
    main()
