from __future__ import annotations

from pathlib import Path

from climate_api.versioning import AppVersionInfo, resolve_app_version


def test_resolve_app_version_uses_exact_semver_tag(
    monkeypatch,
) -> None:
    def _fake_run_git(*, repo_root: Path, args: list[str]) -> str | None:
        if args == ["rev-parse", "--short", "HEAD"]:
            return "abc1234"
        if args == ["tag", "--points-at", "HEAD"]:
            return "release-candidate\nv1.2.3\nv1.2.2"
        return None

    monkeypatch.setattr("climate_api.versioning._run_git", _fake_run_git)
    out = resolve_app_version(repo_root=Path("."))
    assert out == AppVersionInfo(
        app_version="v1.2.3",
        app_tag="v1.2.3",
        app_commit="abc1234",
    )


def test_resolve_app_version_uses_dev_commit_without_tag(monkeypatch) -> None:
    def _fake_run_git(*, repo_root: Path, args: list[str]) -> str | None:
        if args == ["rev-parse", "--short", "HEAD"]:
            return "deadbee"
        if args == ["tag", "--points-at", "HEAD"]:
            return ""
        return None

    monkeypatch.setattr("climate_api.versioning._run_git", _fake_run_git)
    out = resolve_app_version(repo_root=Path("."))
    assert out == AppVersionInfo(
        app_version="dev+deadbee",
        app_tag=None,
        app_commit="deadbee",
    )


def test_resolve_app_version_returns_unknown_when_git_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        "climate_api.versioning._run_git",
        lambda **kwargs: None,
    )
    out = resolve_app_version(repo_root=Path("."))
    assert out == AppVersionInfo(
        app_version="unknown",
        app_tag=None,
        app_commit=None,
    )
