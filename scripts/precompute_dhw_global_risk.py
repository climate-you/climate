#!/usr/bin/env python3
"""
Precompute DHW risk-day counts for the coral reef panel, globally and per sea.

For each threshold, a day is classified as severe/moderate if at least X% of valid
coral reef cells exceed the corresponding DHW threshold. Days are mutually
exclusive: severe > moderate > no-risk. "moderate" in the output is the non-overlapping
band (not severe but at-least-moderate), so severe + moderate = total risk days.

The same classification is made for each sea, over the reef cells inside it, so a
sea's panel reads like the globe's: "days when at least 10% of the Coral
Sea's reefs were under heat stress". An average of per-cell day counts would be
the simpler aggregate, but it blurs a few badly stressed reefs into many calm
ones, which is why the globe does not use it either. Seas are taken from the
ocean mask plus the overlay mask, so the Great Barrier Reef is a sea of its own
while its cells still count towards the Coral Sea. A sea needs at least
--min-region-cells reef cells: below that, "10% of its reefs" is a handful of
cells.

A sea's reef cells are those of the reef-domain mask (reef polygons with DHW
data; see docs/runbooks/reef-mask.md), the cells the map layer and the per-cell
tiles use. The global series is different: it counts every cell with data in
the downloaded tiles, open water between reefs included. It is left as it was
published.

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
sys.path.insert(0, str(REPO_ROOT))

from climate.geo.regions import ocean_region_id  # noqa: E402

_DEFAULT_CACHE_DIR = REPO_ROOT / "data" / "cache"
_LOCATIONS = REPO_ROOT / "data" / "locations"
_DEFAULT_REEF_DOMAIN_MASK = (
    REPO_ROOT / "data" / "masks" / "crw_dhw_daily_global_0p05_mask.npz"
)
_DEFAULT_MIN_REGION_CELLS = 100
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


Counts = tuple[np.ndarray, np.ndarray, np.ndarray]


def _sample(mask, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """A 0.05° mask's values at a tile's cell centres, flattened in (lat, lon) order."""
    deg = float(mask["deg"])
    data = mask["data"]
    rows = np.floor((float(mask["lat_max"]) - lat) / deg).astype(int)
    cols = np.floor((lon - float(mask["lon_min"])) / deg).astype(int)
    rows = np.clip(rows, 0, data.shape[0] - 1)
    cols = cols % data.shape[1]
    return data[np.ix_(rows, cols)].ravel()


class SeaIndex:
    """Which sea(s) each reef cell of a daily DHW tile belongs to.

    Only reef-domain cells count; the tiles also hold the open water around the
    reefs. A cell can belong to two seas: its sea in the ocean mask, and an
    overlay sea lying inside it (the Great Barrier Reef inside the Coral Sea).
    """

    def __init__(
        self,
        ocean_mask: Path,
        overlay_mask: Path,
        ocean_names: Path,
        reef_domain_mask: Path,
    ):
        names = json.loads(ocean_names.read_text(encoding="utf-8"))
        self.region_ids = {int(k): ocean_region_id(v) for k, v in names.items() if v}
        self.names = {ocean_region_id(v): v for v in names.values() if v}
        self._masks = [np.load(ocean_mask)]
        if overlay_mask.exists():
            self._masks.append(np.load(overlay_mask))
        self._reef = np.load(reef_domain_mask)
        # Filled on first sight of each tile; the grid never changes.
        self.by_tile: dict[str, list[tuple[str, np.ndarray]]] = {}

    def columns(self, tile: str, lat: np.ndarray, lon: np.ndarray):
        """[(region_id, flat column indices)] for a tile, in (lat, lon) order."""
        if tile not in self.by_tile:
            found: list[tuple[str, np.ndarray]] = []
            reef = _sample(self._reef, lat, lon) > 0
            for m in self._masks:
                ids = np.where(reef, _sample(m, lat, lon), 0)
                for uid in np.unique(ids):
                    region_id = self.region_ids.get(int(uid))
                    if uid > 0 and region_id is not None:
                        found.append((region_id, np.flatnonzero(ids == uid)))
            self.by_tile[tile] = found
        return self.by_tile[tile]


def compute_counts_year(
    year: int,
    cache_root: Path,
    seas: SeaIndex | None = None,
    ever_valid: dict[str, np.ndarray] | None = None,
) -> tuple[Counts, dict[str, Counts]] | None:
    """
    Return the global (n_severe, n_moderate_cumulative, n_valid) per day, and the
    same per sea when `seas` is given.

    n_severe              = cells with DHW >= 8
    n_moderate_cumulative = cells with DHW >= 4  (includes severe cells)
    n_valid               = cells with non-NaN DHW

    `ever_valid`, keyed by tile, collects which cells ever had data, from which
    each sea's reef cell count is taken at the end.
    """
    n_severe = n_moderate = n_valid = None
    per_sea: dict[str, list[np.ndarray]] = {}
    for tile_dir in tile_dirs(cache_root):
        files = list(tile_dir.glob(nc_pattern(year)))
        if not files:
            continue
        ds = xr.open_dataset(files[0], engine="netcdf4")
        dhw = ds["degree_heating_week"].values
        flat = dhw.reshape(dhw.shape[0], -1)  # (time, cells)

        valid = ~np.isnan(flat)
        severe = flat >= SEVERE_THRESHOLD
        moderate = flat >= MODERATE_THRESHOLD  # includes severe
        tile_valid = valid.sum(axis=1)
        tile_severe = severe.sum(axis=1)
        tile_moderate = moderate.sum(axis=1)

        if n_valid is None:
            n_severe, n_moderate, n_valid = tile_severe, tile_moderate, tile_valid
        else:
            n_severe = n_severe + tile_severe
            n_moderate = n_moderate + tile_moderate
            n_valid = n_valid + tile_valid

        if seas is not None:
            tile = tile_dir.name
            lat = ds["latitude"].values.astype(np.float64)
            lon = ds["longitude"].values.astype(np.float64)
            for region_id, cols in seas.columns(tile, lat, lon):
                counts = [
                    severe[:, cols].sum(axis=1),
                    moderate[:, cols].sum(axis=1),
                    valid[:, cols].sum(axis=1),
                ]
                if region_id in per_sea:
                    per_sea[region_id] = [
                        a + b for a, b in zip(per_sea[region_id], counts)
                    ]
                else:
                    per_sea[region_id] = counts
            if ever_valid is not None:
                seen = valid.any(axis=0)
                ever_valid[tile] = (
                    ever_valid[tile] | seen if tile in ever_valid else seen
                )
        ds.close()

    if n_valid is None:
        return None
    return (n_severe, n_moderate, n_valid), {
        region_id: (c[0], c[1], c[2]) for region_id, c in per_sea.items()
    }


def reef_cell_counts(
    seas: SeaIndex, ever_valid: dict[str, np.ndarray]
) -> dict[str, int]:
    """Cells in each sea that had DHW data on at least one day of the record."""
    counts: dict[str, int] = {}
    for tile, seen in ever_valid.items():
        for region_id, cols in seas.by_tile[tile]:
            counts[region_id] = counts.get(region_id, 0) + int(seen[cols].sum())
    return counts


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
    frac_severe = np.where(has_data, n_severe / safe_valid, np.nan)
    frac_moderate = np.where(has_data, n_moderate / safe_valid, np.nan)

    severe_days = has_data & (frac_severe >= thresh)
    moderate_days = has_data & ~severe_days & (frac_moderate >= thresh)
    no_risk_days = has_data & ~severe_days & ~moderate_days

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
    seas: dict[str, dict] | None = None,
) -> None:
    """`seas` maps a region id to its record: name, type, reef_cell_count, values.

    A sea's record carries `reef_cell_count`, not `cell_count`: it counts 0.05°
    reef cells, where every other aggregate counts the 0.25° cells behind the
    sea's mean, which is what the panel shows as the sea's footprint.
    """
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
            },
            **(seas or {}),
        },
    }
    path.write_text(json.dumps(payload, indent=2))
    print(f"  wrote {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--thresholds",
        nargs="+",
        type=float,
        required=True,
        metavar="PCT",
        help="One or more fraction thresholds in %% (e.g. 1 5 10). "
        "All thresholds are computed in a single pass.",
    )
    ap.add_argument("--release", default="dev", help="Release id (default: dev)")
    ap.add_argument(
        "--releases-root",
        default=None,
        help="Path to releases root (default: <repo>/data/releases)",
    )
    ap.add_argument(
        "--cache-dir",
        type=Path,
        default=_DEFAULT_CACHE_DIR,
        help="Cache root directory (default: <repo>/data/cache)",
    )
    ap.add_argument("--ocean-mask", type=Path, default=_LOCATIONS / "ocean_mask.npz")
    ap.add_argument(
        "--ocean-overlay-mask",
        type=Path,
        default=_LOCATIONS / "ocean_overlay_mask.npz",
        help="Seas lying inside another sea (the Great Barrier Reef); skipped if absent",
    )
    ap.add_argument("--ocean-names", type=Path, default=_LOCATIONS / "ocean_names.json")
    ap.add_argument("--reef-domain-mask", type=Path, default=_DEFAULT_REEF_DOMAIN_MASK)
    ap.add_argument(
        "--min-region-cells",
        type=int,
        default=_DEFAULT_MIN_REGION_CELLS,
        help="Fewest reef cells a sea needs to get its own series "
        f"(default: {_DEFAULT_MIN_REGION_CELLS})",
    )
    ap.add_argument(
        "--global-only",
        action="store_true",
        help="Compute the global series only, as before seas were added",
    )
    args = ap.parse_args()

    releases_root = (
        Path(args.releases_root)
        if args.releases_root
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

    seas = (
        None
        if args.global_only
        else SeaIndex(
            args.ocean_mask,
            args.ocean_overlay_mask,
            args.ocean_names,
            args.reef_domain_mask,
        )
    )
    ever_valid: dict[str, np.ndarray] = {}

    # Accumulate results per threshold: {label: (no_risk_list, moderate_list, severe_list)}
    results: dict[str, tuple[list, list, list]] = {l: ([], [], []) for l in labels}
    # Per sea: {label: {region_id: {year_index: (no_risk, moderate, severe)}}}
    sea_results: dict[str, dict[str, dict[int, tuple[int, int, int]]]] = {
        l: {} for l in labels
    }

    for i, year in enumerate(YEARS):
        print(f"  [{i+1:2d}/{len(YEARS)}] {year}…", end=" ", flush=True)
        result = compute_counts_year(year, cache_root, seas, ever_valid)
        counts, sea_counts = result if result is not None else (None, {})
        for region_id, region_counts in sea_counts.items():
            for t, label in zip(thresholds, labels):
                sea_results[label].setdefault(region_id, {})[i] = classify(
                    *region_counts, t
                )
        if counts is None:
            print("no data")
            for nr, mo, sv in results.values():
                nr.append(None)
                mo.append(None)
                sv.append(None)
            continue

        parts = []
        for t, label in zip(thresholds, labels):
            no_risk, moderate, severe = classify(*counts, t)
            results[label][0].append(no_risk)
            results[label][1].append(moderate)
            results[label][2].append(severe)
            parts.append(f"{label}: no-risk={no_risk} mod={moderate} sev={severe}")
        print("  |  ".join(parts))

    reef_cells = reef_cell_counts(seas, ever_valid) if seas is not None else {}
    kept = sorted(
        region_id for region_id, n in reef_cells.items() if n >= args.min_region_cells
    )
    if seas is not None:
        print(
            f"\nSeas with at least {args.min_region_cells} reef cells: {len(kept)} "
            f"of {len(reef_cells)}"
        )

    def sea_records(label: str, level: int) -> dict[str, dict]:
        """One risk level's series for every kept sea (0 no risk, 1 moderate, 2 severe)."""
        records = {}
        for region_id in kept:
            by_year = sea_results[label].get(region_id, {})
            records[region_id] = {
                "name": seas.names[region_id],
                "type": "ocean",
                "reef_cell_count": reef_cells[region_id],
                "values": [
                    by_year[i][level] if i in by_year else None
                    for i in range(len(YEARS))
                ],
            }
        return records

    print("\nWriting output files…")
    out_path = series_root / GRID_ID
    for label, (no_risk_vals, moderate_vals, severe_vals) in results.items():
        for level, (metric_id, values) in enumerate(
            (
                ("dhw_no_risk_days_per_year", no_risk_vals),
                ("dhw_moderate_risk_days_per_year", moderate_vals),
                ("dhw_severe_risk_days_per_year", severe_vals),
            )
        ):
            write_aggregate_json(
                out_path / metric_id / "aggregates" / f"{label}.json",
                metric_id,
                label,
                YEARS,
                values,
                seas=sea_records(label, level),
            )
    print("Done.")


if __name__ == "__main__":
    main()
