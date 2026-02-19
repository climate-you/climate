#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate data/releases/<release>/manifest.json integrity."
    )
    parser.add_argument("--release", required=True, help="Release id to validate.")
    parser.add_argument(
        "--releases-root",
        type=Path,
        default=Path("data/releases"),
        help='Releases root (default: "data/releases").',
    )
    args = parser.parse_args()

    release_root = args.releases_root / args.release
    manifest_path = release_root / "manifest.json"
    if not manifest_path.exists():
        print(f"Missing manifest: {manifest_path}")
        return 1

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON in {manifest_path}: {exc}")
        return 1

    required = ["release", "created_at_utc", "series_root", "maps_root", "registry"]
    missing = [k for k in required if k not in payload]
    if missing:
        print(f"Manifest missing keys: {', '.join(missing)}")
        return 1

    if payload["release"] != args.release:
        print(
            f"Manifest release mismatch: expected {args.release!r}, got {payload['release']!r}"
        )
        return 1

    series_root = release_root / str(payload["series_root"])
    maps_root = release_root / str(payload["maps_root"])
    if not series_root.exists():
        print(f"series_root path does not exist: {series_root}")
        return 1
    if not maps_root.exists():
        print(f"maps_root path does not exist: {maps_root}")
        return 1

    registry = payload["registry"]
    if not isinstance(registry, dict):
        print("Manifest registry field must be an object.")
        return 1

    for filename in (
        "metrics.json",
        "datasets.json",
        "maps.json",
        "layers.json",
        "panels.json",
    ):
        rel = registry.get(filename)
        if not isinstance(rel, str) or not rel:
            print(f"Manifest registry missing entry for {filename}")
            return 1
        path = release_root / rel
        if not path.exists():
            print(f"Manifest registry path does not exist for {filename}: {path}")
            return 1

    print(f"OK: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
