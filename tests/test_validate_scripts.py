from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np


def test_validate_all_script() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = "."

    result = subprocess.run(
        [sys.executable, "scripts/validate/all.py"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (
        "validate/all.py failed\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def test_validate_suite_help() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "scripts/validate_suite.py", "--help"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "validate_suite.py --help failed\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def test_validate_all_help() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "scripts/validate/all.py", "--help"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "validate/all.py --help failed\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def test_validate_suite_returns_nonzero_on_failure(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    locations_csv = tmp_path / "locations.csv"
    index_csv = tmp_path / "locations.index.csv"
    locations_csv.write_text("geonameid,lat,lon\n1,48.85,2.35\n", encoding="utf-8")
    index_csv.write_text("geonameid,label,lat,lon,country_code\n1,Paris,48.85,2.35,FR\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/validate_suite.py",
            "--skip-registry",
            "--skip-tiles",
            "--skip-pytest",
            "--base-url",
            "http://127.0.0.1:9",
            "--locations-csv",
            str(locations_csv),
            "--index-csv",
            str(index_csv),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0, (
        "validate_suite.py should fail when a step fails\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def test_validate_sparse_risk_mask_skips_when_no_crw_dataset(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    release_root = tmp_path / "releases" / "demo"
    (release_root / "registry").mkdir(parents=True)
    (release_root / "registry" / "datasets.json").write_text(
        '{"version":"0.1","era5_daily_t2m":{"id":"era5_daily_t2m"}}\n',
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/validate/sparse_risk_mask.py",
            "--release",
            "demo",
            "--releases-root",
            str(tmp_path / "releases"),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "sparse_risk_mask.py should skip when crw_dhw_daily is absent\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def test_validate_sparse_risk_mask_checks_accuracy(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    release_root = tmp_path / "releases" / "demo"
    fine_mask_path = tmp_path / "masks" / "crw_demo_0p05.npz"
    sparse_mask_path = release_root / "aux" / "sparse_risk_global_0p25_mask.npz"
    (release_root / "registry").mkdir(parents=True, exist_ok=True)
    sparse_mask_path.parent.mkdir(parents=True, exist_ok=True)
    fine_mask_path.parent.mkdir(parents=True, exist_ok=True)

    fine = np.zeros((10, 10), dtype=np.uint8)
    fine[0, 0] = 1
    fine[7, 7] = 1
    np.savez_compressed(
        fine_mask_path,
        data=fine,
        deg=np.float64(0.05),
        lat_max=np.float64(90.0),
        lon_min=np.float64(-180.0),
    )
    sparse = (fine.reshape(2, 5, 2, 5).any(axis=(1, 3))).astype(np.uint8)
    np.savez_compressed(
        sparse_mask_path,
        data=sparse,
        deg=np.float64(0.25),
        lat_max=np.float64(90.0),
        lon_min=np.float64(-180.0),
    )

    (release_root / "registry" / "datasets.json").write_text(
        (
            '{\n'
            '  "version":"0.1",\n'
            '  "crw_dhw_daily":{"id":"crw_dhw_daily","source":{"mask_file":"'
            + str(fine_mask_path)
            + '"}}\n'
            '}\n'
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/validate/sparse_risk_mask.py",
            "--release",
            "demo",
            "--releases-root",
            str(tmp_path / "releases"),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "sparse_risk_mask.py should pass for matching masks\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
