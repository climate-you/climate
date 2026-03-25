#!/usr/bin/env python
"""
Publish local dev release data to the production server's artifact store.

Computes checksums of all local dev metrics and maps, diffs them against the
current prod release, syncs only what has changed, and creates a new v2
release manifest on the server.

Workflow:
  1. [pre-flight]  Run validate_suite on the local dev release (registry,
                   tile coverage, unit tests).
  2. [discover]    Scan data/releases/dev/series/ and data/releases/dev/maps/.
  3. [checksum]    Compute tree_sha256 for each metric and map locally.
  4. [diff]        SSH to fetch the current prod release manifest and artifact
                   checksums. Categorise each as new, changed, unchanged, or
                   removed.
  5. [confirm]     Print the diff and prompt for confirmation.
  6. [sync]        Rsync changed/new artifacts to the server artifact store and
                   write per-artifact manifest.json.
  7. [release]     Write the new release manifest + registry on the server.
  8. [LATEST]      Optionally update the LATEST pointer.

Usage:
  python scripts/deploy/publish_release.py \\
    --remote deploy@host \\
    --remote-releases-root /opt/climate/source/data/releases \\
    --update-latest

Permissions:
  Files are rsync'd with --chmod a+rX by default (world-readable), so the
  climate service user can read artifacts synced by the deploy SSH user.
  Pass --rsync-chmod "" to disable, or use --remote-chown climate:climate
  to chown after each sync (requires passwordless sudo chown on the remote).
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

_DEFAULT_DEV_ROOT = Path("data/releases/dev")
_DEFAULT_REGISTRY = Path("registry")


# ---------------------------------------------------------------------------
# Shell helpers
# ---------------------------------------------------------------------------


def _run(cmd: list[str], *, dry_run: bool = False, check: bool = True) -> int:
    print(f"  $ {' '.join(shlex.quote(a) for a in cmd)}")
    if dry_run:
        return 0
    result = subprocess.run(cmd, check=False)
    if check and result.returncode != 0:
        print(f"ERROR: command failed (exit {result.returncode})", file=sys.stderr)
        raise SystemExit(result.returncode)
    return result.returncode


def _ssh_read(remote: str | None, path: str) -> str:
    if remote is None:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Cannot read {path}: file not found")
        return p.read_text(encoding="utf-8")
    result = subprocess.run(
        ["ssh", remote, f"cat {shlex.quote(path)}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise FileNotFoundError(f"Cannot read {remote}:{path}: {result.stderr.strip()}")
    return result.stdout


def _ssh_run(remote: str | None, cmd: str, *, dry_run: bool = False) -> None:
    if remote is None:
        _run(["sh", "-c", cmd], dry_run=dry_run)
    else:
        _run(["ssh", remote, cmd], dry_run=dry_run)


def _dst(remote: str | None, path: str) -> str:
    return f"{remote}:{path}" if remote else path


def _ssh_mkdir(remote: str | None, path: str, owner: str, *, dry_run: bool = False) -> None:
    """Create a remote directory via sudo and chown it to owner so it is writable."""
    _ssh_run(remote, f"sudo mkdir -p {shlex.quote(path)}", dry_run=dry_run)
    _ssh_run(remote, f"sudo chown {shlex.quote(owner)} {shlex.quote(path)}", dry_run=dry_run)


def _ssh_chown(remote: str | None, path: str, owner: str, *, recursive: bool = False, dry_run: bool = False) -> None:
    """Chown a remote path via sudo, optionally recursively."""
    flag = "-R " if recursive else ""
    _ssh_run(remote, f"sudo chown {flag}{shlex.quote(owner)} {shlex.quote(path)}", dry_run=dry_run)


def _rsync_dir(src: str, dst: str, *, dry_run: bool = False, chmod: str = "a+rX") -> None:
    if not src.endswith("/"):
        src += "/"
    cmd = ["rsync", "-av", "--progress", "--exclude=._*", "--exclude=.DS_Store"]
    if chmod:
        cmd += ["--chmod", chmod]
    cmd += [src, dst]
    _run(cmd, dry_run=dry_run)


def _rsync_file(src: str, dst: str, *, dry_run: bool = False, chmod: str = "a+rX") -> None:
    cmd = ["rsync", "-av"]
    if chmod:
        cmd += ["--chmod", chmod]
    cmd += [src, dst]
    _run(cmd, dry_run=dry_run)


def _write_remote_json(
    remote: str | None,
    remote_path: str,
    data: dict,
    *,
    dry_run: bool = False,
    chmod: str = "a+rX",
) -> None:
    content = json.dumps(data, indent=2, sort_keys=True) + "\n"
    if dry_run:
        print(f"  [write] {remote_path}")
        return
    if remote is None:
        Path(remote_path).write_text(content, encoding="utf-8")
    else:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write(content)
            tmp = f.name
        try:
            _rsync_file(tmp, f"{remote}:{remote_path}", chmod=chmod)
        finally:
            os.unlink(tmp)


# ---------------------------------------------------------------------------
# Checksum
# ---------------------------------------------------------------------------


def _hash_files(files: list[tuple[str, Path]]) -> str:
    """Compute sha256 over (rel_posix_path, file_bytes) pairs sorted by path."""
    h = hashlib.sha256()
    for rel, path in sorted(files):
        h.update(rel.encode("utf-8"))
        h.update(b"\x00")
        h.update(path.read_bytes())
    return h.hexdigest()


def _metric_sha256(dev_series_root: Path, metric_id: str) -> str:
    """Hash all tile files for metric_id across every grid_id in the dev series root.

    Relative paths are rooted at each metric_dir, producing paths like:
      z64/r000_c000.bin.zst
    This matches the flat artifact store layout (no grid_id prefix), so the
    same hash can be compared against the stored tree_sha256 on subsequent runs.
    """
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
    return _hash_files(files)


def _map_sha256(map_dir: Path) -> str:
    """Hash all data files for a map; relative paths rooted at the map dir."""
    files: list[tuple[str, Path]] = []
    for p in sorted(map_dir.rglob("*")):
        if p.is_file() and not p.name.startswith("."):
            files.append((p.relative_to(map_dir).as_posix(), p))
    return _hash_files(files)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _discover_metrics(dev_series_root: Path) -> dict[str, list[str]]:
    """Return {metric_id: [grid_id, ...]} for all metrics found in dev series root."""
    result: dict[str, list[str]] = {}
    if not dev_series_root.is_dir():
        return result
    for grid_dir in sorted(dev_series_root.iterdir()):
        if not grid_dir.is_dir():
            continue
        for metric_dir in sorted(grid_dir.iterdir()):
            if metric_dir.is_dir():
                result.setdefault(metric_dir.name, []).append(grid_dir.name)
    return result


def _discover_maps(dev_maps_root: Path) -> dict[str, Path]:
    """Return {map_id: map_dir} scanning the {grid_id}/{map_id} layout in dev maps root."""
    result: dict[str, Path] = {}
    if not dev_maps_root.is_dir():
        return result
    for grid_dir in sorted(dev_maps_root.iterdir()):
        if not grid_dir.is_dir():
            continue
        for map_dir in sorted(grid_dir.iterdir()):
            if map_dir.is_dir():
                result[map_dir.name] = map_dir
    return result


# ---------------------------------------------------------------------------
# Prod state
# ---------------------------------------------------------------------------


def _fetch_prod_state(
    remote: str | None, releases_root: str, artifacts_root: str
) -> dict | None:
    """Return prod state dict, or None if no LATEST release exists (fresh server)."""
    try:
        latest = _ssh_read(remote, f"{releases_root}/LATEST").strip()
    except FileNotFoundError:
        return None
    if not latest:
        return None

    try:
        manifest = json.loads(_ssh_read(remote, f"{releases_root}/{latest}/manifest.json"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"WARNING: could not read prod manifest for '{latest}': {exc}")
        return None

    series_checksums: dict[str, str | None] = {}
    for metric_id, date in manifest.get("series", {}).items():
        try:
            info = json.loads(
                _ssh_read(remote, f"{artifacts_root}/series/{metric_id}/{date}/.artifact_manifest.json")
            )
            series_checksums[metric_id] = info.get("tree_sha256")
        except (FileNotFoundError, json.JSONDecodeError):
            series_checksums[metric_id] = None

    maps_checksums: dict[str, str | None] = {}
    for map_id, date in manifest.get("maps", {}).items():
        try:
            info = json.loads(
                _ssh_read(remote, f"{artifacts_root}/maps/{map_id}/{date}/.artifact_manifest.json")
            )
            maps_checksums[map_id] = info.get("tree_sha256")
        except (FileNotFoundError, json.JSONDecodeError):
            maps_checksums[map_id] = None

    return {
        "release": latest,
        "manifest": manifest,
        "series_checksums": series_checksums,
        "maps_checksums": maps_checksums,
    }


# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------


def _run_validate_suite(repo_root: Path) -> bool:
    cmd = [
        sys.executable,
        "scripts/validate_suite.py",
        "--release", "dev",
        "--skip-smoke",
        "--skip-pytest",
        "--tile-summary-only",
    ]
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=repo_root, check=False)
    return result.returncode == 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Publish local dev release to the production artifact store.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument(
        "--remote",
        default=None,
        help=(
            "SSH remote (user@host). "
            "Omit to publish locally (useful for testing the v2 code path)."
        ),
    )
    ap.add_argument(
        "--remote-releases-root",
        default=None,
        help=(
            "Releases root on the target. "
            "Required when --remote is set. "
            "Defaults to data/releases when publishing locally."
        ),
    )
    ap.add_argument(
        "--remote-artifacts-root",
        default=None,
        help=(
            "Artifact store root on the target. "
            "Defaults to sibling of remote-releases-root named 'artifacts'."
        ),
    )
    ap.add_argument(
        "--release",
        default=None,
        help="New release id (default: today's date as YYYY_MM_DD).",
    )
    ap.add_argument(
        "--dev-root",
        type=Path,
        default=_DEFAULT_DEV_ROOT,
        help=f"Local dev release root (default: {_DEFAULT_DEV_ROOT}).",
    )
    ap.add_argument(
        "--registry",
        type=Path,
        default=_DEFAULT_REGISTRY,
        help=f"Local registry directory to copy into the release (default: {_DEFAULT_REGISTRY}).",
    )
    ap.add_argument(
        "--rsync-chmod",
        default="a+rX",
        help=(
            "chmod spec for rsync transfers (default: 'a+rX', world-readable). "
            "Set to '' to disable."
        ),
    )
    ap.add_argument(
        "--remote-chown",
        default="",
        help=(
            "If set (e.g. 'climate:climate'), SSH and run "
            "'sudo chown -R <spec> <artifact_dir>' after each artifact sync. "
            "Requires passwordless sudo chown on the remote."
        ),
    )
    ap.add_argument(
        "--update-latest",
        action="store_true",
        help="Update the LATEST pointer after successful publish.",
    )
    ap.add_argument(
        "--skip-validate",
        action="store_true",
        help="Skip the validate_suite pre-flight check.",
    )
    ap.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip confirmation prompt.",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be synced without executing any commands.",
    )
    args = ap.parse_args()

    remote: str | None = args.remote
    if remote and not args.remote_releases_root:
        raise SystemExit("--remote-releases-root is required when --remote is set.")
    remote_releases_root: str = args.remote_releases_root or "data/releases"
    remote_artifacts_root: str = (
        args.remote_artifacts_root
        or str(Path(remote_releases_root).parent / "artifacts")
    )
    release: str = args.release or datetime.date.today().strftime("%Y_%m_%d")
    deploy_user: str = remote.split("@")[0] if remote and "@" in remote else "deploy"
    dev_root: Path = args.dev_root
    dev_series_root = dev_root / "series"
    dev_maps_root = dev_root / "maps"
    repo_root = Path(__file__).resolve().parent.parent.parent

    print(f"Publishing to:    {remote or '(local)'}")
    print(f"New release id:   {release}")
    print(f"Target releases:  {remote_releases_root}")
    print(f"Target artifacts: {remote_artifacts_root}")
    print(f"Local dev root:   {dev_root}")
    print()

    if not args.yes and not args.dry_run:
        ans = input("Continue? [y/N] ").strip().lower()
        if ans not in ("y", "yes"):
            print("Aborted.")
            return 0
        print()

    # --- Pre-flight ---
    if not args.skip_validate:
        print("[pre-flight] Running validate_suite on dev release...")
        if not _run_validate_suite(repo_root):
            print(
                "ERROR: validate_suite failed. Fix issues before publishing.",
                file=sys.stderr,
            )
            return 1
        print()

    # --- Discover local data ---
    print("[discover] Scanning local dev data...")
    local_metrics = _discover_metrics(dev_series_root)
    local_maps = _discover_maps(dev_maps_root)
    if not local_metrics and not local_maps:
        print("ERROR: No metrics or maps found in dev release.", file=sys.stderr)
        return 1
    print(f"  {len(local_metrics)} metric(s): {', '.join(sorted(local_metrics))}")
    print(f"  {len(local_maps)} map(s):    {', '.join(sorted(local_maps))}")
    print()

    # --- Compute local checksums ---
    print("[checksum] Computing local checksums...")
    local_metric_sha: dict[str, str] = {}
    for metric_id in sorted(local_metrics):
        sha = _metric_sha256(dev_series_root, metric_id)
        local_metric_sha[metric_id] = sha
        print(f"  series/{metric_id}: {sha[:12]}...")
    local_map_sha: dict[str, str] = {}
    for map_id, map_dir in local_maps.items():
        sha = _map_sha256(map_dir)
        local_map_sha[map_id] = sha
        print(f"  maps/{map_id}: {sha[:12]}...")
    print()

    # --- Fetch prod state ---
    print("[diff] Fetching current prod release state...")
    prod = _fetch_prod_state(remote, remote_releases_root, remote_artifacts_root)
    if prod is None:
        print("  No current prod release — all artifacts will be treated as new.")
        prod_series: dict[str, str] = {}
        prod_maps: dict[str, str] = {}
        prod_series_checksums: dict[str, str | None] = {}
        prod_maps_checksums: dict[str, str | None] = {}
        base_release: str | None = None
    else:
        print(f"  Current prod release: {prod['release']}")
        base_release = prod["release"]
        prod_series = prod["manifest"].get("series", {})
        prod_maps = prod["manifest"].get("maps", {})
        prod_series_checksums = prod["series_checksums"]
        prod_maps_checksums = prod["maps_checksums"]
    print()

    # --- Diff ---
    new_metrics = [m for m in sorted(local_metrics) if m not in prod_series]
    changed_metrics = [
        m for m in sorted(local_metrics)
        if m in prod_series and local_metric_sha[m] != prod_series_checksums.get(m)
    ]
    unchanged_metrics = [
        m for m in sorted(local_metrics)
        if m in prod_series and local_metric_sha[m] == prod_series_checksums.get(m)
    ]
    removed_metrics = [m for m in prod_series if m not in local_metrics]

    new_maps = [m for m in local_maps if m not in prod_maps]
    changed_maps = [
        m for m in local_maps
        if m in prod_maps and local_map_sha[m] != prod_maps_checksums.get(m)
    ]
    unchanged_maps = [
        m for m in local_maps
        if m in prod_maps and local_map_sha[m] == prod_maps_checksums.get(m)
    ]
    removed_maps = [m for m in prod_maps if m not in local_maps]

    # --- Print diff ---
    markers = {"new": "+", "changed": "~", "unchanged": "=", "removed": "-"}
    rows: list[tuple[str, str, str]] = []
    for m in new_metrics:
        rows.append((markers["new"], "series", m))
    for m in changed_metrics:
        rows.append((markers["changed"], "series", m))
    for m in unchanged_metrics:
        rows.append((markers["unchanged"], "series", m))
    for m in removed_metrics:
        rows.append((markers["removed"], "series", m))
    for m in new_maps:
        rows.append((markers["new"], "maps", m))
    for m in changed_maps:
        rows.append((markers["changed"], "maps", m))
    for m in unchanged_maps:
        rows.append((markers["unchanged"], "maps", m))
    for m in removed_maps:
        rows.append((markers["removed"], "maps", m))

    print("Changes:")
    for marker, kind, name in rows:
        print(f"  {marker} {kind}/{name}")
    print()

    has_changes = bool(new_metrics or changed_metrics or removed_metrics or
                       new_maps or changed_maps or removed_maps)
    if not has_changes:
        print("Nothing to publish — all local data matches prod.")
        return 0

    if removed_metrics or removed_maps:
        print("WARNING: the following exist in prod but not in your local dev release")
        print("and will be EXCLUDED from the new release manifest:")
        for m in removed_metrics:
            print(f"  - series/{m}")
        for m in removed_maps:
            print(f"  - maps/{m}")
        print()

    if not args.yes and not args.dry_run:
        ans = input("Proceed with publish? [y/N] ").strip().lower()
        if ans not in ("y", "yes"):
            print("Aborted.")
            return 0
    print()

    # --- Sync artifacts ---
    sync_metrics = new_metrics + changed_metrics
    sync_maps = new_maps + changed_maps
    artifact_date = release
    now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()

    if sync_metrics:
        print(f"[sync] Syncing {len(sync_metrics)} series artifact(s)...")
        for metric_id in sync_metrics:
            grid_ids = local_metrics[metric_id]
            print(f"  series/{metric_id}  (grid_ids: {', '.join(grid_ids)})")
            dst_dir = f"{remote_artifacts_root}/series/{metric_id}/{artifact_date}"
            _ssh_mkdir(remote, dst_dir, deploy_user, dry_run=args.dry_run)
            for grid_id in grid_ids:
                src = str(dev_series_root / grid_id / metric_id)
                _rsync_dir(
                    src,
                    _dst(remote, f"{dst_dir}/"),
                    dry_run=args.dry_run,
                    chmod=args.rsync_chmod,
                )
            artifact_manifest = {
                "artifact_type": "series",
                "metric_id": metric_id,
                "artifact_date": artifact_date,
                "grid_ids": grid_ids,
                "built_at_utc": now_utc,
                "tree_sha256": local_metric_sha[metric_id],
            }
            _write_remote_json(
                remote,
                f"{remote_artifacts_root}/series/{metric_id}/{artifact_date}/.artifact_manifest.json",
                artifact_manifest,
                dry_run=args.dry_run,
                chmod=args.rsync_chmod,
            )
            if args.remote_chown:
                _ssh_chown(remote, dst_dir, args.remote_chown, recursive=True, dry_run=args.dry_run)
        print()

    if sync_maps:
        print(f"[sync] Syncing {len(sync_maps)} map artifact(s)...")
        for map_id in sync_maps:
            print(f"  maps/{map_id}")
            src = str(local_maps[map_id])
            dst_dir = f"{remote_artifacts_root}/maps/{map_id}/{artifact_date}"
            _ssh_mkdir(remote, dst_dir, deploy_user, dry_run=args.dry_run)
            _rsync_dir(
                src,
                _dst(remote, f"{dst_dir}/"),
                dry_run=args.dry_run,
                chmod=args.rsync_chmod,
            )
            artifact_manifest = {
                "artifact_type": "maps",
                "map_id": map_id,
                "artifact_date": artifact_date,
                "built_at_utc": now_utc,
                "tree_sha256": local_map_sha[map_id],
            }
            _write_remote_json(
                remote,
                f"{remote_artifacts_root}/maps/{map_id}/{artifact_date}/.artifact_manifest.json",
                artifact_manifest,
                dry_run=args.dry_run,
                chmod=args.rsync_chmod,
            )
            if args.remote_chown:
                _ssh_chown(remote, dst_dir, args.remote_chown, recursive=True, dry_run=args.dry_run)
        print()

    # --- Build new release manifest ---
    new_series_pointers: dict[str, str] = {}
    for metric_id in unchanged_metrics:
        new_series_pointers[metric_id] = prod_series[metric_id]
    for metric_id in sync_metrics:
        new_series_pointers[metric_id] = artifact_date

    new_maps_pointers: dict[str, str] = {}
    for map_id in unchanged_maps:
        new_maps_pointers[map_id] = prod_maps[map_id]
    for map_id in sync_maps:
        new_maps_pointers[map_id] = artifact_date

    release_manifest = {
        "format_version": 2,
        "release": release,
        "base_release": base_release,
        "created_at_utc": now_utc,
        "series": new_series_pointers,
        "maps": new_maps_pointers,
    }

    # --- Write release dir on remote ---
    print(f"[release] Creating release '{release}' on remote...")
    remote_release_dir = f"{remote_releases_root}/{release}"
    _ssh_mkdir(remote, remote_release_dir, deploy_user, dry_run=args.dry_run)
    _ssh_mkdir(remote, f"{remote_release_dir}/registry", deploy_user, dry_run=args.dry_run)
    registry_src = args.registry
    if registry_src.is_dir():
        _rsync_dir(
            str(registry_src),
            _dst(remote, f"{remote_release_dir}/registry/"),
            dry_run=args.dry_run,
            chmod=args.rsync_chmod,
        )
    else:
        print(f"  WARNING: registry directory not found at {registry_src}, skipping.")
    local_aux_dir = dev_root / "aux"
    if local_aux_dir.is_dir():
        print(f"  Copying aux files from {local_aux_dir}...")
        _ssh_mkdir(remote, f"{remote_release_dir}/aux", deploy_user, dry_run=args.dry_run)
        _rsync_dir(
            str(local_aux_dir),
            _dst(remote, f"{remote_release_dir}/aux/"),
            dry_run=args.dry_run,
            chmod=args.rsync_chmod,
        )
    else:
        print(f"  WARNING: no aux directory found at {local_aux_dir}; sparse risk mask will not be included in the release.")
    _write_remote_json(
        remote,
        f"{remote_release_dir}/manifest.json",
        release_manifest,
        dry_run=args.dry_run,
        chmod=args.rsync_chmod,
    )
    if args.remote_chown:
        _ssh_chown(remote, remote_release_dir, args.remote_chown, recursive=True, dry_run=args.dry_run)
    print()

    # --- Update LATEST ---
    if args.update_latest:
        print(f"[LATEST] Updating LATEST -> {release}")
        _ssh_run(
            remote,
            f"echo {shlex.quote(release)} | sudo tee {shlex.quote(remote_releases_root + '/LATEST')} > /dev/null",
            dry_run=args.dry_run,
        )
        print()

    print("Publish complete.")
    if args.dry_run:
        print("(dry run — no changes were made)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
