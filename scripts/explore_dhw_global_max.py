"""
Exploration: global-max or widespread-fraction DHW approach for coral reef risk days.

Two modes:
  - Max mode (default): a day's risk level is determined by the single highest
    DHW value across all coral reef cells.
  - Fraction mode (--fraction X): a day is classified as severe/moderate if at
    least X% of valid coral reef cells exceed the corresponding threshold.

Results are cached in /tmp so re-runs with different --fraction values are instant.

Usage:
    python scripts/explore_dhw_global_max.py
    python scripts/explore_dhw_global_max.py --fraction 10
    python scripts/explore_dhw_global_max.py --fraction 10 --no-cache
"""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import xarray as xr

CACHE_ROOT = Path("/Volumes/SDCard/Climate/cache/erddap/crw_dhw_daily")
MAX_CACHE = Path("/tmp/dhw_global_max_cache.json")
FRAC_CACHE = Path("/tmp/dhw_global_fraction_cache.json")
MODERATE_THRESHOLD = 4.0
SEVERE_THRESHOLD = 8.0
YEARS = list(range(1985, 2026))

COLOR_NO_RISK = "#ccccff"
COLOR_MODERATE = "#fdd835"
COLOR_SEVERE = "#ff0000"


def tile_dirs():
    return sorted(CACHE_ROOT.iterdir())


def nc_pattern(year: int) -> str:
    if year == 1985:
        return "*_1985-03-25_1985-12-31.nc"
    return f"*_{year}-01-01_{year}-12-31.nc"


# --- Max mode ------------------------------------------------------------------


def compute_max_year(year: int) -> np.ndarray | None:
    """Daily global max DHW across all tiles."""
    daily_max = None
    for tile_dir in tile_dirs():
        files = list(tile_dir.glob(nc_pattern(year)))
        if not files:
            continue
        ds = xr.open_dataset(files[0], engine="netcdf4")
        dhw = ds["degree_heating_week"].values
        tile_max = np.nanmax(dhw.reshape(dhw.shape[0], -1), axis=1)
        daily_max = tile_max if daily_max is None else np.fmax(daily_max, tile_max)
        ds.close()
    return daily_max


def classify_max(daily_max: np.ndarray) -> tuple[int, int, int]:
    valid = daily_max[~np.isnan(daily_max)]
    severe = int(np.sum(valid >= SEVERE_THRESHOLD))
    moderate = int(np.sum((valid >= MODERATE_THRESHOLD) & (valid < SEVERE_THRESHOLD)))
    no_risk = len(valid) - moderate - severe
    return no_risk, moderate, severe


def load_or_compute_max(force: bool) -> dict[int, tuple[int, int, int]]:
    if not force and MAX_CACHE.exists():
        print(f"Loading cached max results from {MAX_CACHE}")
        raw = json.loads(MAX_CACHE.read_text())
        return {int(y): tuple(v) for y, v in raw.items()}

    results = {}
    for i, year in enumerate(YEARS):
        print(f"  [{i+1:2d}/{len(YEARS)}] {year}...", end=" ", flush=True)
        daily_max = compute_max_year(year)
        if daily_max is None:
            print("no data")
            continue
        counts = classify_max(daily_max)
        results[year] = counts
        print(f"no-risk={counts[0]}  moderate={counts[1]}  severe={counts[2]}")

    MAX_CACHE.write_text(json.dumps({str(y): list(v) for y, v in results.items()}))
    return results


# --- Fraction mode -------------------------------------------------------------


def compute_fraction_year(
    year: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """
    For each day: count of cells in severe risk, moderate risk, and total valid.
    Returned as three int arrays of shape (n_days,).
    """
    n_severe = n_moderate = n_valid = None
    for tile_dir in tile_dirs():
        files = list(tile_dir.glob(nc_pattern(year)))
        if not files:
            continue
        ds = xr.open_dataset(files[0], engine="netcdf4")
        dhw = ds["degree_heating_week"].values  # (time, lat, lon)
        flat = dhw.reshape(dhw.shape[0], -1)  # (time, cells)
        valid_mask = ~np.isnan(flat)

        tile_valid = valid_mask.sum(axis=1)
        tile_severe = (flat >= SEVERE_THRESHOLD).sum(axis=1)
        tile_moderate = (flat >= MODERATE_THRESHOLD).sum(axis=1)  # includes severe

        if n_valid is None:
            n_severe, n_moderate, n_valid = tile_severe, tile_moderate, tile_valid
        else:
            n_severe = n_severe + tile_severe
            n_moderate = n_moderate + tile_moderate
            n_valid = n_valid + tile_valid
        ds.close()

    if n_valid is None:
        return None
    return n_severe, n_moderate, n_valid


def classify_fraction(
    n_severe: np.ndarray,
    n_moderate: np.ndarray,
    n_valid: np.ndarray,
    threshold_pct: float,
) -> tuple[int, int, int]:
    thresh = threshold_pct / 100.0
    has_data = n_valid > 0
    frac_severe = np.where(has_data, n_severe / np.maximum(n_valid, 1), np.nan)
    frac_moderate = np.where(has_data, n_moderate / np.maximum(n_valid, 1), np.nan)

    severe_days = has_data & (frac_severe >= thresh)
    moderate_days = has_data & (~severe_days) & (frac_moderate >= thresh)
    no_risk_days = has_data & (~severe_days) & (~moderate_days)

    return int(no_risk_days.sum()), int(moderate_days.sum()), int(severe_days.sum())


def load_or_compute_fraction(force: bool) -> dict[int, dict]:
    """Load/compute raw per-day counts (threshold-independent)."""
    if not force and FRAC_CACHE.exists():
        print(f"Loading cached fraction counts from {FRAC_CACHE}")
        raw = json.loads(FRAC_CACHE.read_text())
        return {int(y): {k: np.array(v) for k, v in d.items()} for y, d in raw.items()}

    results = {}
    for i, year in enumerate(YEARS):
        print(f"  [{i+1:2d}/{len(YEARS)}] {year}...", end=" ", flush=True)
        out = compute_fraction_year(year)
        if out is None:
            print("no data")
            continue
        n_severe, n_moderate, n_valid = out
        results[year] = {"severe": n_severe, "moderate": n_moderate, "valid": n_valid}
        print(f"total valid cells/day: {int(n_valid.mean()):,}")

    FRAC_CACHE.write_text(
        json.dumps(
            {str(y): {k: v.tolist() for k, v in d.items()} for y, d in results.items()}
        )
    )
    return results


# --- Plotting ------------------------------------------------------------------


def plot(results: dict[int, tuple[int, int, int]], title: str) -> None:
    years = sorted(results)
    no_risk = np.array([results[y][0] for y in years], dtype=float)
    moderate = np.array([results[y][1] for y in years], dtype=float)
    severe = np.array([results[y][2] for y in years], dtype=float)

    fig, ax = plt.subplots(figsize=(14, 6))
    x = np.arange(len(years))

    ax.bar(x, no_risk, 0.8, label="No risk (DHW < 4)", color=COLOR_NO_RISK, zorder=2)
    ax.bar(
        x,
        moderate,
        0.8,
        bottom=no_risk,
        label="Moderate risk (4 ≤ DHW < 8)",
        color=COLOR_MODERATE,
        zorder=2,
    )
    ax.bar(
        x,
        severe,
        0.8,
        bottom=no_risk + moderate,
        label="Severe risk (DHW ≥ 8)",
        color=COLOR_SEVERE,
        zorder=2,
    )

    ax.set_xticks(x)
    ax.set_xticklabels([str(y) for y in years], rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("Days per year")
    ax.set_ylim(0, 400)
    ax.set_title(title)
    ax.legend(loc="upper left")
    ax.grid(axis="y", alpha=0.3, zorder=1)
    fig.tight_layout()
    plt.show()


# --- Entry point ---------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fraction",
        type=float,
        default=None,
        metavar="PCT",
        help="Fraction mode: classify a day as severe/moderate if at least PCT%% "
        "of coral reef cells exceed the threshold (e.g. --fraction 10). "
        "Omit to use max-across-all-cells mode.",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Ignore cached results and recompute from raw files",
    )
    args = parser.parse_args()

    print("DHW exploration — 1985 to 2025")

    if args.fraction is None:
        print("Mode: global maximum across all coral reef cells")
        raw = load_or_compute_max(force=args.no_cache)
        title = "Coral reef DHW risk days — global max (1985–2025)"
    else:
        pct = args.fraction
        print(f"Mode: fraction ≥ {pct}% of coral reef cells exceed threshold")
        raw_counts = load_or_compute_fraction(force=args.no_cache)
        raw = {
            y: classify_fraction(d["severe"], d["moderate"], d["valid"], pct)
            for y, d in raw_counts.items()
        }
        title = (
            f"Coral reef DHW risk days — ≥{pct}% of cells exceed threshold (1985–2025)"
        )

    plot(raw, title)


if __name__ == "__main__":
    main()
