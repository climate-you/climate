#!/usr/bin/env python3
"""
Tiny tile coverage checker.

Reads tiles directly from disk (no API), and reports how many cells in each tile
contain non-NaN data (for float tiles). This matches the current v0 convention
where "missing" is encoded as NaN for float metrics.

Example:
  python scripts/tile_coverage.py --root data/releases/dev --metric t2m_yearly_mean_c
  python scripts/tile_coverage.py --root data/releases/dev
"""

from __future__ import annotations

import argparse
import json
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
from climate.tiles import zarr_tiles
from climate.tiles.io import metric_root, read_metric_tile, storage_format, tile_written
from climate.tiles.layout import GridSpec, grid_from_id, tile_counts


_TILE_RE = re.compile(r"r(\d+)_c(\d+)\.bin(\.zst)?$")
REPO_ROOT = Path(__file__).resolve().parents[1]


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


def _tiles_present(
    root: Path, grid: GridSpec, metric_id: str, storage: dict | None
) -> tuple[Path, list[tuple[int, int]] | None]:
    """(where the tiles live, sorted (tile_r, tile_c) on disk), or None when that place is missing.

    A zarr tile is listed once every time shard of it is on disk.
    """
    mroot = metric_root(root / "series", grid, metric_id)
    if storage_format(storage) == "zarr":
        zdir = zarr_tiles.zarr_dir(mroot)
        meta = zdir / "zarr.json"
        if not meta.exists():
            return zdir, None
        meta_json = json.loads(meta.read_text(encoding="utf-8"))
        shape = meta_json["shape"]
        if len(shape) == 2:
            pattern, blocks = "*/*", 1
        else:
            st = int(meta_json["chunk_grid"]["configuration"]["chunk_shape"][0])
            pattern, blocks = "*/*/*", -(-int(shape[0]) // st)
        counts: dict[tuple[int, int], int] = {}
        for p in (zdir / "c").glob(pattern):
            if p.is_file():
                rc = (int(p.parent.name), int(p.name))
                counts[rc] = counts.get(rc, 0) + 1
        return zdir, sorted(rc for rc, n in counts.items() if n == blocks)
    zdir = mroot / f"z{grid.tile_size}"
    if not zdir.exists():
        return zdir, None
    rcs = [rc for rc in (_parse_tile_rc(p) for p in _iter_tile_files(zdir)) if rc]
    return zdir, rcs


def _format_mismatch(
    root: Path, grid: GridSpec, metric_id: str, storage: dict | None
) -> str | None:
    """Why the files on disk disagree with the registry's storage.format, or None.

    The API reads each metric in the format its release registry declares, so a
    release whose files are in the other format would fail in production.
    """
    mroot = metric_root(root / "series", grid, metric_id)
    has_zarr = (zarr_tiles.zarr_dir(mroot) / "zarr.json").exists()
    has_clmtile = (mroot / f"z{grid.tile_size}").is_dir()
    declared = storage_format(storage)
    if has_zarr and has_clmtile:
        return f"{metric_id}: both zarr/ and z{grid.tile_size}/ on disk (registry says {declared})"
    if declared == "zarr" and has_clmtile:
        return f"{metric_id}: registry says zarr but the files are clmtile (z{grid.tile_size}/)"
    if declared == "clmtile" and has_zarr:
        return f"{metric_id}: registry says clmtile but the files are zarr (zarr/)"
    return None


def _read_tile(
    root: Path, grid: GridSpec, metric_id: str, tr: int, tc: int, storage: dict | None
) -> tuple[int, np.ndarray]:
    """(nyears, tile) with nyears = 0 for a scalar metric, as the old tile header says."""
    arr = read_metric_tile(root / "series", grid, metric_id, tr, tc, storage)
    return (0 if arr.ndim == 2 else int(arr.shape[2])), arr


def _missing_tiles(
    root: Path, grid: GridSpec, metric_id: str, storage: dict | None
) -> list[tuple[int, int]]:
    """Tiles of the grid that are not (fully) on disk.

    Every tile is stored, an empty one included, so readers treat a missing
    tile as an error; this lists them before a publish does.
    """
    ntr, ntc = tile_counts(grid)
    return [
        (tr, tc)
        for tr in range(ntr)
        for tc in range(ntc)
        if not tile_written(root / "series", grid, metric_id, tr, tc, storage)
    ]


def _tile_list(tiles: list[tuple[int, int]]) -> str:
    shown = ", ".join(f"r{tr} c{tc}" for tr, tc in tiles[:5])
    return f"{shown}{', ...' if len(tiles) > 5 else ''}"


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


def _nonempty_mask_window(
    hdr_nyears: int, arr: np.ndarray, valid_h: int, valid_w: int
) -> np.ndarray:
    """
    Returns a boolean mask (valid_h, valid_w) where True means "at least one
    finite value across time" for float tiles.
    """
    if valid_h <= 0 or valid_w <= 0:
        return np.zeros((0, 0), dtype=bool)

    if hdr_nyears == 0:
        a = arr[:valid_h, :valid_w]
        if not np.issubdtype(a.dtype, np.floating):
            return np.ones((valid_h, valid_w), dtype=bool)
        return ~np.isnan(a)

    a = arr[:valid_h, :valid_w, :]
    if not np.issubdtype(a.dtype, np.floating):
        return np.ones((valid_h, valid_w), dtype=bool)
    return ~np.all(np.isnan(a), axis=2)


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


def _metric_summary(
    *,
    root: Path,
    metric_id: str,
    grid_id: str,
    tile_size: int,
    max_tiles: int,
    summary_only: bool,
    domain_mask: np.ndarray | None = None,
    domain_label: str = "global",
    storage: dict | None = None,
    count_outside: bool = False,
) -> dict:
    """Coverage of one metric; with count_outside, also its data cells outside domain_mask.

    count_outside only makes sense when domain_mask is a dataset mask, which
    says cell by cell where data may be, not a mask built from another
    metric's data.
    """
    grid = grid_from_id(grid_id, tile_size=tile_size)
    zdir, tiles = _tiles_present(root, grid, metric_id, storage)
    if tiles is None:
        print(f"[warn] Tile directory not found: {zdir}")
        return {
            "tiles_found": 0.0,
            "tiles_expected": 0.0,
            "real_coverage_pct": 0.0,
        }

    if max_tiles and max_tiles > 0:
        tiles = tiles[:max_tiles]

    if not tiles:
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
    domain_total_cells = (
        int(np.count_nonzero(domain_mask))
        if domain_mask is not None
        else total_real_cells
    )
    domain_nonempty = 0
    outside_cells = 0
    outside_tiles: list[tuple[int, int]] = []

    for tr, tc in tiles:
        nyears, arr = _read_tile(root, grid, metric_id, tr, tc, storage)

        nonempty_c, total_c = _count_nonempty_cells(nyears, arr)
        frac_c = 100.0 * (nonempty_c / total_c if total_c else 0.0)

        valid_h, valid_w = _valid_hw(grid, tr, tc)
        nonempty_r, total_r = _count_nonempty_cells_window(
            nyears, arr, valid_h, valid_w
        )
        nonempty_mask_r = _nonempty_mask_window(nyears, arr, valid_h, valid_w)
        frac_r = 100.0 * (nonempty_r / total_r if total_r else 0.0)

        total_tiles += 1
        total_container_cells += total_c
        total_container_nonempty += nonempty_c
        total_real_nonempty += nonempty_r
        if domain_mask is not None:
            r0 = tr * grid.tile_size
            c0 = tc * grid.tile_size
            dm = domain_mask[r0 : r0 + valid_h, c0 : c0 + valid_w]
            domain_nonempty += int(np.count_nonzero(nonempty_mask_r & dm))
            if count_outside:
                n_out = int(np.count_nonzero(nonempty_mask_r & ~dm))
                if n_out:
                    outside_cells += n_out
                    outside_tiles.append((tr, tc))
        else:
            domain_nonempty += nonempty_r

        if not summary_only:
            print(
                f"tile r{tr:03d} c{tc:03d}  nyears={nyears:>3d}  "
                f"dtype={str(arr.dtype):>6s}  "
                f"container={nonempty_c:5d}/{total_c:5d}  ({frac_c:6.2f}%)  "
                f"real={nonempty_r:5d}/{total_r:5d}  ({frac_r:6.2f}%)"
            )

    total_container_cells_expected = (
        total_tiles_expected * grid.tile_size * grid.tile_size
    )
    overall_c = 100.0 * (
        total_container_nonempty / total_container_cells_expected
        if total_container_cells_expected
        else 0.0
    )
    overall_r = 100.0 * (
        total_real_nonempty / total_real_cells if total_real_cells else 0.0
    )
    overall_domain = 100.0 * (
        domain_nonempty / domain_total_cells if domain_total_cells else 0.0
    )
    print(
        f"\nSUMMARY: metric={metric_id} tiles={total_tiles}/{total_tiles_expected}  "
        f"container_nonempty={total_container_nonempty}/{total_container_cells_expected}  ({overall_c:.2f}%)  "
        f"real_nonempty={total_real_nonempty}/{total_real_cells}  ({overall_r:.2f}%)  "
        f"domain={domain_label} nonempty={domain_nonempty}/{domain_total_cells}  ({overall_domain:.2f}%)"
        + (f"  outside={outside_cells}" if count_outside else "")
        + "\n"
    )
    return {
        "tiles_found": float(total_tiles),
        "tiles_expected": float(total_tiles_expected),
        "real_coverage_pct": float(overall_r),
        "domain_coverage_pct": float(overall_domain),
        "outside_cells": float(outside_cells),
        "outside_tiles": outside_tiles,
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


def _metric_domain(spec: dict) -> str:
    domain = spec.get("domain")
    if isinstance(domain, str) and domain in {
        "global",
        "ocean",
        "land",
        "dataset_mask",
    }:
        return domain

    # Backward-compatible fallback for old release registries without domain.
    source = spec.get("source", {})
    dataset_ref = source.get("_dataset_ref") or source.get("dataset_ref")
    dataset_key = source.get("dataset_key")

    tokens = []
    if isinstance(dataset_ref, str):
        tokens.append(dataset_ref.lower())
    if isinstance(dataset_key, str):
        tokens.append(dataset_key.lower())

    if any("oisst" in tok or "sst" in tok for tok in tokens):
        return "ocean"
    return "global"


def _build_metric_presence_mask(
    *,
    root: Path,
    metric_id: str,
    grid_id: str,
    tile_size: int,
    storage: dict | None = None,
) -> np.ndarray:
    grid = grid_from_id(grid_id, tile_size=tile_size)
    zdir, tiles = _tiles_present(root, grid, metric_id, storage)
    if tiles is None:
        raise SystemExit(f"Mask metric tiles not found: {zdir}")
    if not tiles:
        raise SystemExit(f"No mask tiles found: {zdir}")

    mask = np.zeros((grid.nlat, grid.nlon), dtype=bool)
    for tr, tc in tiles:
        nyears, arr = _read_tile(root, grid, metric_id, tr, tc, storage)
        valid_h, valid_w = _valid_hw(grid, tr, tc)
        if valid_h <= 0 or valid_w <= 0:
            continue
        local = _nonempty_mask_window(nyears, arr, valid_h, valid_w)
        r0 = tr * grid.tile_size
        c0 = tc * grid.tile_size
        mask[r0 : r0 + valid_h, c0 : c0 + valid_w] = local
    return mask


def _resolve_dataset_mask_file(
    *,
    metric_id: str,
    metrics: dict[str, dict],
) -> str:
    visited: set[str] = set()

    def _walk(mid: str) -> set[str]:
        if mid in visited:
            return set()
        visited.add(mid)
        spec = metrics.get(mid)
        if not isinstance(spec, dict):
            return set()
        source = spec.get("source", {})
        if not isinstance(source, dict):
            return set()
        source_type = source.get("type")
        if source_type in {"cds", "erddap"}:
            mask_file = source.get("mask_file")
            if isinstance(mask_file, str) and mask_file.strip():
                return {mask_file}
            return set()
        if source_type == "derived":
            files: set[str] = set()
            for dep in source.get("inputs", []) or []:
                if isinstance(dep, str):
                    files.update(_walk(dep))
            return files
        return set()

    files = _walk(metric_id)
    if not files:
        raise SystemExit(
            f"Metric {metric_id!r} has domain=dataset_mask but no source.mask_file in ancestry."
        )
    if len(files) > 1:
        raise SystemExit(
            f"Metric {metric_id!r} has multiple source.mask_file entries in ancestry: {sorted(files)}"
        )
    return next(iter(files))


def _load_dataset_mask_file(mask_file: str, *, grid: GridSpec) -> np.ndarray:
    mask_path = Path(mask_file)
    if not mask_path.is_absolute():
        mask_path = REPO_ROOT / mask_path
    if not mask_path.exists():
        raise SystemExit(f"Dataset mask file not found: {mask_path}")

    with np.load(mask_path, allow_pickle=False) as npz:
        if "data" not in npz:
            raise SystemExit(f"Dataset mask file missing 'data' array: {mask_path}")
        raw = np.asarray(npz["data"])
        if raw.ndim != 2:
            raise SystemExit(
                f"Dataset mask file expected 2D data, got shape={raw.shape}: {mask_path}"
            )
        if raw.shape != (grid.nlat, grid.nlon):
            raise SystemExit(
                f"Dataset mask grid mismatch for {mask_path}: mask={raw.shape}, "
                f"metric_grid=({grid.nlat},{grid.nlon})"
            )
        if raw.dtype == np.bool_:
            mask = raw.astype(bool, copy=False)
        elif np.issubdtype(raw.dtype, np.floating):
            mask = np.isfinite(raw) & (raw != 0.0)
        else:
            mask = raw != 0

        if "deg" in npz:
            deg = float(np.asarray(npz["deg"]).reshape(()))
            if not np.isclose(deg, float(grid.deg), atol=1e-9):
                raise SystemExit(
                    f"Dataset mask resolution mismatch for {mask_path}: "
                    f"mask_deg={deg}, metric_deg={grid.deg}"
                )

    return mask


def _remap_mask_to_grid(
    *,
    source_mask: np.ndarray,
    source_grid: GridSpec,
    target_grid: GridSpec,
) -> np.ndarray:
    """
    Remap a presence mask from source grid to target grid using nearest-cell lookup.
    Works for mixed grid resolutions (e.g. 0.25 -> 0.05).
    """
    if (
        source_grid.nlat == target_grid.nlat
        and source_grid.nlon == target_grid.nlon
        and abs(float(source_grid.deg) - float(target_grid.deg)) < 1e-12
    ):
        return source_mask

    lat_t = target_grid.lat_max - (
        np.arange(target_grid.nlat, dtype=np.float64) + 0.5
    ) * float(target_grid.deg)
    lat_t = np.clip(lat_t, -source_grid.lat_max + 1e-12, source_grid.lat_max - 1e-12)
    src_i_lat = np.floor((source_grid.lat_max - lat_t) / float(source_grid.deg)).astype(
        np.int64
    )
    src_i_lat = np.clip(src_i_lat, 0, source_grid.nlat - 1)

    lon_t = target_grid.lon_min + (
        np.arange(target_grid.nlon, dtype=np.float64) + 0.5
    ) * float(target_grid.deg)
    lon_t = ((lon_t + 180.0) % 360.0) - 180.0
    src_i_lon = np.floor((lon_t - source_grid.lon_min) / float(source_grid.deg)).astype(
        np.int64
    )
    src_i_lon = np.clip(src_i_lon, 0, source_grid.nlon - 1)

    return source_mask[src_i_lat[:, None], src_i_lon[None, :]]


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
    ap.add_argument(
        "--domain-aware",
        action="store_true",
        help="Evaluate coverage against expected metric domain (e.g. ocean-only for SST).",
    )
    ap.add_argument(
        "--ocean-mask-metric",
        type=str,
        default="sst_yearly_mean_c",
        help="Metric used as ocean-domain mask when --domain-aware is enabled.",
    )
    args = ap.parse_args()

    if args.domain_aware and args.max_tiles:
        raise SystemExit("--domain-aware requires --max-tiles 0 (full coverage scan).")

    if args.metric:
        stats = _metric_summary(
            root=args.root,
            metric_id=args.metric,
            grid_id="global_0p25",
            tile_size=64,
            max_tiles=args.max_tiles,
            summary_only=args.summary_only,
            domain_label="global",
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
    ocean_mask_cache: dict[tuple[str, int, str], np.ndarray] = {}
    dataset_mask_cache: dict[tuple[str, int, str], np.ndarray] = {}
    metrics_by_id = {metric_id: spec for metric_id, spec in metrics}
    for metric_id, spec in metrics:
        storage = spec.get("storage", {})
        tile_size = int(storage.get("tile_size", 64))
        grid_id = spec.get("grid_id", "global_0p25")
        domain_mask = None
        domain_label = "global"
        if args.domain_aware:
            domain_label = _metric_domain(spec)
            if domain_label == "ocean":
                if args.ocean_mask_metric not in metrics_by_id:
                    raise SystemExit(
                        f"--ocean-mask-metric={args.ocean_mask_metric!r} not found in loaded metrics."
                    )
                key = (grid_id, tile_size, args.ocean_mask_metric)
                if key not in ocean_mask_cache:
                    ocean_spec = metrics_by_id[args.ocean_mask_metric]
                    ocean_storage = ocean_spec.get("storage", {})
                    ocean_grid_id = str(ocean_spec.get("grid_id", "global_0p25"))
                    ocean_tile_size = int(ocean_storage.get("tile_size", 64))
                    ocean_source_key = (
                        ocean_grid_id,
                        ocean_tile_size,
                        args.ocean_mask_metric,
                    )
                    if ocean_source_key not in ocean_mask_cache:
                        ocean_mask_cache[ocean_source_key] = (
                            _build_metric_presence_mask(
                                root=args.root,
                                metric_id=args.ocean_mask_metric,
                                grid_id=ocean_grid_id,
                                tile_size=ocean_tile_size,
                                storage=ocean_storage,
                            )
                        )
                    source_grid = grid_from_id(ocean_grid_id, tile_size=ocean_tile_size)
                    target_grid = grid_from_id(grid_id, tile_size=tile_size)
                    ocean_mask_cache[key] = _remap_mask_to_grid(
                        source_mask=ocean_mask_cache[ocean_source_key],
                        source_grid=source_grid,
                        target_grid=target_grid,
                    )
                domain_mask = ocean_mask_cache[key]
            elif domain_label == "dataset_mask":
                key = (grid_id, tile_size, metric_id)
                if key not in dataset_mask_cache:
                    metric_grid = grid_from_id(grid_id, tile_size=tile_size)
                    mask_file = _resolve_dataset_mask_file(
                        metric_id=metric_id,
                        metrics=metrics_by_id,
                    )
                    dataset_mask_cache[key] = _load_dataset_mask_file(
                        mask_file,
                        grid=metric_grid,
                    )
                domain_mask = dataset_mask_cache[key]
        print(f"== metric: {metric_id}  grid={grid_id}  tile_size={tile_size} ==")
        mismatch = _format_mismatch(
            args.root, grid_from_id(grid_id, tile_size=tile_size), metric_id, storage
        )
        if mismatch:
            print(f"[error] {mismatch}")
            failures.append(mismatch)
            continue
        missing_tiles = _missing_tiles(
            args.root, grid_from_id(grid_id, tile_size=tile_size), metric_id, storage
        )
        if missing_tiles:
            msg = (
                f"{metric_id}: {len(missing_tiles)} tile(s) missing "
                f"({_tile_list(missing_tiles)})"
            )
            print(f"[error] {msg}")
            failures.append(msg)
        stats = _metric_summary(
            root=args.root,
            metric_id=metric_id,
            grid_id=grid_id,
            tile_size=tile_size,
            max_tiles=args.max_tiles,
            summary_only=args.summary_only,
            domain_mask=domain_mask,
            domain_label=domain_label,
            storage=storage,
            # A dataset mask says cell by cell where data may be; the ocean mask
            # is built from SST's own data, so nothing can fall outside it.
            count_outside=domain_label == "dataset_mask",
        )
        if stats.get("outside_cells"):
            msg = (
                f"{metric_id}: {int(stats['outside_cells'])} data cell(s) outside the dataset mask "
                f"(tiles {_tile_list(stats['outside_tiles'])})"
            )
            print(f"[error] {msg}")
            failures.append(msg)
        check_pct = (
            stats["domain_coverage_pct"]
            if args.domain_aware
            else stats["real_coverage_pct"]
        )
        check_label = "domain coverage" if args.domain_aware else "real coverage"
        # A metric may declare its own floor when its definition leaves cells
        # undefined — a percentage of a near-zero normal, say. The registry
        # entry has to carry a reason, so the exemption sits where the metric is
        # defined rather than buried in a suite-wide flag.
        coverage_rule = (metrics_by_id.get(metric_id) or {}).get("coverage") or {}
        required_pct = coverage_rule.get("min_real_pct", args.require_real_coverage_pct)
        if required_pct is not None and check_pct < required_pct:
            failures.append(
                f"{metric_id}: {check_label} {check_pct:.2f}% < {required_pct:.2f}%"
            )
        elif coverage_rule:
            print(
                f"   declared coverage floor {required_pct:.2f}%: "
                f"{coverage_rule.get('reason', '')}"
            )

    if failures:
        print("Coverage checks failed:")
        for item in failures:
            print(f"- {item}")
        raise SystemExit(2)


if __name__ == "__main__":
    main()
