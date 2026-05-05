"""
Precompute global DHW risk-day counts for the coral reef panel.

For each threshold, a day is classified as severe/moderate if at least X% of valid
coral reef cells globally exceed the corresponding DHW threshold. Days are mutually
exclusive: severe > moderate > no-risk. "moderate" in the output is the non-overlapping
band (not severe but at-least-moderate), so severe + moderate = total risk days.

All thresholds are computed in a single pass over the data.  Each threshold produces
three output files (one per risk level):
  data/releases/<release>/series/global_0p05/<metric_id>/aggregates/fraction_<X>pct.json

These are auto-discovered by TileDataStore._load_aggregates() and become accessible as
tile_store.aggregates[(<metric_id>, "fraction_<X>pct")].

Usage:
    python scripts/precompute_dhw_global_risk.py --thresholds 1 5 10
    python scripts/precompute_dhw_global_risk.py --thresholds 1 5 10 --release dev
    python scripts/precompute_dhw_global_risk.py --thresholds 1 5 10 \\
        --cache-dir /Volumes/SDCard/Climate/cache
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import xarray as xr

REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CACHE_DIR = REPO_ROOT / "data" / "cache"
_DATASET_KEY = "crw_dhw_daily"

GRID_ID = "global_0p05"
METRIC_IDS = [
    "dhw_no_risk_days_per_year",
    "dhw_moderate_risk_days_per_year",
    "dhw_severe_risk_days_per_year",
]
YEARS = list(range(1985, 2026))
MODERATE_THRESHOLD = 4.0
SEVERE_THRESHOLD = 8.0


def _dhw_cache_root(cache_dir: Path) -> Path:
    return cache_dir / "erddap" / _DATASET_KEY


def _threshold_label(t: float) -> str:
    """Format a threshold as a clean label, e.g. 1.0 → 'fraction_1pct'."""
    v = int(t) if t == int(t) else t
    return f"fraction_{v}pct"


def tile_dirs(cache_root: Path) -> list[Path]:
    return sorted(cache_root.iterdir())


def nc_pattern(year: int) -> str:
    if year == 1985:
        return "*_1985-03-25_1985-12-31.nc"
    return f"*_{year}-01-01_{year}-12-31.nc"


# ---------------------------------------------------------------------------
# Computation
# ---------------------------------------------------------------------------

def compute_counts_year(
    year: int, cache_root: Path
) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """
    Return (n_severe, n_moderate_cumulative, n_valid) per day.

    n_severe              = cells with DHW >= 8
    n_moderate_cumulative = cells with DHW >= 4  (includes severe cells)
    n_valid               = cells with non-NaN DHW
    """
    n_severe = n_moderate = n_valid = None
    for tile_dir in tile_dirs(cache_root):
        files = list(tile_dir.glob(nc_pattern(year)))
        if not files:
            continue
        ds = xr.open_dataset(files[0], engine="netcdf4")
        dhw = ds["degree_heating_week"].values
        flat = dhw.reshape(dhw.shape[0], -1)            # (time, cells)

        tile_valid    = (~np.isnan(flat)).sum(axis=1)
        tile_severe   = (flat >= SEVERE_THRESHOLD).sum(axis=1)
        tile_moderate = (flat >= MODERATE_THRESHOLD).sum(axis=1)  # includes severe

        if n_valid is None:
            n_severe, n_moderate, n_valid = tile_severe, tile_moderate, tile_valid
        else:
            n_severe   = n_severe   + tile_severe
            n_moderate = n_moderate + tile_moderate
            n_valid    = n_valid    + tile_valid
        ds.close()

    return (n_severe, n_moderate, n_valid) if n_valid is not None else None


def classify(
    n_severe: np.ndarray,
    n_moderate: np.ndarray,
    n_valid: np.ndarray,
    threshold_pct: float,
) -> tuple[int, int, int]:
    """Return (no_risk_days, moderate_days, severe_days) for the given threshold."""
    thresh = threshold_pct / 100.0
    has_data = n_valid > 0
    safe_valid = np.maximum(n_valid, 1)
    frac_severe   = np.where(has_data, n_severe   / safe_valid, np.nan)
    frac_moderate = np.where(has_data, n_moderate / safe_valid, np.nan)

    severe_days   = has_data & (frac_severe >= thresh)
    moderate_days = has_data & ~severe_days & (frac_moderate >= thresh)
    no_risk_days  = has_data & ~severe_days & ~moderate_days

    return int(no_risk_days.sum()), int(moderate_days.sum()), int(severe_days.sum())


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def write_aggregate_json(
    path: Path,
    metric_id: str,
    aggregation: str,
    time_axis: list[int],
    values: list[int | None],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "metric_id": metric_id,
        "aggregation": aggregation,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "time_axis": time_axis,
        "regions": {
            "globe": {
                "name": "Global",
                "type": "globe",
                "values": values,
            }
        },
    }
    path.write_text(json.dumps(payload, indent=2))
    print(f"  wrote {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--thresholds", nargs="+", type=float, required=True, metavar="PCT",
        help="One or more fraction thresholds in %% (e.g. 1 5 10). "
             "All thresholds are computed in a single pass.",
    )
    ap.add_argument("--release", default="dev",
                    help="Release id (default: dev)")
    ap.add_argument("--releases-root", default=None,
                    help="Path to releases root (default: <repo>/data/releases)")
    ap.add_argument("--cache-dir", type=Path, default=_DEFAULT_CACHE_DIR,
                    help="Cache root directory (default: <repo>/data/cache)")
    args = ap.parse_args()

    releases_root = (
        Path(args.releases_root) if args.releases_root
        else REPO_ROOT / "data" / "releases"
    )
    series_root = releases_root / args.release / "series"
    if not series_root.is_dir():
        print(f"ERROR: series root not found: {series_root}", file=sys.stderr)
        sys.exit(1)

    cache_root = _dhw_cache_root(args.cache_dir)
    if not cache_root.is_dir():
        print(f"ERROR: DHW cache not found: {cache_root}", file=sys.stderr)
        sys.exit(1)

    thresholds = args.thresholds
    labels = [_threshold_label(t) for t in thresholds]
    print(f"Thresholds: {', '.join(f'{t}% ({l})' for t, l in zip(thresholds, labels))}")
    print(f"Processing {len(YEARS)} years ({YEARS[0]}–{YEARS[-1]})…")

    # Accumulate results per threshold: {label: (no_risk_list, moderate_list, severe_list)}
    results: dict[str, tuple[list, list, list]] = {l: ([], [], []) for l in labels}

    for i, year in enumerate(YEARS):
        print(f"  [{i+1:2d}/{len(YEARS)}] {year}…", end=" ", flush=True)
        counts = compute_counts_year(year, cache_root)
        if counts is None:
            print("no data")
            for nr, mo, sv in results.values():
                nr.append(None); mo.append(None); sv.append(None)
            continue

        parts = []
        for t, label in zip(thresholds, labels):
            no_risk, moderate, severe = classify(*counts, t)
            results[label][0].append(no_risk)
            results[label][1].append(moderate)
            results[label][2].append(severe)
            parts.append(f"{label}: no-risk={no_risk} mod={moderate} sev={severe}")
        print("  |  ".join(parts))

    print("\nWriting output files…")
    out_path = series_root / GRID_ID
    for label, (no_risk_vals, moderate_vals, severe_vals) in results.items():
        write_aggregate_json(
            out_path / "dhw_no_risk_days_per_year" / "aggregates" / f"{label}.json",
            "dhw_no_risk_days_per_year", label, YEARS, no_risk_vals,
        )
        write_aggregate_json(
            out_path / "dhw_moderate_risk_days_per_year" / "aggregates" / f"{label}.json",
            "dhw_moderate_risk_days_per_year", label, YEARS, moderate_vals,
        )
        write_aggregate_json(
            out_path / "dhw_severe_risk_days_per_year" / "aggregates" / f"{label}.json",
            "dhw_severe_risk_days_per_year", label, YEARS, severe_vals,
        )
    print("Done.")


if __name__ == "__main__":
    main()
