from __future__ import annotations

import pytest

from climate.registry.maps import (
    MapsSchemaError,
    validate_maps_against_metrics,
    validate_maps_mobile_output_requirements,
)


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
            "type": "texture",
            "source_metric": "t2m_yearly_mean_c",
        },
        "trend_interest": {
            "id": "trend_interest",
            "type": "score",
            "source_metric": "t2m_yearly_mean_c",
            "score_rules": [],
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
            "type": "texture",
            "source_metric": "missing_metric",
        },
    }
    metrics_manifest = {
        "version": "0.1",
        "t2m_yearly_mean_c": _base_metric("t2m_yearly_mean_c"),
    }
    with pytest.raises(MapsSchemaError, match="unknown source_metric"):
        validate_maps_against_metrics(maps_manifest, metrics_manifest)


def test_validate_maps_against_metrics_requires_materialized_source() -> None:
    maps_manifest = {
        "version": "0.1",
        "warming_texture": {
            "id": "warming_texture",
            "type": "texture",
            "source_metric": "derived_runtime_only",
        },
    }
    metric = _base_metric("derived_runtime_only")
    metric["materialize"] = "on_api"
    metrics_manifest = {"version": "0.1", "derived_runtime_only": metric}
    with pytest.raises(MapsSchemaError, match="not materialized as tiled data"):
        validate_maps_against_metrics(maps_manifest, metrics_manifest)


def test_validate_maps_against_metrics_allows_constant_score_map_without_metric() -> (
    None
):
    maps_manifest = {
        "version": "0.1",
        "score_1_map": {
            "id": "score_1_map",
            "type": "score",
            "constant_score": 1,
        },
    }
    metrics_manifest = {"version": "0.1"}
    validate_maps_against_metrics(maps_manifest, metrics_manifest)


def test_validate_maps_mobile_output_requirements_requires_mobile_filename() -> None:
    maps_manifest = {
        "version": "0.1",
        "reef": {
            "id": "reef",
            "type": "texture",
            "projection": "mercator",
            "source_metric": "dhw_metric",
            "output": {"filename": "reef.webp"},
        },
    }
    metrics_manifest = {
        "version": "0.1",
        "dhw_metric": {
            **_base_metric("dhw_metric"),
            "grid_id": "global_0p05",
        },
    }
    layers_manifest = {
        "version": "0.1",
        "reef_layer": {"id": "reef_layer", "label": "Reef", "map_id": "reef"},
    }

    with pytest.raises(MapsSchemaError, match="missing output.mobile_filename"):
        validate_maps_mobile_output_requirements(
            maps_manifest=maps_manifest,
            metrics_manifest=metrics_manifest,
            layers_manifest=layers_manifest,
        )


def test_validate_maps_mobile_output_requirements_scopes_to_layer_references() -> None:
    maps_manifest = {
        "version": "0.1",
        "reef": {
            "id": "reef",
            "type": "texture",
            "projection": "mercator",
            "source_metric": "dhw_metric",
            "output": {"filename": "reef.webp"},
        },
    }
    metrics_manifest = {
        "version": "0.1",
        "dhw_metric": {
            **_base_metric("dhw_metric"),
            "grid_id": "global_0p05",
        },
    }
    layers_manifest = {"version": "0.1"}

    validate_maps_mobile_output_requirements(
        maps_manifest=maps_manifest,
        metrics_manifest=metrics_manifest,
        layers_manifest=layers_manifest,
    )
