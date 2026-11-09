#!/usr/bin/env python3
"""Convert a release's tiles from the clmtile format to zarr.

v2.5 ships the zarr format on the data already published (decision 9 in the v3
master plan), so instead of re-packaging from the caches this rewrites an
existing release: every tiled metric the registry declares as zarr is written
as a zarr array, with the encoding its ``storage`` entry asks for; everything
else (time axes, aggregates, rankings, metrics still declared clmtile, maps,
aux) is copied unchanged. The source release is only read.

Every tile is checked after it is written: the same cells are missing, and
every value is within half an encoding step of the original (exact for
float32). Any difference fails the run. Every source tile is written, an empty
one included, so the zarr array has a shard wherever the old format had a file.

Usage:
  python scripts/build/convert_release_to_zarr.py \\
    --src ../source/data/releases/dev --dst data/releases/dev [--metric ID ...] [--workers 8]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from climate.registry.metrics import load_metrics  # noqa: E402
from climate.tiles import zarr_tiles  # noqa: E402
from climate.tiles.io import (  # noqa: E402
    clmtile_ext,
    metric_root,
    open_tile_writer,
    storage_format,
)
from climate.tiles.layout import GridSpec, grid_from_id, tile_counts  # noqa: E402
from climate.tiles.spec import read_tile_array  # noqa: E402


def _tiled_metrics(manifest: dict[str, dict]) -> dict[str, dict]:
    out = {}
    for metric_id, spec in manifest.items():
        if metric_id == "version" or not isinstance(spec, dict):
            continue
        storage = spec.get("storage") or {}
        if not storage.get("tiled", True) or spec.get("materialize") not in (
            None,
            "on_packager",
        ):
            continue
        out[metric_id] = spec
    return out


def _tolerance(encoding: zarr_tiles.Encoding, values: np.ndarray) -> np.ndarray | float:
    if encoding.is_float:
        return 0.0
    # half a step, plus float32 rounding of the decoded value
    return encoding.scale / 2 + np.abs(values) * 2e-7 + 1e-7


def _convert_tile(args) -> dict:
    (src_tile, dst_series, grid, metric_id, ntime, storage, time_axis, tr, tc) = args
    _hdr, src = read_tile_array(src_tile)
    writer = open_tile_writer(
        dst_series,
        grid,
        metric_id,
        ntime=ntime,
        dtype=np.dtype("float32"),
        storage=storage,
        time_axis=time_axis,
        resume=False,
    )
    writer.write(tr, tc, src, label=f"{metric_id} r{tr} c{tc}")
    got = zarr_tiles.read_tile(
        metric_root(dst_series, grid, metric_id), tr, tc, tile_size=grid.tile_size
    )
    src = np.asarray(src, dtype=np.float64)
    nan_src, nan_got = np.isnan(src), np.isnan(got)
    both = ~nan_src & ~nan_got
    err = np.abs(got[both] - src[both])
    over = int((err > _tolerance(writer.encoding, src[both])).sum()) if err.size else 0
    return {
        "nan_mismatch": int((nan_src != nan_got).sum()),
        "over_tolerance": over,
        "max_err": float(err.max()) if err.size else 0.0,
        "sum_err": float(err.sum()),
        "n": int(err.size),
    }


def _copy_tree_except(src: Path, dst: Path, skip: set[str]) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.name in skip:
            continue
        if item.is_dir():
            shutil.copytree(item, dst / item.name, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dst / item.name)


def _dir_bytes(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def convert_metric(
    metric_id: str,
    spec: dict,
    src_series: Path,
    dst_series: Path,
    workers: int,
) -> dict:
    storage = spec.get("storage") or {}
    grid: GridSpec = grid_from_id(
        str(spec["grid_id"]), tile_size=int(storage.get("tile_size", 64))
    )
    src_root = metric_root(src_series, grid, metric_id)
    dst_root = metric_root(dst_series, grid, metric_id)
    zname = f"z{grid.tile_size}"
    if not src_root.is_dir():
        return {"metric": metric_id, "status": "missing in source"}
    if storage_format(storage) != "zarr":
        _copy_tree_except(src_root, dst_root, skip=set())
        return {"metric": metric_id, "status": "copied (clmtile)"}

    _copy_tree_except(src_root, dst_root, skip={zname, zarr_tiles.ZARR_DIRNAME})
    ext = clmtile_ext(storage)
    ntr, ntc = tile_counts(grid)
    tiles = [
        (tr, tc, src_root / zname / f"r{tr:03d}_c{tc:03d}{ext}")
        for tr in range(ntr)
        for tc in range(ntc)
    ]
    tiles = [t for t in tiles if t[2].exists()]
    if not tiles:
        return {"metric": metric_id, "status": "no tiles in source"}
    hdr, _ = read_tile_array(tiles[0][2])
    ntime = int(hdr.nyears)
    time_axis = spec.get("time_axis")

    t0 = time.monotonic()
    # Create the array once, fresh, before the workers open it.
    shutil.rmtree(zarr_tiles.zarr_dir(dst_root), ignore_errors=True)
    open_tile_writer(
        dst_series,
        grid,
        metric_id,
        ntime=ntime,
        dtype=np.dtype("float32"),
        storage=storage,
        time_axis=time_axis,
        resume=False,
    )
    jobs = [
        (p, dst_series, grid, metric_id, ntime, storage, time_axis, tr, tc)
        for tr, tc, p in tiles
    ]
    with ProcessPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(_convert_tile, jobs, chunksize=4))
    n = sum(r["n"] for r in results)
    src_bytes = sum(p.stat().st_size for _, _, p in tiles)
    dst_bytes = _dir_bytes(zarr_tiles.zarr_dir(dst_root))
    return {
        "metric": metric_id,
        "status": "converted",
        "encoding": storage.get("encoding") or {"dtype": "float32"},
        "ntime": ntime,
        "tiles": len(tiles),
        "src_bytes": src_bytes,
        "dst_bytes": dst_bytes,
        "nan_mismatch": sum(r["nan_mismatch"] for r in results),
        "over_tolerance": sum(r["over_tolerance"] for r in results),
        "max_err": max(r["max_err"] for r in results),
        "mean_err": (sum(r["sum_err"] for r in results) / n) if n else 0.0,
        "seconds": round(time.monotonic() - t0, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--src", type=Path, required=True, help="source release root (read-only)"
    )
    ap.add_argument("--dst", type=Path, required=True, help="destination release root")
    ap.add_argument(
        "--metrics-path",
        type=Path,
        default=None,
        help="registry metrics.json (default: repo)",
    )
    ap.add_argument(
        "--metric", action="append", default=[], help="convert only these (repeatable)"
    )
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument(
        "--report", type=Path, default=None, help="write the per-metric report as JSON"
    )
    args = ap.parse_args()

    src, dst = args.src.resolve(), args.dst.resolve()
    if src == dst:
        raise SystemExit(
            "--src and --dst must differ: the source release is never modified"
        )
    manifest = (
        load_metrics(path=args.metrics_path, validate=True)
        if args.metrics_path
        else load_metrics(validate=True)
    )
    metrics = _tiled_metrics(manifest)
    if args.metric:
        unknown = set(args.metric) - set(metrics)
        if unknown:
            raise SystemExit(f"not tiled metrics in the registry: {sorted(unknown)}")
        metrics = {k: v for k, v in metrics.items() if k in args.metric}

    report = []
    failed = []
    for metric_id, spec in metrics.items():
        r = convert_metric(
            metric_id, spec, src / "series", dst / "series", args.workers
        )
        report.append(r)
        if r["status"] != "converted":
            print(f"{metric_id:55s} {r['status']}")
            continue
        ok = r["nan_mismatch"] == 0 and r["over_tolerance"] == 0
        if not ok:
            failed.append(metric_id)
        print(
            f"{metric_id:55s} {r['src_bytes'] / 1e6:9.1f} MB -> {r['dst_bytes'] / 1e6:8.1f} MB "
            f"(x{r['dst_bytes'] / max(r['src_bytes'], 1):.3f})  max err {r['max_err']:.4g}  "
            f"{r['seconds']:6.1f}s  {'OK' if ok else 'FAILED'}"
            + (
                ""
                if ok
                else f" nan_mismatch={r['nan_mismatch']} over_tolerance={r['over_tolerance']}"
            ),
            flush=True,
        )

    if not args.metric:
        for name in ("maps", "aux"):
            if (src / name).is_dir():
                shutil.copytree(src / name, dst / name, dirs_exist_ok=True)

    conv = [r for r in report if r["status"] == "converted"]
    if conv:
        s, d = sum(r["src_bytes"] for r in conv), sum(r["dst_bytes"] for r in conv)
        print(
            f"\nconverted {len(conv)} metric(s): {s / 1e9:.2f} GB -> {d / 1e9:.2f} GB"
        )
    if args.report:
        args.report.write_text(json.dumps(report, indent=1))
    if failed:
        print(f"FAILED verification: {failed}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
