#!/usr/bin/env python3
"""Validate that precomputed aggregate files exist for all metrics that declare them.

Checks that for every metric with an 'aggregates' field in metrics.json, the
corresponding aggregate JSON files exist under:
  <series_root>/<grid_id>/<metric_id>/aggregates/<aggregation>.json

Also verifies that each file contains non-empty regions and that the number of
values per region matches the length of the time_axis.
"""
from __future__ import annotations

import argparse
import json
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


def check_aggregates(
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
        aggregations: list[str] = spec.get("aggregates", [])
        if not aggregations:
            continue
        grid_id = spec.get("grid_id", "")
        for aggregation in aggregations:
            path = (
                series_root / grid_id / metric_id / "aggregates" / f"{aggregation}.json"
            )
            rel = path.relative_to(series_root.parent)
            if not path.exists():
                errors.append(f"Missing aggregate file: {rel}")
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                errors.append(f"Cannot parse {rel}: {exc}")
                continue
            regions = data.get("regions", {})
            if not regions:
                errors.append(f"Empty regions in {rel}")
                continue
            time_axis = data.get("time_axis", [])
            if not time_axis:
                errors.append(f"Empty time_axis in {rel}")
                continue
            n_steps = len(time_axis)
            for region_id, info in regions.items():
                values = info.get("values", [])
                if len(values) != n_steps:
                    errors.append(
                        f"{rel}: region {region_id!r} has {len(values)} values "
                        f"but time_axis has {n_steps} entries"
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

    errors = check_aggregates(
        metrics_path=args.metrics,
        series_root=args.series_root,
    )

    if errors:
        for err in errors:
            print(f"  ERROR: {err}", file=sys.stderr)
        print(f"[aggregates] {len(errors)} error(s) found", file=sys.stderr)
        return 1

    print("[aggregates] all aggregate files present and valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
