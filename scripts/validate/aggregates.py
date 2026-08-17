#!/usr/bin/env python3
"""Validate that precomputed aggregate files exist for all metrics that declare them.

Checks that for every metric with an 'aggregates' field in metrics.json, the
corresponding aggregate JSON files exist under:
  <series_root>/<grid_id>/<metric_id>/aggregates/<aggregation>.json

Also verifies that each file contains non-empty regions and that the number of
values per region matches the length of the time_axis.

Finally — and this is the check that catches the common failure — it compares
each aggregate's time_axis against the metric's own canonical axis. An
aggregate is internally consistent forever once written, so extending a metric
with new data leaves a perfectly valid file that silently stops short: region
queries then return nothing for the new period while point queries work fine.
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


def _metric_time_axis(series_root: Path, grid_id: str, metric_id: str, spec: dict):
    """The metric's canonical axis, as written next to its tiles.

    Returns None when the metric ships no axis file, in which case there is
    nothing to compare an aggregate against.
    """
    axis_name = spec.get("time_axis", "yearly")
    path = series_root / grid_id / metric_id / "time" / f"{axis_name}.json"
    if not path.exists():
        return None
    try:
        axis = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return [str(v) for v in axis] if isinstance(axis, list) else None


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
        metric_axis = _metric_time_axis(series_root, grid_id, metric_id, spec)
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

            # Staleness: the file is valid on its own terms but no longer
            # covers everything the metric holds.
            if metric_axis:
                agg_axis = [str(v) for v in time_axis]
                if agg_axis != metric_axis:
                    missing = [v for v in metric_axis if v not in set(agg_axis)]
                    if missing:
                        errors.append(
                            f"STALE {rel}: aggregate ends at {agg_axis[-1]} "
                            f"({len(agg_axis)} steps) but metric {metric_id} has data "
                            f"to {metric_axis[-1]} ({len(metric_axis)} steps) — "
                            f"{len(missing)} step(s) missing, so region queries return "
                            f"nothing for them. Regenerate with: "
                            f"scripts/precompute_regional_aggregates.py --metrics {metric_id}"
                        )
                    else:
                        errors.append(
                            f"{rel}: aggregate axis does not match metric {metric_id} "
                            f"(aggregate {len(agg_axis)} steps, metric "
                            f"{len(metric_axis)} steps)"
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
