from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


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
