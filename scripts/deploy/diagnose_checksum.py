#!/usr/bin/env python
"""
Diagnose a checksum mismatch for a single metric between local dev and prod.

Prints:
  - Local hash + file list
  - Prod stored hash (from artifact manifest.json)
  - Prod computed hash (by hashing files on the server via SSH)
  - Diff of file lists

Usage:
  python scripts/deploy/diagnose_checksum.py \\
    --remote deploy@116.203.92.158 \\
    --remote-releases-root /opt/climate/data/releases \\
    --metric t2m_yearly_mean_c
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
import sys
from pathlib import Path

_DEFAULT_DEV_ROOT = Path("data/releases/dev")


# ---------------------------------------------------------------------------
# Helpers (copied from publish_release.py to stay self-contained)
# ---------------------------------------------------------------------------

def _ssh_read(remote: str, path: str) -> str:
    result = subprocess.run(
        ["ssh", remote, f"cat {shlex.quote(path)}"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise FileNotFoundError(f"{remote}:{path}: {result.stderr.strip()}")
    return result.stdout


def _ssh_run_capture(remote: str, cmd: str) -> str:
    result = subprocess.run(
        ["ssh", remote, cmd],
        capture_output=True, text=True, check=False,
    )
    return result.stdout


def _hash_files(files: list[tuple[str, Path]]) -> str:
    h = hashlib.sha256()
    for rel, path in sorted(files):
        h.update(rel.encode("utf-8"))
        h.update(b"\x00")
        h.update(path.read_bytes())
    return h.hexdigest()


def _metric_sha256_local(dev_series_root: Path, metric_id: str) -> tuple[str, list[str]]:
    """Returns (sha256, sorted list of rel paths hashed)."""
    files: list[tuple[str, Path]] = []
    for grid_dir in sorted(dev_series_root.iterdir()):
        if not grid_dir.is_dir():
            continue
        metric_dir = grid_dir / metric_id
        if not metric_dir.is_dir():
            continue
        for p in sorted(metric_dir.rglob("*")):
            if p.is_file() and not p.name.startswith("."):
                files.append((p.relative_to(metric_dir).as_posix(), p))
    sha = _hash_files(files)
    return sha, sorted(rel for rel, _ in files)


# ---------------------------------------------------------------------------
# Remote hash computation (Python one-liner sent over SSH)
# ---------------------------------------------------------------------------

_REMOTE_HASH_SCRIPT = r"""
import hashlib, json, sys
from pathlib import Path

artifact_dir = Path(sys.argv[1])
files = []
for p in sorted(artifact_dir.rglob("*")):
    if p.is_file() and not p.name.startswith("."):
        files.append((p.relative_to(artifact_dir).as_posix(), p))
h = hashlib.sha256()
for rel, path in sorted(files):
    h.update(rel.encode("utf-8"))
    h.update(b"\x00")
    h.update(path.read_bytes())
print(json.dumps({"sha256": h.hexdigest(), "files": [r for r, _ in sorted(files)]}))
"""


def _compute_remote_hash(remote: str, artifact_dir: str) -> tuple[str, list[str]]:
    # Send the script inline via python3 -c
    escaped = _REMOTE_HASH_SCRIPT.replace("\\", "\\\\").replace("'", "'\\''").replace("\n", "\n")
    cmd = f"python3 - {shlex.quote(artifact_dir)} << 'PYEOF'\n{_REMOTE_HASH_SCRIPT}\nPYEOF"
    result = subprocess.run(["ssh", remote, cmd], capture_output=True, text=True, check=False)
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(f"Remote hash failed:\n{result.stderr.strip()}")
    data = json.loads(result.stdout.strip())
    return data["sha256"], data["files"]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Diagnose metric checksum mismatch.")
    ap.add_argument("--remote", required=True)
    ap.add_argument("--remote-releases-root", required=True)
    ap.add_argument("--remote-artifacts-root", default=None)
    ap.add_argument("--metric", required=True)
    ap.add_argument("--dev-root", type=Path, default=_DEFAULT_DEV_ROOT)
    args = ap.parse_args()

    remote_artifacts_root = args.remote_artifacts_root or str(
        Path(args.remote_releases_root).parent / "artifacts"
    )
    dev_series_root = args.dev_root / "series"

    # --- Local ---
    print(f"[local] Computing hash for series/{args.metric} ...")
    if not dev_series_root.is_dir():
        print(f"ERROR: {dev_series_root} not found", file=sys.stderr)
        return 1
    local_sha, local_files = _metric_sha256_local(dev_series_root, args.metric)
    print(f"  hash : {local_sha}")
    print(f"  files: {len(local_files)}")

    # --- Prod stored hash ---
    print(f"\n[prod] Reading LATEST release manifest ...")
    latest = _ssh_read(args.remote, f"{args.remote_releases_root}/LATEST").strip()
    print(f"  LATEST: {latest}")
    manifest = json.loads(_ssh_read(args.remote, f"{args.remote_releases_root}/{latest}/manifest.json"))
    artifact_date = manifest.get("series", {}).get(args.metric)
    if not artifact_date:
        print(f"  ERROR: {args.metric} not in prod release manifest")
        return 1
    print(f"  artifact date: {artifact_date}")

    artifact_dir = f"{remote_artifacts_root}/series/{args.metric}/{artifact_date}"
    art_manifest = json.loads(_ssh_read(args.remote, f"{artifact_dir}/.artifact_manifest.json"))
    prod_stored_sha = art_manifest.get("tree_sha256", "(missing)")
    print(f"  stored hash: {prod_stored_sha}")

    # --- Prod computed hash ---
    print(f"\n[prod] Computing hash over files in {artifact_dir} ...")
    try:
        prod_computed_sha, prod_files = _compute_remote_hash(args.remote, artifact_dir)
        print(f"  computed hash: {prod_computed_sha}")
        print(f"  files: {len(prod_files)}")
    except Exception as e:
        print(f"  WARNING: could not compute remote hash: {e}")
        prod_computed_sha = None
        prod_files = []

    # --- Summary ---
    print("\n--- Summary ---")
    print(f"  local hash         : {local_sha}")
    print(f"  prod stored hash   : {prod_stored_sha}")
    if prod_computed_sha:
        print(f"  prod computed hash : {prod_computed_sha}")
        if prod_stored_sha != prod_computed_sha:
            print("  WARNING: prod stored hash != prod computed hash (manifest was written incorrectly!)")

    if local_sha == prod_stored_sha:
        print("\n  RESULT: hashes match — no real change (deploy script may have a comparison bug)")
    else:
        print("\n  RESULT: hashes differ")

    # --- File diff ---
    local_set = set(local_files)
    prod_set = set(prod_files)
    only_local = sorted(local_set - prod_set)
    only_prod = sorted(prod_set - local_set)
    if only_local or only_prod:
        print("\n--- File list diff ---")
        for f in only_local:
            print(f"  + (local only)  {f}")
        for f in only_prod:
            print(f"  - (prod only)   {f}")
    elif prod_files:
        print("\n  File lists are identical — difference is in file contents.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
