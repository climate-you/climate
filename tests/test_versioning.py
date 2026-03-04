from __future__ import annotations

from pathlib import Path

from climate_api.versioning import AppVersionInfo, resolve_app_version


def test_run_git_marks_repo_root_as_safe(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[list[str], Path]] = []

    class _Result:
        returncode = 0
        stdout = "ok\n"

    def _fake_run(cmd, cwd, capture_output, text, check):  # type: ignore[no-untyped-def]
        calls.append((cmd, cwd))
        return _Result()

    monkeypatch.setattr("climate_api.versioning.subprocess.run", _fake_run)
    from climate_api.versioning import _run_git

    out = _run_git(repo_root=tmp_path, args=["rev-parse", "--short", "HEAD"])
    assert out == "ok"
    assert len(calls) == 1
    cmd, cwd = calls[0]
    assert cmd[:3] == ["git", "-c", f"safe.directory={tmp_path.resolve()}"]
    assert cmd[3:] == ["rev-parse", "--short", "HEAD"]
    assert cwd == tmp_path.resolve()


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
