from __future__ import annotations

import pytest

from climate.registry.panels import PanelsSchemaError, validate_panels_against_metrics


def _raw_metric(metric_id: str) -> dict:
    return {
        "id": metric_id,
        "dtype": "float32",
        "missing": "nan",
        "time_axis": "yearly",
        "grid_id": "global_0p25",
        "source": {"type": "cds", "_dataset_ref": "dataset_a", "agg": "annual"},
        "storage": {"tiled": True, "tile_size": 64},
    }


def _derived_metric(metric_id: str, inputs: list[str], materialize: str = "on_api") -> dict:
    return {
        "id": metric_id,
        "dtype": "float32",
        "missing": "nan",
        "time_axis": "yearly",
        "grid_id": "global_0p25",
        "source": {"type": "derived", "inputs": inputs, "steps": ["identity"]},
        "materialize": materialize,
    }


def _panels(metric_id: str) -> dict:
    return {
        "version": "0.1",
        "panels": {
            "overview": {
                "title": "Overview",
                "graphs": [
                    {
                        "id": "g1",
                        "title": "Graph 1",
                        "series": [{"metric": metric_id, "label": "Series 1", "unit": "C"}],
                    }
                ],
            }
        },
    }


def test_panels_against_metrics_ok_with_materialized_ancestor() -> None:
    metrics = {
        "version": "0.1",
        "base": _raw_metric("base"),
        "derived": _derived_metric("derived", ["base"], materialize="on_api"),
    }
    validate_panels_against_metrics(_panels("derived"), metrics)


def test_panels_against_metrics_unknown_metric_fails() -> None:
    metrics = {"version": "0.1", "base": _raw_metric("base")}
    with pytest.raises(PanelsSchemaError, match="unknown metric"):
        validate_panels_against_metrics(_panels("missing"), metrics)


def test_panels_against_metrics_no_materialized_ancestor_fails() -> None:
    metrics = {
        "version": "0.1",
        "a": _derived_metric("a", ["b"], materialize="on_api"),
        "b": _derived_metric("b", ["a"], materialize="on_api"),
    }
    with pytest.raises(PanelsSchemaError, match="no materialized ancestor"):
        validate_panels_against_metrics(_panels("a"), metrics)
