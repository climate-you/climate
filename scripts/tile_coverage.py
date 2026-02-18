#!/usr/bin/env python3
"""
Tiny tile coverage checker.

Reads tiles directly from disk (no API), and reports how many cells in each tile
contain non-NaN data (for float tiles). This matches the current v0 convention
where "missing" is encoded as NaN for float metrics.

Example:
  python scripts/debug_tile_coverage.py --root data/releases/dev --metric t2m_yearly_mean_c
  python scripts/debug_tile_coverage.py --root data/releases/dev
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import numpy as np

from climate.registry.maps import DEFAULT_MAPS_PATH, DEFAULT_MAPS_SCHEMA_PATH, load_maps
from climate.registry.metrics import (
    DEFAULT_DATASETS_PATH,
    DEFAULT_DATASETS_SCHEMA_PATH,
    DEFAULT_METRICS_PATH,
    DEFAULT_SCHEMA_PATH,
    load_metrics,
)
from climate.registry.panels import (
    DEFAULT_PANELS_PATH,
    DEFAULT_PANELS_SCHEMA_PATH,
    load_panels,
)
from climate.tiles.layout import GridSpec
from climate.tiles.spec import read_tile_array


_TILE_RE = re.compile(r"r(\d+)_c(\d+)\.bin(\.zst)?$")


def _parse_tile_rc(path: Path) -> tuple[int, int] | None:
    m = _TILE_RE.search(path.name)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _iter_tile_files(zdir: Path) -> list[Path]:
    # Support both compressed and uncompressed
    files = list(zdir.glob("r*_c*.bin.zst")) + list(zdir.glob("r*_c*.bin"))

    # Sort by (r,c) if possible, else by name
    def key(p: Path):
        rc = _parse_tile_rc(p)
        return (rc[0], rc[1]) if rc else (10**9, 10**9)

    return sorted(files, key=key)


def _valid_hw(grid: GridSpec, tr: int, tc: int) -> tuple[int, int]:
    """
    Returns (valid_h, valid_w): how many *real* globe cells exist in this tile.
    Edge tiles may be partial; padding cells are excluded.
    """
    r0 = tr * grid.tile_size
    c0 = tc * grid.tile_size
    if r0 >= grid.nlat or c0 >= grid.nlon:
        return 0, 0
    valid_h = min(grid.tile_size, grid.nlat - r0)
    valid_w = min(grid.tile_size, grid.nlon - c0)
    return int(valid_h), int(valid_w)


def _count_nonempty_cells_window(
    hdr_nyears: int, arr: np.ndarray, valid_h: int, valid_w: int
) -> tuple[int, int]:
    """
    Same as _count_nonempty_cells, but only for the real-grid window [0:valid_h, 0:valid_w].
    Returns (nonempty_cells, total_cells) for that window.
    """
    total = int(valid_h * valid_w)
    if total <= 0:
        return 0, 0

    if hdr_nyears == 0:
        # scalar: (H,W)
        a = arr[:valid_h, :valid_w]
        if not np.issubdtype(a.dtype, np.floating):
            return total, total
        nonempty = int(np.sum(~np.isnan(a)))
        return nonempty, total

    # series: (H,W,Y)
    a = arr[:valid_h, :valid_w, :]
    if not np.issubdtype(a.dtype, np.floating):
        return total, total
    nonempty_mask = ~np.all(np.isnan(a), axis=2)
    nonempty = int(np.sum(nonempty_mask))
    return nonempty, total


def _count_nonempty_cells(hdr_nyears: int, arr: np.ndarray) -> tuple[int, int]:
    """
    Returns (nonempty_cells, total_cells) for float tiles using NaN as missing.
    For integer tiles, we can't reliably infer "missing" (0 can be valid), so we return (total, total).
    """
    total = int(arr.shape[0] * arr.shape[1])

    if not np.issubdtype(arr.dtype, np.floating):
        # Can't infer missing reliably for integer tiles in a generic way.
        return total, total

    if hdr_nyears == 0:
        # scalar: (H,W)
        nonempty = int(np.sum(~np.isnan(arr)))
        return nonempty, total

    # series: (H,W,Y)
    nonempty_mask = ~np.all(np.isnan(arr), axis=2)
    nonempty = int(np.sum(nonempty_mask))
    return nonempty, total


def _grid_from_id(grid_id: str, tile_size: int) -> GridSpec:
    if grid_id == "global_0p25":
        return GridSpec.global_0p25(tile_size=tile_size)
    raise SystemExit(
        f"Unsupported grid_id {grid_id!r} (v0 supports 'global_0p25' only)"
    )


def _metric_summary(
    *,
    root: Path,
    metric_id: str,
    grid_id: str,
    tile_size: int,
    max_tiles: int,
    summary_only: bool,
) -> dict[str, float]:
    grid = _grid_from_id(grid_id, tile_size=tile_size)
    zdir = root / "series" / grid.grid_id / metric_id / f"z{grid.tile_size}"
    if not zdir.exists():
        print(f"[warn] Tile directory not found: {zdir}")
        return {
            "tiles_found": 0.0,
            "tiles_expected": 0.0,
            "real_coverage_pct": 0.0,
        }

    files = _iter_tile_files(zdir)
    if max_tiles and max_tiles > 0:
        files = files[: max_tiles]

    if not files:
        print(f"[warn] No tile files found in: {zdir}")
        return {
            "tiles_found": 0.0,
            "tiles_expected": 0.0,
            "real_coverage_pct": 0.0,
        }

    total_tiles = 0
    total_tiles_expected = ((grid.nlat + grid.tile_size - 1) // grid.tile_size) * (
        (grid.nlon + grid.tile_size - 1) // grid.tile_size
    )

    total_container_cells = 0
    total_container_nonempty = 0

    total_real_cells = grid.nlat * grid.nlon
    total_real_nonempty = 0

    for p in files:
        rc = _parse_tile_rc(p)
        if rc is None:
            continue
        tr, tc = rc

        hdr, arr = read_tile_array(p)

        nonempty_c, total_c = _count_nonempty_cells(hdr.nyears, arr)
        frac_c = 100.0 * (nonempty_c / total_c if total_c else 0.0)

        valid_h, valid_w = _valid_hw(grid, tr, tc)
        nonempty_r, total_r = _count_nonempty_cells_window(
            hdr.nyears, arr, valid_h, valid_w
        )
        frac_r = 100.0 * (nonempty_r / total_r if total_r else 0.0)

        total_tiles += 1
        total_container_cells += total_c
        total_container_nonempty += nonempty_c
        total_real_nonempty += nonempty_r

        if not summary_only:
            print(
                f"tile r{tr:03d} c{tc:03d}  nyears={hdr.nyears:>3d}  "
                f"dtype={str(arr.dtype):>6s}  "
                f"container={nonempty_c:5d}/{total_c:5d}  ({frac_c:6.2f}%)  "
                f"real={nonempty_r:5d}/{total_r:5d}  ({frac_r:6.2f}%)  "
                f"{p.name}"
            )

    total_container_cells_expected = total_tiles_expected * grid.tile_size * grid.tile_size
    overall_c = 100.0 * (
        total_container_nonempty / total_container_cells_expected
        if total_container_cells_expected
        else 0.0
    )
    overall_r = 100.0 * (
        total_real_nonempty / total_real_cells if total_real_cells else 0.0
    )
    print(
        f"\nSUMMARY: metric={metric_id} tiles={total_tiles}/{total_tiles_expected}  "
        f"container_nonempty={total_container_nonempty}/{total_container_cells_expected}  ({overall_c:.2f}%)  "
        f"real_nonempty={total_real_nonempty}/{total_real_cells}  ({overall_r:.2f}%)\n"
    )
    return {
        "tiles_found": float(total_tiles),
        "tiles_expected": float(total_tiles_expected),
        "real_coverage_pct": float(overall_r),
    }


def _is_materialized_tiled(spec: dict) -> bool:
    storage = spec.get("storage", {})
    return bool(storage.get("tiled", True)) and spec.get("materialize") in (
        None,
        "on_packager",
    )


def _registry_metrics(
    metrics_path: Path,
    schema_path: Path,
    datasets_path: Path,
    datasets_schema_path: Path,
) -> list[tuple[str, dict]]:
    manifest = load_metrics(
        metrics_path,
        schema_path=schema_path,
        datasets_path=datasets_path,
        datasets_schema_path=datasets_schema_path,
        validate=True,
    )
    items: list[tuple[str, dict]] = []
    for metric_id, spec in manifest.items():
        if metric_id == "version":
            continue
        if not _is_materialized_tiled(spec):
            continue
        items.append((metric_id, spec))
    return items


def _referenced_registry_metrics(
    *,
    metrics_path: Path,
    metrics_schema_path: Path,
    datasets_path: Path,
    datasets_schema_path: Path,
    maps_path: Path,
    maps_schema_path: Path,
    panels_path: Path,
    panels_schema_path: Path,
) -> list[tuple[str, dict]]:
    metrics = load_metrics(
        metrics_path,
        schema_path=metrics_schema_path,
        datasets_path=datasets_path,
        datasets_schema_path=datasets_schema_path,
        validate=True,
    )
    maps = load_maps(maps_path, schema_path=maps_schema_path, validate=True)
    panels = load_panels(panels_path, schema_path=panels_schema_path, validate=True)

    seeds: set[str] = set()

    for map_id, spec in maps.items():
        if map_id == "version" or not isinstance(spec, dict):
            continue
        source_metric = spec.get("source_metric")
        if isinstance(source_metric, str) and source_metric:
            seeds.add(source_metric)

    panels_root = panels.get("panels", {})
    if isinstance(panels_root, dict):
        for panel in panels_root.values():
            if not isinstance(panel, dict):
                continue
            graphs = panel.get("graphs", [])
            if not isinstance(graphs, list):
                continue
            for graph in graphs:
                if not isinstance(graph, dict):
                    continue
                series_list = graph.get("series", [])
                if not isinstance(series_list, list):
                    continue
                for series in series_list:
                    if not isinstance(series, dict):
                        continue
                    metric_id = series.get("metric")
                    if isinstance(metric_id, str) and metric_id:
                        seeds.add(metric_id)

    visited: set[str] = set()
    stack = list(seeds)
    while stack:
        metric_id = stack.pop()
        if metric_id in visited:
            continue
        visited.add(metric_id)
        spec = metrics.get(metric_id)
        if not isinstance(spec, dict):
            continue
        source = spec.get("source", {})
        if source.get("type") != "derived":
            continue
        for dep in source.get("inputs", []) or []:
            if isinstance(dep, str) and dep:
                stack.append(dep)

    selected: list[tuple[str, dict]] = []
    for metric_id in sorted(visited):
        spec = metrics.get(metric_id)
        if metric_id == "version" or not isinstance(spec, dict):
            continue
        if _is_materialized_tiled(spec):
            selected.append((metric_id, spec))
    return selected


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path("data/releases/dev"))
    ap.add_argument("--metric", type=str, default=None)
    ap.add_argument("--metrics-path", type=Path, default=DEFAULT_METRICS_PATH)
    ap.add_argument("--datasets-path", type=Path, default=DEFAULT_DATASETS_PATH)
    ap.add_argument("--schema-path", type=Path, default=DEFAULT_SCHEMA_PATH)
    ap.add_argument(
        "--datasets-schema-path", type=Path, default=DEFAULT_DATASETS_SCHEMA_PATH
    )
    ap.add_argument("--maps-path", type=Path, default=DEFAULT_MAPS_PATH)
    ap.add_argument("--maps-schema-path", type=Path, default=DEFAULT_MAPS_SCHEMA_PATH)
    ap.add_argument("--panels-path", type=Path, default=DEFAULT_PANELS_PATH)
    ap.add_argument(
        "--panels-schema-path", type=Path, default=DEFAULT_PANELS_SCHEMA_PATH
    )
    ap.add_argument(
        "--only-referenced-metrics",
        action="store_true",
        help="Check only metrics referenced by maps/panels, plus derived dependencies.",
    )
    ap.add_argument(
        "--require-real-coverage-pct",
        type=float,
        default=None,
        help="Fail if any checked metric is below this real coverage percentage.",
    )
    ap.add_argument("--max-tiles", type=int, default=0, help="0 = no limit")
    ap.add_argument("--summary-only", action="store_true")
    args = ap.parse_args()

    if args.metric:
        stats = _metric_summary(
            root=args.root,
            metric_id=args.metric,
            grid_id="global_0p25",
            tile_size=64,
            max_tiles=args.max_tiles,
            summary_only=args.summary_only,
        )
        if (
            args.require_real_coverage_pct is not None
            and stats["real_coverage_pct"] < args.require_real_coverage_pct
        ):
            raise SystemExit(2)
        return

    if args.only_referenced_metrics:
        metrics = _referenced_registry_metrics(
            metrics_path=args.metrics_path,
            metrics_schema_path=args.schema_path,
            datasets_path=args.datasets_path,
            datasets_schema_path=args.datasets_schema_path,
            maps_path=args.maps_path,
            maps_schema_path=args.maps_schema_path,
            panels_path=args.panels_path,
            panels_schema_path=args.panels_schema_path,
        )
    else:
        metrics = _registry_metrics(
            args.metrics_path,
            args.schema_path,
            args.datasets_path,
            args.datasets_schema_path,
        )

    failures: list[str] = []
    for metric_id, spec in metrics:
        storage = spec.get("storage", {})
        tile_size = int(storage.get("tile_size", 64))
        grid_id = spec.get("grid_id", "global_0p25")
        print(f"== metric: {metric_id}  grid={grid_id}  tile_size={tile_size} ==")
        stats = _metric_summary(
            root=args.root,
            metric_id=metric_id,
            grid_id=grid_id,
            tile_size=tile_size,
            max_tiles=args.max_tiles,
            summary_only=args.summary_only,
        )
        if (
            args.require_real_coverage_pct is not None
            and stats["real_coverage_pct"] < args.require_real_coverage_pct
        ):
            failures.append(
                f"{metric_id}: real coverage {stats['real_coverage_pct']:.2f}% < {args.require_real_coverage_pct:.2f}%"
            )

    if failures:
        print("Coverage checks failed:")
        for item in failures:
            print(f"- {item}")
        raise SystemExit(2)


if __name__ == "__main__":
    main()
