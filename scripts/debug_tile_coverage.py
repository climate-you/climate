#!/usr/bin/env python3
"""
Tiny tile coverage checker.

Reads tiles directly from disk (no API), and reports how many cells in each tile
contain non-NaN data (for float tiles). This matches the current v0 convention
where "missing" is encoded as NaN for float metrics.

Example:
  python scripts/debug_tile_coverage.py --root data/releases/dev --metric t2m_yearly_mean_c
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import numpy as np

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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path("data/releases/dev"))
    ap.add_argument("--metric", type=str, required=True)
    ap.add_argument("--grid", type=str, default="global_0p25")
    ap.add_argument("--max-tiles", type=int, default=0, help="0 = no limit")
    ap.add_argument("--summary-only", action="store_true")
    args = ap.parse_args()

    # v0: only one grid spec used so far
    if args.grid == "global_0p25":
        grid = GridSpec.global_0p25(tile_size=64)
    else:
        raise SystemExit(
            f"Unsupported --grid {args.grid!r} (v0 supports 'global_0p25' only)"
        )

    zdir = args.root / "series" / grid.grid_id / args.metric / f"z{grid.tile_size}"
    if not zdir.exists():
        raise SystemExit(f"Tile directory not found: {zdir}")

    files = _iter_tile_files(zdir)
    if args.max_tiles and args.max_tiles > 0:
        files = files[: args.max_tiles]

    if not files:
        raise SystemExit(f"No tile files found in: {zdir}")

    total_tiles = 0

    # Container fill (includes padding cells)
    total_container_cells = 0
    total_container_nonempty = 0

    # Real-grid fill (excludes padding beyond nlat/nlon)
    total_real_cells = 0
    total_real_nonempty = 0

    for p in files:
        rc = _parse_tile_rc(p)
        if rc is None:
            continue
        tr, tc = rc

        hdr, arr = read_tile_array(p)

        # Container counts (full 64x64)
        nonempty_c, total_c = _count_nonempty_cells(hdr.nyears, arr)
        frac_c = 100.0 * (nonempty_c / total_c if total_c else 0.0)

        # Real-grid counts (exclude padded rows/cols at edges)
        valid_h, valid_w = _valid_hw(grid, tr, tc)
        nonempty_r, total_r = _count_nonempty_cells_window(
            hdr.nyears, arr, valid_h, valid_w
        )
        frac_r = 100.0 * (nonempty_r / total_r if total_r else 0.0)

        total_tiles += 1

        total_container_cells += total_c
        total_container_nonempty += nonempty_c

        total_real_cells += total_r
        total_real_nonempty += nonempty_r

        if not args.summary_only:
            print(
                f"tile r{tr:03d} c{tc:03d}  nyears={hdr.nyears:>3d}  "
                f"dtype={str(arr.dtype):>6s}  "
                f"container={nonempty_c:5d}/{total_c:5d}  ({frac_c:6.2f}%)  "
                f"real={nonempty_r:5d}/{total_r:5d}  ({frac_r:6.2f}%)  "
                f"{p.name}"
            )

    overall_c = 100.0 * (
        total_container_nonempty / total_container_cells
        if total_container_cells
        else 0.0
    )
    overall_r = 100.0 * (
        total_real_nonempty / total_real_cells if total_real_cells else 0.0
    )
    print(
        f"\nSUMMARY: tiles={total_tiles}  "
        f"container_nonempty={total_container_nonempty}/{total_container_cells}  ({overall_c:.2f}%)  "
        f"real_nonempty={total_real_nonempty}/{total_real_cells}  ({overall_r:.2f}%)"
    )


if __name__ == "__main__":
    main()
