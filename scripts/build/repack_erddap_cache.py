#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
import time
import importlib.util

import xarray as xr


def _pick_engine() -> str:
    if importlib.util.find_spec("netCDF4") is not None:
        return "netcdf4"
    if importlib.util.find_spec("h5netcdf") is not None:
        return "h5netcdf"
    raise RuntimeError(
        "No NetCDF4-capable backend found. Install netCDF4 or h5netcdf."
    )


def _iter_nc_files(root: Path) -> list[Path]:
    return sorted(
        p
        for p in root.rglob("*.nc")
        if p.is_file() and not p.name.endswith(".tmp")
    )


def _is_old_enough(path: Path, *, min_age_s: int) -> bool:
    age = time.time() - path.stat().st_mtime
    return age >= float(min_age_s)


def _encoding_for_dataset(ds: xr.Dataset, *, level: int) -> dict[str, dict[str, object]]:
    enc: dict[str, dict[str, object]] = {}
    for name, var in ds.data_vars.items():
        if var.dtype.kind in {"f", "i", "u"}:
            enc[name] = {
                "zlib": True,
                "complevel": int(level),
                "shuffle": True,
            }
    return enc


def _repack_one(
    path: Path,
    *,
    engine: str,
    level: int,
    keep_larger: bool,
) -> tuple[bool, int, int]:
    before = int(path.stat().st_size)
    tmp = path.with_suffix(path.suffix + ".repack.tmp")
    if tmp.exists():
        tmp.unlink()

    with xr.open_dataset(path) as ds:
        encoding = _encoding_for_dataset(ds, level=level)
        ds.to_netcdf(
            tmp,
            mode="w",
            engine=engine,
            format="NETCDF4",
            encoding=encoding,
        )

    after = int(tmp.stat().st_size)
    if keep_larger and after >= before:
        tmp.unlink(missing_ok=True)
        return (False, before, after)

    os.replace(tmp, path)
    return (True, before, after)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Repack ERDDAP NetCDF cache files with internal compression."
    )
    ap.add_argument(
        "--cache-root",
        type=Path,
        default=Path("data/cache/erddap"),
        help='ERDDAP cache root (default: "data/cache/erddap").',
    )
    ap.add_argument(
        "--dataset-key",
        type=str,
        default=None,
        help="Optional dataset subfolder (e.g. crw_dhw_daily).",
    )
    ap.add_argument(
        "--level",
        type=int,
        default=4,
        help="zlib compression level 1..9 (default: 4).",
    )
    ap.add_argument(
        "--min-age-sec",
        type=int,
        default=300,
        help="Skip very recent files to avoid active writes (default: 300s).",
    )
    ap.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Optional cap on number of files to repack.",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="List candidate files without rewriting.",
    )
    ap.add_argument(
        "--replace-larger",
        action="store_true",
        help="Replace file even if repacked output is larger.",
    )
    args = ap.parse_args()

    root = args.cache_root
    if args.dataset_key:
        root = root / args.dataset_key
    if not root.exists():
        raise SystemExit(f"Cache root does not exist: {root}")

    files = [p for p in _iter_nc_files(root) if _is_old_enough(p, min_age_s=args.min_age_sec)]
    if args.max_files is not None:
        files = files[: int(args.max_files)]
    if not files:
        print("[repack] no eligible .nc files found")
        return

    if args.dry_run:
        total = sum(int(p.stat().st_size) for p in files)
        print(f"[repack] dry-run: {len(files)} file(s), total={total/1024/1024:.1f} MB")
        for p in files[:20]:
            print(f"  - {p}")
        return

    engine = _pick_engine()
    level = max(1, min(9, int(args.level)))
    keep_larger = not bool(args.replace_larger)

    changed = 0
    skipped_larger = 0
    failed = 0
    in_bytes = 0
    out_bytes = 0

    for idx, path in enumerate(files, start=1):
        try:
            replaced, before, after = _repack_one(
                path,
                engine=engine,
                level=level,
                keep_larger=keep_larger,
            )
            in_bytes += before
            out_bytes += after if replaced else before
            if replaced:
                changed += 1
                print(
                    f"[repack] {idx}/{len(files)} repacked {path.name} "
                    f"{before/1024/1024:.1f}MB -> {after/1024/1024:.1f}MB"
                )
            else:
                skipped_larger += 1
                print(
                    f"[repack] {idx}/{len(files)} kept original (larger/equal): "
                    f"{path.name} {before/1024/1024:.1f}MB -> {after/1024/1024:.1f}MB"
                )
        except Exception as exc:
            failed += 1
            print(f"[repack] {idx}/{len(files)} failed {path}: {exc}")

    saved = in_bytes - out_bytes
    print(
        f"[repack] done files={len(files)} repacked={changed} skipped={skipped_larger} "
        f"failed={failed} saved={saved/1024/1024:.1f}MB"
    )


if __name__ == "__main__":
    main()
