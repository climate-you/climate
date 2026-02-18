#!/usr/bin/env python
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def run(cmd: list[str]) -> int:
    result = subprocess.run(cmd)
    return int(result.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate registry manifests and cross-links."
    )
    parser.add_argument(
        "--registry-root",
        type=Path,
        default=Path("registry"),
        help='Registry directory containing metrics/maps/panels/datasets JSON (default: "registry").',
    )
    parser.add_argument(
        "--release",
        default=None,
        help='Validate release registry from "data/releases/<release>/registry".',
    )
    parser.add_argument(
        "--releases-root",
        type=Path,
        default=Path("data/releases"),
        help='Releases root used with --release (default: "data/releases").',
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    scripts_dir = root / "scripts" / "validate"
    registry_root = args.registry_root
    if args.release:
        registry_root = args.releases_root / args.release / "registry"
    if not registry_root.exists():
        print(f"Registry root does not exist: {registry_root}")
        return 1

    metrics = registry_root / "metrics.json"
    maps = registry_root / "maps.json"
    panels = registry_root / "panels.json"
    datasets = registry_root / "datasets.json"

    commands = [
        [
            "python",
            str(scripts_dir / "metrics.py"),
            "--metrics",
            str(metrics),
            "--datasets",
            str(datasets),
        ],
        [
            "python",
            str(scripts_dir / "maps.py"),
            "--maps",
            str(maps),
            "--metrics",
            str(metrics),
            "--datasets",
            str(datasets),
        ],
        [
            "python",
            str(scripts_dir / "panels.py"),
            "--panels",
            str(panels),
            "--maps",
            str(maps),
            "--metrics",
            str(metrics),
            "--datasets",
            str(datasets),
        ],
    ]

    for cmd in commands:
        code = run(cmd)
        if code != 0:
            return code

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
