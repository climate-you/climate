from __future__ import annotations

import json
from pathlib import Path

import pytest

import climate.packager.registry as registry_module


def _write_datasets(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def test_copy_sparse_risk_aux_mask_if_needed_copies_when_global_0p05_metric_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_repo = tmp_path / "repo"
    src_mask = fake_repo / "data" / "masks" / "sparse_risk_global_0p25_mask.npz"
    src_mask.parent.mkdir(parents=True, exist_ok=True)
    src_mask.write_bytes(b"mask-bytes")
    monkeypatch.setattr(registry_module, "REPO_ROOT", fake_repo)

    datasets_path = tmp_path / "datasets.json"
    _write_datasets(
        datasets_path,
        {
            "version": "0.1",
            "any_metric": {"id": "any_metric", "grid_id": "global_0p05"},
        },
    )
    release_root = tmp_path / "releases" / "dev"

    registry_module._copy_sparse_risk_aux_mask_if_needed(
        release_root=release_root,
        datasets_path=datasets_path,
    )

    dst = release_root / "aux" / "sparse_risk_global_0p25_mask.npz"
    assert dst.exists()
    assert dst.read_bytes() == b"mask-bytes"


def test_copy_sparse_risk_aux_mask_if_needed_skips_when_no_global_0p05_metric(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_repo = tmp_path / "repo"
    monkeypatch.setattr(registry_module, "REPO_ROOT", fake_repo)

    datasets_path = tmp_path / "datasets.json"
    _write_datasets(
        datasets_path, {"version": "0.1", "era5_daily_t2m": {"id": "era5_daily_t2m"}}
    )
    release_root = tmp_path / "releases" / "dev"

    registry_module._copy_sparse_risk_aux_mask_if_needed(
        release_root=release_root,
        datasets_path=datasets_path,
    )

    assert not (release_root / "aux" / "sparse_risk_global_0p25_mask.npz").exists()


def test_copy_sparse_risk_aux_mask_if_needed_fails_when_source_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_repo = tmp_path / "repo"
    monkeypatch.setattr(registry_module, "REPO_ROOT", fake_repo)

    datasets_path = tmp_path / "datasets.json"
    _write_datasets(
        datasets_path,
        {
            "version": "0.1",
            "any_metric": {"id": "any_metric", "grid_id": "global_0p05"},
        },
    )

    with pytest.raises(FileNotFoundError, match="sparse-risk mask"):
        registry_module._copy_sparse_risk_aux_mask_if_needed(
            release_root=tmp_path / "releases" / "dev",
            datasets_path=datasets_path,
        )
