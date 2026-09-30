from __future__ import annotations

import json
from pathlib import Path

from climate_api.store.region_shapes import RegionShapes

FRANCE = {"type": "MultiPolygon", "coordinates": [[[[0, 0], [1, 0], [1, 1], [0, 0]]]]}


def test_outlines_are_served_as_the_geometry_they_were_built_as(tmp_path: Path) -> None:
    path = tmp_path / "region_shapes.json"
    path.write_text(json.dumps({"country:FR": FRANCE}), encoding="utf-8")

    shapes = RegionShapes(path)

    assert len(shapes) == 1
    assert json.loads(shapes.get("country:FR")) == FRANCE
    assert shapes.get("country:ZZ") is None


def test_a_missing_file_disables_outlines_without_failing(tmp_path: Path) -> None:
    # A server whose location assets predate the outlines must still start.
    shapes = RegionShapes(tmp_path / "absent.json")
    assert len(shapes) == 0
    assert shapes.get("country:FR") is None


def test_outlines_can_be_switched_off() -> None:
    assert len(RegionShapes(None)) == 0
