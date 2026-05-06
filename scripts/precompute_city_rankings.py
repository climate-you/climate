#!/usr/bin/env python3
"""Precompute city rankings for metrics that declare a 'rankings' field.

For each (metric_id, aggregation) pair declared in metrics.json, this script
scans all cities, computes the aggregation value, and writes a sorted JSON file
to data/releases/<release>/series/<grid_id>/<metric_id>/rankings/<aggregation>.json.

Usage:
    python scripts/precompute_city_rankings.py --release dev
    python scripts/precompute_city_rankings.py --release dev --metrics t2m_yearly_mean_c
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from climate.registry.metrics import load_metrics
from climate_api.store.tile_data_store import TileDataStore
from climate_api.store.location_index import LocationIndex


_DEFAULT_INDEX_CSV = REPO_ROOT / "data" / "locations" / "locations.index.csv"
_DEFAULT_RELEASES_ROOT = REPO_ROOT / "data" / "releases"


def _compute_aggregation(
    values: list[float],
    years: list[int | str],
    aggregation: str,
) -> float | None:
    if not values:
        return None
    arr = np.array(values, dtype=np.float64)
    if aggregation == "mean":
        return float(np.mean(arr))
    if aggregation == "max":
        return float(np.max(arr))
    if aggregation == "min":
        return float(np.min(arr))
    if aggregation == "trend_slope":
        if len(arr) < 2:
            return None
        int_years = [int(y) for y in years]
        slope = float(np.polyfit(int_years, arr, 1)[0])
        return slope * 10  # units per decade
    raise ValueError(f"Unsupported aggregation: {aggregation}")


def precompute_rankings(
    *,
    release: str,
    releases_root: Path,
    metrics_path: Path,
    index_csv: Path,
    metric_filter: list[str] | None,
) -> int:
    releases_root = Path(releases_root)
    series_root = releases_root / release / "series"
    if not series_root.is_dir():
        print(f"ERROR: series root not found: {series_root}", file=sys.stderr)
        return 1

    manifest = load_metrics(path=metrics_path, validate=True)
    location_index = LocationIndex(index_csv)

    # Collect all cities once (sorted by population desc, minimum 1000)
    all_cities = location_index.iter_all(min_population=1000)
    print(f"[rankings] {len(all_cities)} candidate cities")

    tile_store = TileDataStore.discover(
        series_root,
        metrics_path=metrics_path,
    )

    generated = 0
    for metric_id, spec in manifest.items():
        if metric_id == "version":
            continue
        aggregations: list[str] = spec.get("rankings", [])
        if not aggregations:
            continue
        if metric_filter and metric_id not in metric_filter:
            continue
        if metric_id not in tile_store.metrics:
            print(f"[rankings] skip {metric_id}: tiles not found in {series_root}")
            continue

        grid_id = spec.get("grid_id", "")
        rankings_dir = series_root / grid_id / metric_id / "rankings"
        rankings_dir.mkdir(parents=True, exist_ok=True)

        for aggregation in aggregations:
            out_path = rankings_dir / f"{aggregation}.json"
            print(
                f"[rankings] computing {metric_id}/{aggregation} ...",
                end="",
                flush=True,
            )
            t0 = time.monotonic()

            scored: list[tuple[float, dict]] = []
            seen_cells: set[tuple[int, int]] = set()

            for city in all_cities:
                cell_key = (round(city.lat * 4), round(city.lon * 4))
                if cell_key in seen_cells:
                    continue
                seen_cells.add(cell_key)

                vec = tile_store.try_get_metric_vector(metric_id, city.lat, city.lon)
                if vec is None:
                    continue
                axis = tile_store.axis(metric_id)
                if axis is None:
                    continue

                values = [float(v) for v in vec]
                years = list(axis)
                score = _compute_aggregation(values, years, aggregation)
                if score is None:
                    continue

                scored.append(
                    (
                        score,
                        {
                            "name": city.label,
                            "country": city.country_code,
                            "lat": city.lat,
                            "lon": city.lon,
                            "population": city.population,
                            "capital": getattr(city, "capital", False),
                            "value": round(score, 4),
                        },
                    )
                )

            scored.sort(key=lambda t: t[0], reverse=True)
            cities_sorted = [entry for _, entry in scored]

            out_path.write_text(
                json.dumps(
                    {
                        "metric_id": metric_id,
                        "aggregation": aggregation,
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                        "cities": cities_sorted,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            elapsed = time.monotonic() - t0
            print(f" {len(cities_sorted)} cities, {elapsed:.1f}s -> {out_path}")
            generated += 1

    print(f"[rankings] done: {generated} ranking file(s) generated")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--release", default="dev", help="Release id (default: dev)")
    ap.add_argument(
        "--releases-root",
        type=Path,
        default=_DEFAULT_RELEASES_ROOT,
        help=f"Releases root (default: {_DEFAULT_RELEASES_ROOT})",
    )
    ap.add_argument(
        "--metrics-path",
        type=Path,
        default=REPO_ROOT / "registry" / "metrics.json",
        help="Path to metrics.json",
    )
    ap.add_argument(
        "--index-csv",
        type=Path,
        default=_DEFAULT_INDEX_CSV,
        help=f"Locations index CSV (default: {_DEFAULT_INDEX_CSV})",
    )
    ap.add_argument(
        "--metrics",
        nargs="+",
        default=None,
        metavar="METRIC_ID",
        help="Limit to specific metric_id(s); default is all metrics with a rankings field",
    )
    args = ap.parse_args()

    return precompute_rankings(
        release=args.release,
        releases_root=args.releases_root,
        metrics_path=args.metrics_path,
        index_csv=args.index_csv,
        metric_filter=args.metrics,
    )


if __name__ == "__main__":
    raise SystemExit(main())
