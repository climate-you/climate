#!/usr/bin/env python3
"""
Prune superseded release data from the artifact store.

Each publish writes artifacts under a dated directory and records pointers in a
release manifest. Unchanged metrics keep pointing at their previous date, so old
artifact versions are never overwritten -- they simply accumulate, and a single
large metric can hold several multi-gigabyte copies.

This deletes artifact versions no longer referenced by any release that is being
kept, and optionally the old release directories themselves.

Workflow:
  1. [read]     List releases and read every manifest.
  2. [keep]     Keep LATEST plus the newest --keep-releases releases.
  3. [refer]    Collect the (kind, id, date) artifacts those releases point at.
  4. [scan]     List what is actually on disk under the artifact store.
  5. [verify]   Refuse to proceed if a kept release points at something missing.
  6. [confirm]  Print the plan with reclaimed size and prompt.
  7. [delete]   Remove unreferenced artifact versions, then pruned releases.

Usage:
  python scripts/deploy/prune_artifacts.py \\
    --remote deploy@host \\
    --remote-releases-root /opt/climate/data/releases \\
    --keep-releases 3 --dry-run

Safety:
  - The release named by LATEST is always kept, whatever --keep-releases says.
  - Nothing is deleted until every kept release is shown to be fully intact.
  - --dry-run prints the plan and changes nothing.
  - Deletion needs write permission on the artifact directories, which the
    publishing user has via the service group; no sudo is required.
"""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Shell helpers (kept local so this script stays independently runnable)
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


def _ssh_read(remote: str | None, path: str) -> str | None:
    """Return file contents, or None when it does not exist."""
    if remote is None:
        p = Path(path)
        return p.read_text(encoding="utf-8") if p.exists() else None
    result = subprocess.run(
        ["ssh", remote, f"cat {shlex.quote(path)}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else None


def _ssh_listdir(remote: str | None, path: str) -> list[str]:
    """List directory entry names, or [] when the directory does not exist."""
    if remote is None:
        p = Path(path)
        return sorted(c.name for c in p.iterdir() if c.is_dir()) if p.is_dir() else []
    result = subprocess.run(
        ["ssh", remote, f"ls -1 {shlex.quote(path)} 2>/dev/null || true"],
        capture_output=True,
        text=True,
        check=False,
    )
    return sorted(n for n in result.stdout.split("\n") if n.strip())


def _ssh_du_bytes(remote: str | None, paths: list[str]) -> int:
    """Total apparent size of the given directories, in bytes."""
    if not paths:
        return 0
    if remote is None:
        total = 0
        for p in paths:
            for f in Path(p).rglob("*"):
                if f.is_file():
                    total += f.stat().st_size
        return total
    quoted = " ".join(shlex.quote(p) for p in paths)
    result = subprocess.run(
        [
            "ssh",
            remote,
            f"du -sb {quoted} 2>/dev/null | awk '{{s+=$1}} END {{print s+0}}'",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        return int(result.stdout.strip() or 0)
    except ValueError:
        return 0


def _rm_rf(remote: str | None, paths: list[str], *, dry_run: bool) -> None:
    for path in paths:
        if remote is None:
            print(f"  $ rm -rf {shlex.quote(path)}")
            if not dry_run:
                shutil.rmtree(path, ignore_errors=True)
        else:
            _run(["ssh", remote, f"rm -rf {shlex.quote(path)}"], dry_run=dry_run)


def _human(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


# ---------------------------------------------------------------------------
# Release inspection
# ---------------------------------------------------------------------------


def _read_manifests(remote: str | None, releases_root: str) -> dict[str, dict]:
    """Return {release_id: manifest} for every release with a readable manifest."""
    manifests: dict[str, dict] = {}
    for name in _ssh_listdir(remote, releases_root):
        raw = _ssh_read(remote, f"{releases_root}/{name}/manifest.json")
        if raw is None:
            continue
        try:
            manifests[name] = json.loads(raw)
        except json.JSONDecodeError:
            print(
                f"  WARNING: {name}/manifest.json is not valid JSON, treating as keep"
            )
            manifests[name] = {}
    return manifests


def _sort_key(release_id: str, manifest: dict) -> tuple:
    """Newest last. Prefer recorded creation time, fall back to the id."""
    return (str(manifest.get("created_at_utc") or ""), release_id)


def _referenced(manifest: dict) -> set[tuple[str, str, str]]:
    """Return {(kind, artifact_id, date)} pointed at by a manifest."""
    out: set[tuple[str, str, str]] = set()
    for kind in ("series", "maps"):
        for artifact_id, date in (manifest.get(kind) or {}).items():
            out.add((kind, str(artifact_id), str(date)))
    return out


def _on_disk(remote: str | None, artifacts_root: str) -> set[tuple[str, str, str]]:
    """Return {(kind, artifact_id, date)} present in the artifact store."""
    found: set[tuple[str, str, str]] = set()
    for kind in ("series", "maps"):
        for artifact_id in _ssh_listdir(remote, f"{artifacts_root}/{kind}"):
            for date in _ssh_listdir(remote, f"{artifacts_root}/{kind}/{artifact_id}"):
                found.add((kind, artifact_id, date))
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description="Prune superseded release artifacts.")
    ap.add_argument(
        "--remote", help="SSH target, e.g. deploy@host. Omit to run locally."
    )
    ap.add_argument(
        "--remote-releases-root",
        "--releases-root",
        dest="releases_root",
        required=True,
        help="Releases root (contains LATEST and one directory per release).",
    )
    ap.add_argument(
        "--remote-artifacts-root",
        "--artifacts-root",
        dest="artifacts_root",
        help="Artifact store root. Defaults to sibling of releases root named 'artifacts'.",
    )
    ap.add_argument(
        "--keep-releases",
        type=int,
        default=3,
        help="Number of most recent releases to keep, in addition to LATEST (default: 3).",
    )
    ap.add_argument(
        "--keep-release-dirs",
        action="store_true",
        help="Keep the pruned releases' own directories (manifest/registry), "
        "deleting only the artifact data they alone referenced.",
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="Show the plan, change nothing."
    )
    ap.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")
    args = ap.parse_args()

    if args.keep_releases < 1:
        raise SystemExit("--keep-releases must be at least 1.")

    remote: str | None = args.remote
    releases_root: str = args.releases_root.rstrip("/")
    artifacts_root: str = (
        args.artifacts_root.rstrip("/")
        if args.artifacts_root
        else str(Path(releases_root).parent / "artifacts")
    )

    print(f"Releases : {releases_root}")
    print(f"Artifacts: {artifacts_root}")
    if remote:
        print(f"Remote   : {remote}")
    print()

    # --- Which releases exist, and which do we keep? ---
    manifests = _read_manifests(remote, releases_root)
    if not manifests:
        raise SystemExit("No readable release manifests found; refusing to prune.")

    latest_raw = _ssh_read(remote, f"{releases_root}/LATEST")
    latest = latest_raw.strip() if latest_raw else ""
    if not latest:
        raise SystemExit("Cannot read LATEST; refusing to prune.")
    if latest not in manifests:
        raise SystemExit(
            f"LATEST points at '{latest}', which has no readable manifest; refusing to prune."
        )

    ordered = sorted(manifests, key=lambda r: _sort_key(r, manifests[r]), reverse=True)
    keep = set(ordered[: args.keep_releases]) | {latest}

    # Some manifest pointers name another release directory rather than an
    # artifact date (currently `llm`). Never delete a directory a kept release
    # points at. `base_release` is deliberately excluded: it is provenance and
    # chains back indefinitely, so honouring it would block all pruning.
    for release_id in list(keep):
        for pointer in (manifests[release_id].get("llm") or {}).values():
            if pointer in manifests:
                keep.add(str(pointer))

    prune = [r for r in ordered if r not in keep]

    print(f"LATEST: {latest}")
    print(f"Keeping {len(keep)} release(s): {', '.join(sorted(keep))}")
    if prune:
        print(f"Pruning {len(prune)} release(s): {', '.join(sorted(prune))}")
    else:
        print("Pruning 0 releases.")
    print()

    # --- What do the kept releases still need? ---
    needed: set[tuple[str, str, str]] = set()
    for release_id in keep:
        needed |= _referenced(manifests[release_id])

    present = _on_disk(remote, artifacts_root)

    # --- Integrity gate: never proceed if a kept release is already broken ---
    missing = sorted(needed - present)
    if missing:
        print("ERROR: releases being kept reference artifacts that are not on disk:")
        for kind, artifact_id, date in missing[:20]:
            print(f"  {kind}/{artifact_id}/{date}")
        if len(missing) > 20:
            print(f"  ... and {len(missing) - 20} more")
        raise SystemExit(
            "Refusing to prune while a kept release is incomplete. "
            "Investigate before deleting anything."
        )

    obsolete = sorted(present - needed)
    if not obsolete and not prune:
        print("Nothing to prune.")
        return 0

    obsolete_paths = [f"{artifacts_root}/{k}/{i}/{d}" for k, i, d in obsolete]
    release_paths = (
        [] if args.keep_release_dirs else [f"{releases_root}/{r}" for r in prune]
    )

    print(
        f"[scan] {len(present)} artifact version(s) on disk, "
        f"{len(needed)} still referenced."
    )
    print(f"[plan] {len(obsolete)} unreferenced artifact version(s) to delete:")
    for kind, artifact_id, date in obsolete[:40]:
        print(f"  {kind}/{artifact_id}/{date}")
    if len(obsolete) > 40:
        print(f"  ... and {len(obsolete) - 40} more")
    print()

    print("[size] measuring...")
    reclaim = _ssh_du_bytes(remote, obsolete_paths + release_paths)
    print(f"[size] would reclaim ~{_human(reclaim)}")
    print()

    if args.dry_run:
        print("Dry run: nothing deleted.")
        return 0

    if not args.yes:
        answer = input("Delete these? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Aborted.")
            return 1

    print("[delete] removing unreferenced artifact versions...")
    _rm_rf(remote, obsolete_paths, dry_run=False)

    # Drop artifact directories left empty once their versions are gone.
    for kind in ("series", "maps"):
        for artifact_id in {i for k, i, _ in obsolete if k == kind}:
            path = f"{artifacts_root}/{kind}/{artifact_id}"
            if not _ssh_listdir(remote, path):
                _rm_rf(remote, [path], dry_run=False)

    if release_paths:
        print("[delete] removing pruned release directories...")
        _rm_rf(remote, release_paths, dry_run=False)

    print()
    print(f"Done. Reclaimed ~{_human(reclaim)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
