#!/usr/bin/env python3
"""Validate that precomputed ranking files exist for all metrics that declare them.

Checks that for every metric with a 'rankings' field in metrics.json, the
corresponding ranking JSON files exist under:
  <series_root>/<grid_id>/<metric_id>/rankings/<aggregation>.json
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from climate.registry.metrics import (
    DEFAULT_DATASETS_PATH,
    DEFAULT_METRICS_PATH,
    DEFAULT_SCHEMA_PATH,
    load_metrics,
)


def check_rankings(
    *,
    metrics_path: Path,
    series_root: Path,
) -> list[str]:
    """Return a list of error strings; empty means all good."""
    manifest = load_metrics(path=metrics_path, validate=True)
    errors: list[str] = []

    for metric_id, spec in manifest.items():
        if metric_id == "version":
            continue
        aggregations: list[str] = spec.get("rankings", [])
        if not aggregations:
            continue
        grid_id = spec.get("grid_id", "")
        for aggregation in aggregations:
            path = (
                series_root / grid_id / metric_id / "rankings" / f"{aggregation}.json"
            )
            if not path.exists():
                errors.append(
                    f"Missing ranking file: {path.relative_to(series_root.parent)}"
                )

    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--series-root",
        type=Path,
        default=REPO_ROOT / "data" / "releases" / "dev" / "series",
        help="Path to the series root (default: data/releases/dev/series)",
    )
    ap.add_argument(
        "--metrics",
        type=Path,
        default=DEFAULT_METRICS_PATH,
        help=f"Path to metrics.json (default: {DEFAULT_METRICS_PATH})",
    )
    args = ap.parse_args()

    errors = check_rankings(
        metrics_path=args.metrics,
        series_root=args.series_root,
    )

    if errors:
        for err in errors:
            print(f"  ERROR: {err}", file=sys.stderr)
        print(f"[rankings] {len(errors)} error(s) found", file=sys.stderr)
        return 1

    print("[rankings] all ranking files present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
