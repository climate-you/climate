#!/usr/bin/env python
from __future__ import annotations

import argparse
from pathlib import Path

from climate.packager.registry import TileRange, package_registry
from climate.registry.metrics import DEFAULT_METRICS_PATH, DEFAULT_SCHEMA_PATH
from climate.registry.maps import DEFAULT_MAPS_PATH, DEFAULT_MAPS_SCHEMA_PATH
from climate.registry.panels import DEFAULT_PANELS_PATH, DEFAULT_PANELS_SCHEMA_PATH


def _parse_ids(ids_csv: str | None, ids_list: list[str]) -> list[str] | None:
    ids: list[str] = []
    if ids_csv:
        ids.extend([m.strip() for m in ids_csv.split(",") if m.strip()])
    ids.extend(ids_list)
    return ids or None


def _parse_tile_range(args: argparse.Namespace) -> TileRange | None:
    if args.all:
        if any(v is not None for v in (args.tile_r0, args.tile_r1, args.tile_c0, args.tile_c1)):
            raise SystemExit("Do not combine --all with --tile-r0/--tile-r1/--tile-c0/--tile-c1.")
        return None
    if any(v is not None for v in (args.tile_r0, args.tile_r1, args.tile_c0, args.tile_c1)):
        if None in (args.tile_r0, args.tile_r1, args.tile_c0, args.tile_c1):
            raise SystemExit(
                "When using --tile-r0/--tile-r1/--tile-c0/--tile-c1, you must provide all four."
            )
        return TileRange(
            int(args.tile_r0), int(args.tile_r1), int(args.tile_c0), int(args.tile_c1)
        )
    raise SystemExit("Provide --all or all of --tile-r0/--tile-r1/--tile-c0/--tile-c1.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Registry-driven packager")
    ap.add_argument("--release", type=str, default="dev")
    ap.add_argument(
        "--out-root",
        type=Path,
        default=None,
        help="Output series root (default: data/releases/<release>/series)",
    )
    ap.add_argument("--metrics", type=str, default=None, help="Comma list of metric ids")
    ap.add_argument("--metric", action="append", default=[], help="Metric id (repeatable)")
    ap.add_argument("--metrics-path", type=Path, default=DEFAULT_METRICS_PATH)
    ap.add_argument("--schema-path", type=Path, default=DEFAULT_SCHEMA_PATH)
    ap.add_argument("--datasets-path", type=Path, default=None)
    ap.add_argument("--maps-path", type=Path, default=DEFAULT_MAPS_PATH)
    ap.add_argument("--maps-schema-path", type=Path, default=DEFAULT_MAPS_SCHEMA_PATH)
    ap.add_argument("--panels-path", type=Path, default=DEFAULT_PANELS_PATH)
    ap.add_argument("--panels-schema-path", type=Path, default=DEFAULT_PANELS_SCHEMA_PATH)
    ap.add_argument(
        "--maps-out-root",
        type=Path,
        default=None,
        help="Output maps root (default: data/releases/<release>/maps)",
    )
    ap.add_argument("--maps", type=str, default=None, help="Comma list of map ids")
    ap.add_argument("--map", action="append", default=[], help="Map id (repeatable)")
    ap.add_argument(
        "--all-maps",
        action="store_true",
        help="Select all maps from registry/maps.json (equivalent to listing every --map).",
    )
    ap.add_argument("--skip-maps", action="store_true")

    ap.add_argument("--start-year", type=int, default=None)
    ap.add_argument("--end-year", type=int, default=None)
    ap.add_argument("--cache-dir", type=Path, default=Path("data/cache"))

    ap.add_argument("--batch-tiles", type=int, default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--tile-r0", type=int)
    ap.add_argument("--tile-r1", type=int)
    ap.add_argument("--tile-c0", type=int)
    ap.add_argument("--tile-c1", type=int)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--overwrite-download", action="store_true")
    ap.add_argument("--max-batches", type=int, default=None)
    ap.add_argument("--max-requests", type=int, default=None)
    ap.add_argument("--dask", action="store_true")
    ap.add_argument("--dask-chunk-lat", type=int, default=16)
    ap.add_argument("--dask-chunk-lon", type=int, default=16)
    ap.add_argument("--agg-debug", action="store_true")
    ap.add_argument("--pipeline", action="store_true")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--summary-interval", type=int, default=30)
    ap.add_argument("--download-only", action="store_true")
    ap.add_argument("--debug", action="store_true")

    args = ap.parse_args()

    out_root = args.out_root
    if out_root is None:
        out_root = Path("data/releases") / args.release / "series"

    metric_ids = _parse_ids(args.metrics, args.metric)
    map_ids = _parse_ids(args.maps, args.map)
    if args.all_maps and map_ids:
        raise SystemExit("Do not combine --all-maps with --maps/--map.")
    if args.all_maps:
        map_ids = None
    tile_range = _parse_tile_range(args)

    package_registry(
        out_root=out_root,
        release=args.release,
        metrics_path=args.metrics_path,
        schema_path=args.schema_path,
        datasets_path=args.datasets_path,
        cache_dir=args.cache_dir,
        start_year=args.start_year,
        end_year=args.end_year,
        metric_ids=metric_ids,
        tile_range=tile_range,
        batch_tiles=args.batch_tiles,
        resume=args.resume,
        overwrite_download=args.overwrite_download,
        debug=args.debug,
        max_batches=args.max_batches,
        max_requests=args.max_requests,
        dask_enabled=args.dask,
        dask_chunk_lat=args.dask_chunk_lat,
        dask_chunk_lon=args.dask_chunk_lon,
        agg_debug=args.agg_debug,
        pipeline=args.pipeline,
        workers=args.workers,
        summary_interval_s=args.summary_interval,
        download_only=args.download_only,
        maps_path=args.maps_path,
        maps_schema_path=args.maps_schema_path,
        panels_path=args.panels_path,
        panels_schema_path=args.panels_schema_path,
        maps_out_root=args.maps_out_root,
        map_ids=map_ids,
        all_maps=args.all_maps,
        skip_maps=args.skip_maps,
    )


if __name__ == "__main__":
    main()
