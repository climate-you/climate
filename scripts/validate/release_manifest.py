#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _validate_v1(
    payload: dict,
    release: str,
    release_root: Path,
    manifest_path: Path,
) -> int:
    """Validate a v1 manifest (no format_version key)."""
    required = ["release", "created_at_utc", "series_root", "maps_root", "registry"]
    missing = [k for k in required if k not in payload]
    if missing:
        print(f"Manifest missing keys: {', '.join(missing)}")
        return 1

    if payload["release"] != release:
        print(
            f"Manifest release mismatch: expected {release!r}, got {payload['release']!r}"
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

    print(f"OK (v1): {manifest_path}")
    return 0


def _validate_v2(
    payload: dict,
    release: str,
    release_root: Path,
    manifest_path: Path,
    artifacts_root: Path,
) -> int:
    """Validate a v2 manifest (format_version: 2)."""
    errors: list[str] = []

    if payload.get("release") != release:
        errors.append(
            f"Manifest release mismatch: expected {release!r}, got {payload.get('release')!r}"
        )

    # Validate registry pointers.
    registry = payload.get("registry")
    if not isinstance(registry, dict):
        errors.append("Manifest 'registry' field must be an object.")
    else:
        for filename in (
            "metrics.json",
            "datasets.json",
            "maps.json",
            "panels.json",
        ):
            rel = registry.get(filename)
            if not isinstance(rel, str) or not rel:
                errors.append(f"Manifest registry missing entry for {filename!r}")
                continue
            path = release_root / rel
            if not path.exists():
                errors.append(f"Registry file missing: {path}")

    # Validate series pointers.
    series = payload.get("series", {})
    if not isinstance(series, dict):
        errors.append("Manifest 'series' field must be an object.")
    else:
        for metric_id, artifact_date in series.items():
            if not isinstance(artifact_date, str) or not artifact_date:
                errors.append(f"series[{metric_id!r}] must be a non-empty string date.")
                continue
            artifact_dir = artifacts_root / "series" / metric_id / artifact_date
            if not artifact_dir.exists():
                errors.append(f"Series artifact dir missing: {artifact_dir}")
            else:
                manifest_file = artifact_dir / ".artifact_manifest.json"
                if not manifest_file.exists():
                    errors.append(
                        f"Series artifact manifest missing (build incomplete?): {manifest_file}"
                    )

    # Validate maps pointers.
    maps = payload.get("maps", {})
    if not isinstance(maps, dict):
        errors.append("Manifest 'maps' field must be an object.")
    else:
        for map_id, artifact_date in maps.items():
            if not isinstance(artifact_date, str) or not artifact_date:
                errors.append(f"maps[{map_id!r}] must be a non-empty string date.")
                continue
            artifact_dir = artifacts_root / "maps" / map_id / artifact_date
            if not artifact_dir.exists():
                errors.append(f"Map artifact dir missing: {artifact_dir}")
            else:
                manifest_file = artifact_dir / ".artifact_manifest.json"
                if not manifest_file.exists():
                    errors.append(
                        f"Map artifact manifest missing (build incomplete?): {manifest_file}"
                    )

    if errors:
        for e in errors:
            print(f"ERROR: {e}")
        return 1

    print(f"OK (v2): {manifest_path}")
    return 0


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
    parser.add_argument(
        "--artifacts-root",
        type=Path,
        default=None,
        help=(
            "Artifact store root for v2 releases "
            "(default: sibling of releases-root named 'artifacts')."
        ),
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

    format_version = int(payload.get("format_version", 1))

    if format_version >= 2:
        artifacts_root = args.artifacts_root
        if artifacts_root is None:
            artifacts_root = args.releases_root.parent / "artifacts"
        return _validate_v2(
            payload, args.release, release_root, manifest_path, artifacts_root
        )
    else:
        return _validate_v1(payload, args.release, release_root, manifest_path)


if __name__ == "__main__":
    raise SystemExit(main())
