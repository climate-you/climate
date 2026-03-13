#!/usr/bin/env python3
"""
Build final reef-domain mask with optional sea-only dilation and DHW availability constraint.

Formula:
  reef_seed = OR(reef_masks...)
  dil = reef_seed OR (dilate(reef_seed) AND water_mask)
  out = dil AND dhw_available_mask
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


def _load_mask(path: Path) -> tuple[np.ndarray, dict[str, float]]:
    with np.load(path, allow_pickle=False) as npz:
        if "data" not in npz:
            raise ValueError(f"{path}: missing 'data'")
        data = np.asarray(npz["data"])
        if data.ndim != 2:
            raise ValueError(f"{path}: expected 2D data, got shape={data.shape}")
        meta = {
            "deg": float(np.asarray(npz["deg"]).reshape(())),
            "lat_max": float(np.asarray(npz["lat_max"]).reshape(())),
            "lon_min": float(np.asarray(npz["lon_min"]).reshape(())),
        }
    if data.dtype == np.bool_:
        mask = data.astype(bool, copy=False)
    elif np.issubdtype(data.dtype, np.floating):
        mask = np.isfinite(data) & (data != 0.0)
    else:
        mask = data != 0
    return mask, meta


def _check_compatible(base_path: Path, base: np.ndarray, base_meta: dict[str, float], path: Path, arr: np.ndarray, meta: dict[str, float]) -> None:
    if base.shape != arr.shape:
        raise ValueError(f"Mask shape mismatch: {base_path}={base.shape}, {path}={arr.shape}")
    for k in ("deg", "lat_max", "lon_min"):
        if not np.isclose(base_meta[k], meta[k], atol=1e-9):
            raise ValueError(f"Mask metadata mismatch for {k}: {base_path}={base_meta[k]} vs {path}={meta[k]}")


def _pct(n: int, total: int) -> str:
    return f"{(100.0 * n / float(total)):.5f}%"


def main() -> None:
    ap = argparse.ArgumentParser(description="Build final reef-domain mask.")
    ap.add_argument(
        "--reef-mask",
        action="append",
        default=[],
        help="Input reef mask NPZ (repeatable, OR-combined).",
    )
    ap.add_argument("--water-mask", type=Path, required=True, help="Water mask NPZ (1=water).")
    ap.add_argument("--dhw-mask", type=Path, required=True, help="DHW availability mask NPZ.")
    ap.add_argument("--dilate-iterations", type=int, default=1, help="Sea-only dilation iterations (default: 1).")
    ap.add_argument("--output", type=Path, default=Path("data/masks/crw_dhw_daily_global_0p05_mask.npz"))
    args = ap.parse_args()

    reef_paths = [Path(p) for p in args.reef_mask]
    if not reef_paths:
        raise SystemExit("Provide at least one --reef-mask.")

    reef_seed, meta = _load_mask(reef_paths[0])
    for p in reef_paths[1:]:
        m, mm = _load_mask(p)
        _check_compatible(reef_paths[0], reef_seed, meta, p, m, mm)
        reef_seed = np.logical_or(reef_seed, m)

    water_mask, water_meta = _load_mask(args.water_mask)
    _check_compatible(reef_paths[0], reef_seed, meta, args.water_mask, water_mask, water_meta)

    dhw_mask, dhw_meta = _load_mask(args.dhw_mask)
    _check_compatible(reef_paths[0], reef_seed, meta, args.dhw_mask, dhw_mask, dhw_meta)

    total = int(reef_seed.size)
    print(f"[stats] reef_seed={int(np.count_nonzero(reef_seed))}/{total} ({_pct(int(np.count_nonzero(reef_seed)), total)})")
    print(f"[stats] water_mask={int(np.count_nonzero(water_mask))}/{total} ({_pct(int(np.count_nonzero(water_mask)), total)})")
    print(f"[stats] dhw_mask={int(np.count_nonzero(dhw_mask))}/{total} ({_pct(int(np.count_nonzero(dhw_mask)), total)})")

    if int(args.dilate_iterations) > 0:
        try:
            from scipy.ndimage import binary_dilation
        except Exception as exc:
            raise RuntimeError("scipy is required for dilation. Install with: pip install scipy") from exc
        # 8-neighbor connectivity to close diagonal coastal gaps.
        structure = np.ones((3, 3), dtype=bool)
        dilated = binary_dilation(
            reef_seed,
            structure=structure,
            iterations=int(args.dilate_iterations),
        )
        reef_domain = np.logical_or(reef_seed, np.logical_and(dilated, water_mask))
    else:
        reef_domain = reef_seed.copy()

    out = np.logical_and(reef_domain, dhw_mask)
    print(f"[stats] reef_domain={int(np.count_nonzero(reef_domain))}/{total} ({_pct(int(np.count_nonzero(reef_domain)), total)})")
    print(f"[stats] final_mask={int(np.count_nonzero(out))}/{total} ({_pct(int(np.count_nonzero(out)), total)})")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.output,
        data=out.astype(np.uint8, copy=False),
        deg=np.float64(meta["deg"]),
        lat_max=np.float64(meta["lat_max"]),
        lon_min=np.float64(meta["lon_min"]),
    )
    print(f"[ok] wrote final reef-domain mask: {args.output}")


if __name__ == "__main__":
    main()

