#!/usr/bin/env python
from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path


MONTHLY_RE = re.compile(
    r"^(era5_monthly_.+_r\d{3}-\d{3}_c\d{3}-\d{3})_\d{4}-\d{4}\.nc$"
)
DAILY_RE = re.compile(
    r"^(era5_daily_.+_r\d{3}-\d{3}_c\d{3}-\d{3})_\d{4}-\d{4}_m\d{2}-\d{2}\.nc$"
)


def _move_file(path: Path, dry_run: bool) -> bool:
    m = MONTHLY_RE.match(path.name) or DAILY_RE.match(path.name)
    if not m:
        return False
    folder_name = m.group(1)
    target_dir = path.parent / folder_name
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / path.name
    if target_path.exists():
        return True
    if dry_run:
        print(f"[dry-run] {path} -> {target_path}")
        return True
    shutil.move(str(path), str(target_path))
    print(f"Moved: {path} -> {target_path}")
    return True


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Move CDS cache files into per-batch subfolders."
    )
    ap.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("data/cache/cds"),
        help="CDS cache directory",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cache_dir = args.cache_dir
    if not cache_dir.exists():
        raise SystemExit(f"Cache dir not found: {cache_dir}")

    moved = 0
    for path in cache_dir.iterdir():
        if path.is_file():
            if path.name.startswith("."):
                continue
            if _move_file(path, args.dry_run):
                moved += 1

    print(f"Done. Files moved: {moved}")


if __name__ == "__main__":
    main()
