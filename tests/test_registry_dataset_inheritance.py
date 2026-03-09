from __future__ import annotations

import json
from pathlib import Path
import sys
import types

import numpy as np
import pytest
import xarray as xr

# Avoid hard dependency during unit tests that only exercise range/helpers.
if "cdsapi" not in sys.modules:
    sys.modules["cdsapi"] = types.SimpleNamespace(Client=object)

from climate.packager.registry import (
    TileRange,
    _batch_target_lat_lon,
    _concat_and_write_time_tiles,
    _slice_daily_cache_to_tile_batch,
    _resolve_batch_tiles,
    _resolve_year_ranges,
)
from climate.registry.metrics import MetricsSchemaError, load_metrics
from climate.tiles.layout import GridSpec


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_dataset_grid_and_tile_size_inherited_to_metric_and_derived(
    tmp_path: Path,
) -> None:
    datasets = {
        "version": "0.1",
        "era5_daily_t2m": {
            "id": "era5_daily_t2m",
            "grid_id": "global_0p25",
            "tile_size": 64,
            "source": {
                "type": "cds",
                "dataset": "derived-era5-single-levels-daily-statistics",
                "variable": "2m_temperature",
                "time_range": {"start_year": 1982, "end_year": 2025},
                "block_years": 4,
                "block_months": 1,
                "batch_tiles": 4,
            },
        },
    }
    metrics = {
        "version": "0.1",
        "hotdays": {
            "id": "hotdays",
            "dtype": "float32",
            "missing": "nan",
            "time_axis": "yearly",
            "source": {
                "type": "cds",
                "dataset_ref": "era5_daily_t2m",
                "agg": "hot_days_per_year",
                "params": {"baseline_years": 10, "percentile": 90},
            },
            "storage": {"tiled": True},
        },
        "hotdays_smoothed": {
            "id": "hotdays_smoothed",
            "dtype": "float32",
            "missing": "nan",
            "time_axis": "yearly",
            "source": {
                "type": "derived",
                "inputs": ["hotdays"],
                "steps": [{"fn": "rolling_mean", "params": {"window": 5}}],
            },
        },
    }

    datasets_path = tmp_path / "datasets.json"
    metrics_path = tmp_path / "metrics.json"
    _write_json(datasets_path, datasets)
    _write_json(metrics_path, metrics)

    manifest = load_metrics(
        path=metrics_path,
        datasets_path=datasets_path,
        validate=True,
    )
    assert manifest["hotdays"]["grid_id"] == "global_0p25"
    assert manifest["hotdays"]["storage"]["tile_size"] == 64
    assert manifest["hotdays_smoothed"]["grid_id"] == "global_0p25"
    assert manifest["hotdays_smoothed"]["storage"]["tile_size"] == 64


def test_metric_cannot_override_dataset_download_fields(tmp_path: Path) -> None:
    datasets = {
        "version": "0.1",
        "oisst_sst_v21_daily": {
            "id": "oisst_sst_v21_daily",
            "grid_id": "global_0p25",
            "tile_size": 64,
            "source": {
                "type": "erddap",
                "dataset_key": "oisst_sst_v21_daily",
                "time_range": {"start_year": 1982, "end_year": 2025},
                "block_years": 4,
                "batch_tiles": 4,
                "mask_file": "data/masks/oisst_mask.npz",
            },
        },
    }
    metrics = {
        "version": "0.1",
        "sst_hotdays": {
            "id": "sst_hotdays",
            "dtype": "float32",
            "missing": "nan",
            "time_axis": "yearly",
            "source": {
                "type": "erddap",
                "dataset_ref": "oisst_sst_v21_daily",
                "agg": "hot_days_per_year",
                "batch_tiles_override": 2,
                "time_range": {"start_year": 1984, "end_year": 1989},
                "params": {"baseline_years": 10, "percentile": 90},
            },
        },
    }
    datasets_path = tmp_path / "datasets.json"
    metrics_path = tmp_path / "metrics.json"
    _write_json(datasets_path, datasets)
    _write_json(metrics_path, metrics)

    manifest = load_metrics(
        path=metrics_path, datasets_path=datasets_path, validate=True
    )
    src = manifest["sst_hotdays"]["source"]
    assert src["time_range"] == {"start_year": 1982, "end_year": 2025}
    assert src["block_years"] == 4
    assert src["batch_tiles"] == 4
    assert src["mask_file"] == "data/masks/oisst_mask.npz"
    assert src["batch_tiles_override"] == 2
    assert src["_analysis_time_range"] == {"start_year": 1984, "end_year": 1989}


def test_batch_tiles_override_precedence() -> None:
    source = {"batch_tiles": 24, "batch_tiles_override": 4}
    assert _resolve_batch_tiles(None, source) == 4
    assert _resolve_batch_tiles(8, source) == 8
    assert _resolve_batch_tiles(None, {"batch_tiles": 24}) == 24


def test_dataset_block_alignment_for_download_window() -> None:
    source = {
        "type": "erddap",
        "_dataset_ref": "oisst_sst_v21_daily",
        "time_range": {"start_year": 1982, "end_year": 2025},
        "_analysis_time_range": {"start_year": 1984, "end_year": 1989},
        "block_years": 5,
    }
    analysis_start, analysis_end, download_start, download_end = _resolve_year_ranges(
        source=source,
        cli_start_year=None,
        cli_end_year=None,
    )
    assert (analysis_start, analysis_end) == (1984, 1989)
    assert (download_start, download_end) == (1982, 1991)


def test_concat_and_write_clips_to_metric_analysis_years(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    years = np.arange(1982, 1992, dtype=np.int32)
    da = xr.DataArray(
        np.arange(10, dtype=np.float32).reshape(1, 1, 10),
        coords={"latitude": [0.0], "longitude": [0.0], "year": years},
        dims=("latitude", "longitude", "year"),
    )

    captured: dict[str, object] = {}

    def _fake_tiles_from_time_da(**kwargs: object) -> int:
        arr = kwargs["da"]
        captured["axis_values"] = kwargs["axis_values"]
        captured["time_dim"] = kwargs["time_dim"]
        captured["axis_name"] = kwargs["axis_name"]
        captured["years_coord"] = list(arr["year"].values.tolist())
        captured["values"] = arr.values.reshape(-1).tolist()
        return 1

    monkeypatch.setattr(
        "climate.packager.registry._tiles_from_time_da",
        _fake_tiles_from_time_da,
    )

    output_years = list(range(1984, 1990))
    written = _concat_and_write_time_tiles(
        da_parts=[da],
        output_years=output_years,
        time_axis="yearly",
        out_root=tmp_path,
        grid=GridSpec.global_0p25(tile_size=64),
        metric_id="sst_hotdays",
        tile_range=TileRange(tile_r0=0, tile_r1=0, tile_c0=0, tile_c1=0),
        dtype=np.dtype("float32"),
        missing=np.nan,
        compression={"codec": "none"},
        debug=False,
        resume=False,
    )

    assert written == 1
    assert captured["axis_values"] == output_years
    assert captured["time_dim"] == "year"
    assert captured["axis_name"] == "yearly"
    assert captured["years_coord"] == output_years
    assert captured["values"] == [2.0, 3.0, 4.0, 5.0, 6.0, 7.0]


def test_slice_daily_cache_keeps_full_batch_grid(tmp_path: Path) -> None:
    grid = GridSpec.global_0p25(tile_size=64)
    tile_range = TileRange(tile_r0=0, tile_r1=3, tile_c0=0, tile_c1=3)
    lat_vals, lon_vals = _batch_target_lat_lon(
        grid, TileRange(tile_r0=0, tile_r1=11, tile_c0=0, tile_c1=22)
    )
    lon_vals_360 = (lon_vals + 360.0) % 360.0
    values = np.random.default_rng(123).random(
        (1, lat_vals.size, lon_vals_360.size), dtype=np.float32
    )

    src = tmp_path / "src.nc"
    dst = tmp_path / "dst.nc"
    ds = xr.Dataset(
        {
            "t2m": (
                ("time", "latitude", "longitude"),
                values,
            )
        },
        coords={
            "time": np.array(["2021-01-01"], dtype="datetime64[ns]"),
            "latitude": lat_vals,
            "longitude": lon_vals_360,
        },
    )
    ds.to_netcdf(src)

    _slice_daily_cache_to_tile_batch(
        src_path=src,
        dst_path=dst,
        grid=grid,
        tile_range=tile_range,
    )

    with xr.open_dataset(dst) as out:
        lat_name, lon_name = "latitude", "longitude"
        expected_lat, expected_lon = _batch_target_lat_lon(grid, tile_range)
        assert out.sizes[lat_name] == expected_lat.size
        assert out.sizes[lon_name] == expected_lon.size
        np.testing.assert_allclose(out[lat_name].values, expected_lat)
        np.testing.assert_allclose(out[lon_name].values, expected_lon)


def test_derived_domain_inherited_and_mismatch_rejected(tmp_path: Path) -> None:
    datasets = {
        "version": "0.1",
        "oisst_sst_v21_daily": {
            "id": "oisst_sst_v21_daily",
            "grid_id": "global_0p25",
            "tile_size": 64,
            "source": {
                "type": "erddap",
                "dataset_key": "oisst_sst_v21_daily",
                "time_range": {"start_year": 1982, "end_year": 2025},
                "block_years": 1,
                "batch_tiles": 4,
            },
        },
    }
    metrics = {
        "version": "0.1",
        "sst_yearly_mean_c": {
            "id": "sst_yearly_mean_c",
            "dtype": "float32",
            "missing": "nan",
            "domain": "ocean",
            "time_axis": "yearly",
            "source": {
                "type": "erddap",
                "dataset_ref": "oisst_sst_v21_daily",
                "agg": "annual_mean_from_daily",
            },
            "storage": {"tiled": True},
        },
        "sst_yearly_5y_mean_c": {
            "id": "sst_yearly_5y_mean_c",
            "dtype": "float32",
            "missing": "nan",
            "time_axis": "yearly",
            "source": {
                "type": "derived",
                "inputs": ["sst_yearly_mean_c"],
                "steps": [{"fn": "rolling_mean", "params": {"window": 5}}],
            },
            "storage": {"tiled": True},
        },
    }
    datasets_path = tmp_path / "datasets.json"
    metrics_path = tmp_path / "metrics.json"
    _write_json(datasets_path, datasets)
    _write_json(metrics_path, metrics)

    manifest = load_metrics(
        path=metrics_path, datasets_path=datasets_path, validate=True
    )
    assert manifest["sst_yearly_5y_mean_c"]["domain"] == "ocean"

    metrics["sst_yearly_5y_mean_c"]["domain"] = "global"
    _write_json(metrics_path, metrics)
    with pytest.raises(MetricsSchemaError, match="does not match derived input domain"):
        load_metrics(path=metrics_path, datasets_path=datasets_path, validate=True)
