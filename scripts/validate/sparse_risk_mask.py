#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


def _load_mask(path: Path) -> tuple[np.ndarray, dict[str, float]]:
    with np.load(path, allow_pickle=False) as npz:
        if "data" not in npz:
            raise ValueError(f"{path}: missing 'data' key")
        data = np.asarray(npz["data"])
        if data.ndim != 2:
            raise ValueError(f"{path}: expected 2D mask, got {data.shape}")
        for key in ("deg", "lat_max", "lon_min"):
            if key not in npz:
                raise ValueError(f"{path}: missing '{key}'")
        meta = {
            "deg": float(np.asarray(npz["deg"]).reshape(())),
            "lat_max": float(np.asarray(npz["lat_max"]).reshape(())),
            "lon_min": float(np.asarray(npz["lon_min"]).reshape(())),
        }
    return data != 0, meta


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Validate release sparse-risk mask presence and accuracy."
    )
    ap.add_argument("--release", required=True, help="Release id to validate.")
    ap.add_argument(
        "--releases-root",
        type=Path,
        default=Path("data/releases"),
        help='Releases root (default: "data/releases").',
    )
    args = ap.parse_args()

    release_root = args.releases_root / args.release
    datasets_path = release_root / "registry" / "datasets.json"
    if not datasets_path.exists():
        print(f"Missing datasets registry: {datasets_path}")
        return 1

    datasets = json.loads(datasets_path.read_text(encoding="utf-8"))
    crw = datasets.get("crw_dhw_daily")
    if not isinstance(crw, dict):
        print(
            f"OK: release '{args.release}' has no 'crw_dhw_daily' dataset; sparse-risk mask check skipped."
        )
        return 0

    source = crw.get("source", {})
    if not isinstance(source, dict):
        print("Dataset 'crw_dhw_daily' has invalid source definition.")
        return 1
    fine_mask_raw = source.get("mask_file")
    if not isinstance(fine_mask_raw, str) or not fine_mask_raw:
        print("Dataset 'crw_dhw_daily' source.mask_file is missing.")
        return 1
    fine_mask_path = Path(fine_mask_raw)
    if not fine_mask_path.exists():
        print(f"Missing fine mask file from registry: {fine_mask_path}")
        return 1

    sparse_path = release_root / "aux" / "sparse_risk_global_0p25_mask.npz"
    if not sparse_path.exists():
        print(f"Missing sparse-risk mask file: {sparse_path}")
        return 1

    fine, fine_meta = _load_mask(fine_mask_path)
    coarse, coarse_meta = _load_mask(sparse_path)

    ratio = coarse_meta["deg"] / fine_meta["deg"]
    factor = int(round(ratio))
    if factor <= 0 or abs(ratio - factor) > 1e-9:
        print(
            f"Invalid degree ratio coarse/fine={coarse_meta['deg']}/{fine_meta['deg']}={ratio}"
        )
        return 1
    nlat, nlon = fine.shape
    coarse_rows = np.floor((np.arange(nlat, dtype=np.float64) + 0.5) / factor).astype(
        np.int64
    )
    coarse_cols = np.floor((np.arange(nlon, dtype=np.float64) + 0.5) / factor).astype(
        np.int64
    )
    expected = np.zeros((int(coarse_rows.max()) + 1, int(coarse_cols.max()) + 1), dtype=bool)
    true_i, true_j = np.nonzero(fine)
    if true_i.size:
        expected[coarse_rows[true_i], coarse_cols[true_j]] = True

    if coarse.shape != expected.shape:
        print(
            f"Sparse-risk mask shape mismatch: got {coarse.shape}, expected {expected.shape}"
        )
        return 1
    if abs(coarse_meta["lat_max"] - fine_meta["lat_max"]) > 1e-9:
        print(
            f"lat_max mismatch: coarse={coarse_meta['lat_max']} fine={fine_meta['lat_max']}"
        )
        return 1
    if abs(coarse_meta["lon_min"] - fine_meta["lon_min"]) > 1e-9:
        print(
            f"lon_min mismatch: coarse={coarse_meta['lon_min']} fine={fine_meta['lon_min']}"
        )
        return 1

    mismatches = np.argwhere(coarse != expected)
    if mismatches.size:
        print(
            f"Sparse-risk mask mismatch: {mismatches.shape[0]} cells differ "
            f"(sample i_lat,i_lon={mismatches[0].tolist()})"
        )
        return 1

    print(
        f"OK: {sparse_path} matches {fine_mask_path} "
        f"(factor={factor}, shape={coarse.shape})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
