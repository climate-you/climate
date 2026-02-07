from __future__ import annotations

import pytest

from climate.registry.metrics import MetricsSchemaError, validate_metric_dependencies


def _base_raw(metric_id: str) -> dict:
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


def _base_derived(metric_id: str, inputs: list[str]) -> dict:
    return {
        "id": metric_id,
        "dtype": "float32",
        "missing": "nan",
        "time_axis": "yearly",
        "source": {"type": "derived", "inputs": inputs, "steps": ["identity"]},
        "storage": {"tiled": False},
    }


def test_validate_metric_dependencies_ok() -> None:
    manifest = {
        "version": "0.1",
        "a_raw": _base_raw("a_raw"),
        "b_derived": _base_derived("b_derived", ["a_raw"]),
    }
    validate_metric_dependencies(manifest)


def test_validate_metric_dependencies_cycle_fails() -> None:
    manifest = {
        "version": "0.1",
        "a": _base_derived("a", ["b"]),
        "b": _base_derived("b", ["a"]),
    }
    with pytest.raises(MetricsSchemaError, match="Cyclic metric dependency"):
        validate_metric_dependencies(manifest)


def test_validate_metric_dependencies_requires_dataset_ancestor() -> None:
    manifest = {
        "version": "0.1",
        "a": _base_derived("a", ["b"]),
        "b": {
            "id": "b",
            "dtype": "float32",
            "missing": "nan",
            "time_axis": "yearly",
            "grid_id": "global_0p25",
            "source": {"type": "cds", "dataset": "dummy", "agg": "x"},
        },
    }
    with pytest.raises(MetricsSchemaError, match="without dataset ancestor"):
        validate_metric_dependencies(manifest)


def test_validate_metric_dependencies_missing_input_fails() -> None:
    manifest = {
        "version": "0.1",
        "a": _base_derived("a", ["b"]),
    }
    with pytest.raises(MetricsSchemaError, match="depends on missing metric"):
        validate_metric_dependencies(manifest)
