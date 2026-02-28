from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

_SEMVER_TAG_PATTERN = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")


@dataclass(frozen=True)
class AppVersionInfo:
    app_version: str
    app_tag: str | None
    app_commit: str | None


def _run_git(*, repo_root: Path, args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _semver_key(tag: str) -> tuple[int, int, int] | None:
    match = _SEMVER_TAG_PATTERN.fullmatch(tag.strip())
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _select_preferred_tag(tags: list[str]) -> str | None:
    cleaned = sorted({tag.strip() for tag in tags if tag.strip()})
    if not cleaned:
        return None
    semver_tags = [(tag, _semver_key(tag)) for tag in cleaned]
    semver_only = [(tag, key) for tag, key in semver_tags if key is not None]
    if semver_only:
        semver_only.sort(key=lambda item: item[1])
        return semver_only[-1][0]
    return cleaned[0]


def resolve_app_version(*, repo_root: Path) -> AppVersionInfo:
    commit = _run_git(repo_root=repo_root, args=["rev-parse", "--short", "HEAD"])
    tags_raw = _run_git(repo_root=repo_root, args=["tag", "--points-at", "HEAD"])
    tags = tags_raw.splitlines() if tags_raw else []
    tag = _select_preferred_tag(tags)

    if tag:
        return AppVersionInfo(app_version=tag, app_tag=tag, app_commit=commit)
    if commit:
        return AppVersionInfo(
            app_version=f"dev+{commit}",
            app_tag=None,
            app_commit=commit,
        )
    return AppVersionInfo(app_version="unknown", app_tag=None, app_commit=None)
