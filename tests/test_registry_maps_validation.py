from __future__ import annotations

import pytest

from climate.registry.maps import MapsSchemaError, validate_maps_against_metrics


def _base_metric(metric_id: str) -> dict:
    return {
        "id": metric_id,
        "dtype": "float32",
        "missing": "nan",
        "time_axis": "yearly",
        "grid_id": "global_0p25",
        "source": {
            "type": "cds",
            "dataset": "dummy",
            "_dataset_ref": "dataset_a",
            "agg": "annual_mean_from_monthly",
        },
        "storage": {"tiled": True, "tile_size": 64},
    }


def test_validate_maps_against_metrics_ok() -> None:
    maps_manifest = {
        "version": "0.1",
        "warming_texture": {
            "id": "warming_texture",
            "type": "texture_png",
            "source_metric": "t2m_yearly_mean_c",
        },
        "trend_interest": {
            "id": "trend_interest",
            "type": "interestingness",
            "source_metric": "t2m_yearly_mean_c",
            "predicate": {"op": "gt", "threshold": 0.0},
        },
    }
    metrics_manifest = {
        "version": "0.1",
        "t2m_yearly_mean_c": _base_metric("t2m_yearly_mean_c"),
    }
    validate_maps_against_metrics(maps_manifest, metrics_manifest)


def test_validate_maps_against_metrics_missing_metric_fails() -> None:
    maps_manifest = {
        "version": "0.1",
        "warming_texture": {
            "id": "warming_texture",
            "type": "texture_png",
            "source_metric": "missing_metric",
        },
    }
    metrics_manifest = {"version": "0.1", "t2m_yearly_mean_c": _base_metric("t2m_yearly_mean_c")}
    with pytest.raises(MapsSchemaError, match="unknown source_metric"):
        validate_maps_against_metrics(maps_manifest, metrics_manifest)


def test_validate_maps_against_metrics_requires_materialized_source() -> None:
    maps_manifest = {
        "version": "0.1",
        "warming_texture": {
            "id": "warming_texture",
            "type": "texture_png",
            "source_metric": "derived_runtime_only",
        },
    }
    metric = _base_metric("derived_runtime_only")
    metric["materialize"] = "on_api"
    metrics_manifest = {"version": "0.1", "derived_runtime_only": metric}
    with pytest.raises(MapsSchemaError, match="not materialized as tiled data"):
        validate_maps_against_metrics(maps_manifest, metrics_manifest)
