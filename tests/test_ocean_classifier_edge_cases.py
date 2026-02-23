from __future__ import annotations

from pathlib import Path
import json

import numpy as np
import pytest

from climate_api.store.ocean_classifier import OceanClassifier


def test_ocean_classifier_init_validation_errors(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Ocean mask NPZ not found"):
        OceanClassifier(tmp_path / "missing.npz")

    missing_data = tmp_path / "missing_data.npz"
    np.savez_compressed(
        missing_data,
        deg=np.float64(1.0),
        lat_max=np.float64(1.0),
        lon_min=np.float64(-1.0),
    )
    with pytest.raises(ValueError, match="missing 'data' array"):
        OceanClassifier(missing_data)

    bad_ndim = tmp_path / "bad_ndim.npz"
    np.savez_compressed(
        bad_ndim,
        data=np.array([1, 2, 3], dtype=np.int32),
        deg=np.float64(1.0),
        lat_max=np.float64(1.0),
        lon_min=np.float64(-1.0),
    )
    with pytest.raises(ValueError, match="must be a 2D array"):
        OceanClassifier(bad_ndim)

    bad_deg = tmp_path / "bad_deg.npz"
    np.savez_compressed(
        bad_deg,
        data=np.zeros((2, 2), dtype=np.int32),
        deg=np.float64(0.0),
        lat_max=np.float64(1.0),
        lon_min=np.float64(-1.0),
    )
    with pytest.raises(ValueError, match="must be > 0"):
        OceanClassifier(bad_deg)


def test_ocean_classifier_names_parsing_and_clamping(tmp_path: Path) -> None:
    mask = tmp_path / "mask.npz"
    names = tmp_path / "names.json"
    np.savez_compressed(
        mask,
        data=np.array([[1, 0], [2, 3]], dtype=np.int32),
        deg=np.float64(1.0),
        lat_max=np.float64(1.0),
        lon_min=np.float64(-1.0),
    )
    names.write_text(
        json.dumps({"1": "One", "bad": "ignored", "3": "Three"}),
        encoding="utf-8",
    )

    classifier = OceanClassifier(mask, names)

    # Extreme lat/lon should clamp/normalize into valid array indices.
    hit1 = classifier.classify(999.0, 719.0)
    assert hit1.in_water
    assert hit1.ocean_id == 1
    assert hit1.ocean_name == "One"

    hit2 = classifier.classify(-999.0, -181.0)
    assert hit2.in_water
    assert hit2.ocean_id in {2, 3}

    # Land cell returns not in water.
    land = classifier.classify(0.5, 0.2)
    assert not land.in_water
    assert land.ocean_name is None
