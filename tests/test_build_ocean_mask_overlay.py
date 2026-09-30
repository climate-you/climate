from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("fiona")
pytest.importorskip("rasterio")

from scripts.build.build_ocean_mask import build_mask  # noqa: E402


def _square(x0: float, y0: float, x1: float, y1: float) -> dict:
    ring = [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]
    return {"type": "Polygon", "coordinates": [ring]}


def _feature(name: str, featurecla: str, geometry: dict) -> dict:
    return {
        "type": "Feature",
        "properties": {"name": name, "featurecla": featurecla},
        "geometry": geometry,
    }


@pytest.fixture()
def built(tmp_path: Path) -> dict:
    # A reef inside a sea, listed first, as in Natural Earth: the sea is burned
    # after it and claims every one of its cells in the partition.
    source = tmp_path / "marine.geojson"
    source.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    _feature("Little Reef", "reef", _square(2, -4, 4, -2)),
                    _feature("Big Sea", "sea", _square(0, -10, 10, 0)),
                ],
            }
        )
    )
    out = {
        "partition": tmp_path / "ocean_mask.npz",
        "names": tmp_path / "ocean_names.json",
        "overlay": tmp_path / "ocean_overlay_mask.npz",
    }
    build_mask(
        input_path=source,
        output_npz=out["partition"],
        output_names_json=out["names"],
        output_overlay_npz=out["overlay"],
        deg=1.0,
        name_field="name",
        id_field=None,
    )
    names = {v: int(k) for k, v in json.loads(out["names"].read_text()).items()}
    return {
        "partition": np.load(out["partition"])["data"],
        "overlay": np.load(out["overlay"])["data"],
        "reef": names["Little Reef"],
        "sea": names["Big Sea"],
    }


def test_the_partition_still_gives_the_reef_to_the_sea(built: dict) -> None:
    assert not (built["partition"] == built["reef"]).any()
    assert (built["partition"] == built["sea"]).sum() == 100


def test_the_overlay_keeps_the_reef_whole_under_the_same_id(built: dict) -> None:
    overlay = built["overlay"]
    assert set(np.unique(overlay)) == {0, built["reef"]}
    assert (overlay == built["reef"]).sum() == 4
    # Every reef cell is still a sea cell in the partition: both count it.
    assert (built["partition"][overlay == built["reef"]] == built["sea"]).all()
