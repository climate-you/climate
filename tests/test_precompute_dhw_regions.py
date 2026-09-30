from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

xr = pytest.importorskip("xarray")
pytest.importorskip("netCDF4")

from scripts import precompute_dhw_global_risk as dhw  # noqa: E402

DEG = 0.05
# A 0.05° window from 10°N, 0°E: small masks stand in for the global ones, which
# SeaIndex reads through their own lat_max/lon_min/deg.
LAT_MAX, LON_MIN, SIZE = 10.0, 0.0, 8


def _mask(path: Path, data: np.ndarray) -> Path:
    np.savez(path, data=data, deg=DEG, lat_max=LAT_MAX, lon_min=LON_MIN)
    return path


@pytest.fixture()
def world(tmp_path: Path) -> dict:
    # A 4x4 tile at the window's top-left corner. Every cell is sea 1; the left
    # half is also inside overlay sea 2 (a reef within the sea). Only the top
    # row is reef-domain: the other rows are open water that the global series
    # counts but a sea's must not.
    ocean = np.zeros((SIZE, SIZE), np.int32)
    ocean[:4, :4] = 1
    overlay = np.zeros((SIZE, SIZE), np.int32)
    overlay[:4, :2] = 2
    reef = np.zeros((SIZE, SIZE), np.uint8)
    reef[0, :4] = 1
    names = tmp_path / "ocean_names.json"
    names.write_text(json.dumps({"1": "Big Sea", "2": "Little Reef"}))

    lat = LAT_MAX - (np.arange(4) + 0.5) * DEG
    lon = LON_MIN + (np.arange(4) + 0.5) * DEG
    # Two days. Day 1: the top row's first cell severe, second moderate. Day 2:
    # nothing stressed. Open water is hot on both days.
    dhw_values = np.zeros((2, 4, 4))
    dhw_values[:, 1:, :] = 9.0
    dhw_values[0, 0, 0] = 9.0
    dhw_values[0, 0, 1] = 5.0
    tile = tmp_path / "cache" / "tile_a"
    tile.mkdir(parents=True)
    xr.Dataset(
        {"degree_heating_week": (("time", "latitude", "longitude"), dhw_values)},
        coords={
            "time": np.array(["2024-01-01", "2024-01-02"], dtype="datetime64[ns]"),
            "latitude": lat,
            "longitude": lon,
        },
    ).to_netcdf(tile / "crw_2024-01-01_2024-12-31.nc")

    seas = dhw.SeaIndex(
        _mask(tmp_path / "ocean.npz", ocean),
        _mask(tmp_path / "overlay.npz", overlay),
        names,
        _mask(tmp_path / "reef.npz", reef),
    )
    ever_valid: dict = {}
    counts, per_sea = dhw.compute_counts_year(
        2024, tmp_path / "cache", seas, ever_valid
    )
    return {
        "counts": counts,
        "per_sea": per_sea,
        "reef_cells": dhw.reef_cell_counts(seas, ever_valid),
    }


def test_a_sea_counts_only_its_reef_cells(world: dict) -> None:
    severe, moderate, valid = world["per_sea"]["ocean:big_sea"]
    assert list(valid) == [4, 4]
    assert list(severe) == [1, 0]
    assert list(moderate) == [2, 0]  # moderate includes severe
    assert world["reef_cells"]["ocean:big_sea"] == 4


def test_an_overlay_sea_counts_its_reefs_too_without_taking_them(world: dict) -> None:
    severe, moderate, valid = world["per_sea"]["ocean:little_reef"]
    assert list(valid) == [2, 2]
    assert list(severe) == [1, 0]
    assert world["reef_cells"]["ocean:little_reef"] == 2


def test_the_global_series_still_counts_every_cell_with_data(world: dict) -> None:
    # Unchanged behaviour: open water in the tiles is part of the global count.
    severe, moderate, valid = world["counts"]
    assert list(valid) == [16, 16]
    assert list(severe) == [13, 12]


def test_a_sea_is_classified_like_the_globe(world: dict) -> None:
    # Day 1: 1 of 4 reef cells severe (25%) -> severe at 10%; day 2 no risk.
    assert dhw.classify(*world["per_sea"]["ocean:big_sea"], 10) == (1, 0, 1)
