#!/usr/bin/env python3
"""Build a coarse sparse-risk mask from a finer-resolution availability mask.

Default use-case:
- input:  global_0p05 DHW mask
- output: global_0p25 sparse-risk mask
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


def _load_mask(path: Path) -> tuple[np.ndarray, dict[str, float]]:
    with np.load(path, allow_pickle=False) as npz:
        if "data" not in npz:
            raise ValueError(f"{path}: missing 'data' key.")
        data = np.asarray(npz["data"])
        if data.ndim != 2:
            raise ValueError(f"{path}: expected 2D data, got {data.shape}.")
        for key in ("deg", "lat_max", "lon_min"):
            if key not in npz:
                raise ValueError(f"{path}: missing metadata key '{key}'.")
        meta = {
            "deg": float(np.asarray(npz["deg"]).reshape(())),
            "lat_max": float(np.asarray(npz["lat_max"]).reshape(())),
            "lon_min": float(np.asarray(npz["lon_min"]).reshape(())),
        }
    mask = data != 0
    return mask, meta


def build_sparse_risk_mask(
    *,
    source_mask_path: Path,
    output_path: Path,
    target_deg: float,
) -> None:
    source_mask, meta = _load_mask(source_mask_path)
    source_deg = float(meta["deg"])
    ratio = target_deg / source_deg
    ratio_rounded = int(round(ratio))
    if ratio_rounded <= 0 or abs(ratio - ratio_rounded) > 1e-9:
        raise ValueError(
            f"target_deg/source_deg must be an integer ratio, got "
            f"{target_deg}/{source_deg}={ratio}."
        )

    factor = ratio_rounded
    nlat, nlon = source_mask.shape
    coarse_rows = np.floor((np.arange(nlat, dtype=np.float64) + 0.5) / factor).astype(
        np.int64
    )
    coarse_cols = np.floor((np.arange(nlon, dtype=np.float64) + 0.5) / factor).astype(
        np.int64
    )
    nlat_coarse = int(coarse_rows.max()) + 1
    nlon_coarse = int(coarse_cols.max()) + 1
    coarse = np.zeros((nlat_coarse, nlon_coarse), dtype=bool)

    true_i, true_j = np.nonzero(source_mask)
    if true_i.size:
        coarse[coarse_rows[true_i], coarse_cols[true_j]] = True
    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output_path,
        data=coarse.astype(np.uint8, copy=False),
        deg=np.float64(target_deg),
        lat_max=np.float64(meta["lat_max"]),
        lon_min=np.float64(meta["lon_min"]),
    )

    valid = int(np.count_nonzero(coarse))
    total = int(coarse.size)
    print(
        f"[ok] wrote sparse-risk mask: {output_path} "
        f"shape={coarse.shape} valid={valid}/{total} ({(valid/total)*100:.5f}%) "
        f"deg={target_deg}"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Build sparse-risk mask at coarse resolution.")
    ap.add_argument(
        "--source-mask",
        type=Path,
        default=Path("data/masks/crw_dhw_daily_global_0p05_mask.npz"),
        help="Input fine-resolution mask NPZ.",
    )
    ap.add_argument(
        "--target-deg",
        type=float,
        default=0.25,
        help="Target coarse grid resolution in degrees (default: 0.25).",
    )
    ap.add_argument(
        "--output",
        type=Path,
        default=Path("data/masks/sparse_risk_global_0p25_mask.npz"),
        help="Output sparse-risk mask NPZ.",
    )
    args = ap.parse_args()

    build_sparse_risk_mask(
        source_mask_path=args.source_mask,
        output_path=args.output,
        target_deg=float(args.target_deg),
    )


if __name__ == "__main__":
    main()
