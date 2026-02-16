from __future__ import annotations

from pathlib import Path
import json

import numpy as np

from climate_api.store.ocean_classifier import OceanClassifier


def _write_mask(tmp_path: Path, data: np.ndarray) -> tuple[Path, Path]:
    mask_npz = tmp_path / "ocean_mask.npz"
    names_json = tmp_path / "ocean_names.json"
    np.savez_compressed(
        mask_npz,
        data=data.astype(np.int32),
        deg=np.float64(1.0),
        lat_max=np.float64(2.5),
        lon_min=np.float64(-2.5),
    )
    names_json.write_text(json.dumps({"1": "Test Ocean"}), encoding="utf-8")
    return mask_npz, names_json


def test_classify_water_cell(tmp_path: Path) -> None:
    data = np.zeros((5, 5), dtype=np.int32)
    data[2, 2] = 1
    mask_npz, names_json = _write_mask(tmp_path, data)

    classifier = OceanClassifier(mask_npz, names_json)
    hit = classifier.classify(0.0, 0.0)
    assert hit.in_water
    assert hit.ocean_name == "Test Ocean"


def test_classify_uses_ocean_id_name(tmp_path: Path) -> None:
    data = np.ones((5, 5), dtype=np.int32)
    data[0, 0] = 0
    data[0, 1] = 0
    mask_npz, names_json = _write_mask(tmp_path, data)

    classifier = OceanClassifier(mask_npz, names_json)
    hit = classifier.classify(0.0, 0.0)
    assert hit.in_water
    assert hit.ocean_id == 1
    assert hit.ocean_name == "Test Ocean"
