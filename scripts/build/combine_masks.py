#!/usr/bin/env python3
"""
Combine mask NPZ files with a logical operation.

Accepted NPZ format:
  - data: 2D array (0/1, bool, int, or float where finite+nonzero means True)
  - deg, lat_max, lon_min: scalar metadata (required)
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


def _load_mask(path: Path) -> tuple[np.ndarray, dict[str, float]]:
    with np.load(path, allow_pickle=False) as npz:
        if "data" not in npz:
            raise ValueError(f"{path}: missing 'data' array")
        data = np.asarray(npz["data"])
        if data.ndim != 2:
            raise ValueError(f"{path}: expected 2D mask data, got shape={data.shape}")

        meta: dict[str, float] = {}
        for k in ("deg", "lat_max", "lon_min"):
            if k not in npz:
                raise ValueError(f"{path}: missing '{k}' metadata")
            meta[k] = float(np.asarray(npz[k]).reshape(()))

    if data.dtype == np.bool_:
        mask = data.astype(bool, copy=False)
    elif np.issubdtype(data.dtype, np.floating):
        mask = np.isfinite(data) & (data != 0.0)
    else:
        mask = data != 0
    return mask, meta


def _validate_compatible(
    left_path: Path,
    left_mask: np.ndarray,
    left_meta: dict[str, float],
    right_path: Path,
    right_mask: np.ndarray,
    right_meta: dict[str, float],
) -> None:
    if left_mask.shape != right_mask.shape:
        raise ValueError(
            f"Mask shape mismatch: {left_path}={left_mask.shape}, "
            f"{right_path}={right_mask.shape}"
        )
    for k in ("deg", "lat_max", "lon_min"):
        if not np.isclose(left_meta[k], right_meta[k], atol=1e-9):
            raise ValueError(
                f"Mask metadata mismatch '{k}': "
                f"{left_path}={left_meta[k]}, {right_path}={right_meta[k]}"
            )


def _format_pct(valid: int, total: int) -> str:
    return f"{(100.0 * valid / float(total)):.5f}%"


def main() -> None:
    ap = argparse.ArgumentParser(description="Combine mask NPZ files.")
    ap.add_argument(
        "--input",
        action="append",
        default=[],
        help="Input mask NPZ path (repeatable; use this for 2+ masks).",
    )
    ap.add_argument(
        "--mode",
        type=str,
        default="and",
        choices=["and", "or"],
        help='Combine mode: "and" or "or" (default: and).',
    )
    ap.add_argument("--output", type=Path, required=True, help="Output NPZ path.")
    args = ap.parse_args()

    input_paths: list[Path] = [Path(p) for p in args.input]
    if len(input_paths) < 2:
        raise SystemExit("Provide at least two masks via repeated --input.")

    masks: list[np.ndarray] = []
    metas: list[dict[str, float]] = []
    for p in input_paths:
        mask, meta = _load_mask(p)
        masks.append(mask)
        metas.append(meta)

    for i in range(1, len(masks)):
        _validate_compatible(
            input_paths[0],
            masks[0],
            metas[0],
            input_paths[i],
            masks[i],
            metas[i],
        )

    total = int(masks[0].size)
    print("[stats] input coverages:")
    for p, m in zip(input_paths, masks):
        v = int(np.count_nonzero(m))
        print(f"[stats] - {p}: valid={v}/{total} ({_format_pct(v, total)})")

    all_and = masks[0].copy()
    all_or = masks[0].copy()
    for m in masks[1:]:
        all_and = np.logical_and(all_and, m)
        all_or = np.logical_or(all_or, m)

    and_valid = int(np.count_nonzero(all_and))
    or_valid = int(np.count_nonzero(all_or))
    print(f"[stats] intersection (AND): {and_valid}/{total} ({_format_pct(and_valid, total)})")
    print(f"[stats] union (OR): {or_valid}/{total} ({_format_pct(or_valid, total)})")

    out_mask = all_and if args.mode == "and" else all_or

    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.output,
        data=out_mask.astype(np.uint8, copy=False),
        deg=np.float64(metas[0]["deg"]),
        lat_max=np.float64(metas[0]["lat_max"]),
        lon_min=np.float64(metas[0]["lon_min"]),
    )

    valid = int(np.count_nonzero(out_mask))
    print(
        f"[ok] wrote combined mask: {args.output} "
        f"shape={out_mask.shape} valid={valid}/{total} ({(valid/total)*100:.5f}%) "
        f"mode={args.mode}"
    )


if __name__ == "__main__":
    main()
