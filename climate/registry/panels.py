from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .metrics import MetricsSchemaError, REPO_ROOT

DEFAULT_PANELS_PATH = REPO_ROOT / "registry" / "panels.json"
DEFAULT_PANELS_SCHEMA_PATH = Path(__file__).with_name("panels.schema.json")


class PanelsSchemaError(ValueError):
    pass


def load_panels_schema(path: Path | str = DEFAULT_PANELS_SCHEMA_PATH) -> dict[str, Any]:
    schema_path = Path(path)
    with schema_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_panels(
    path: Path | str = DEFAULT_PANELS_PATH,
    *,
    schema_path: Path | str = DEFAULT_PANELS_SCHEMA_PATH,
    validate: bool = True,
) -> dict[str, Any]:
    panels_path = Path(path)
    with panels_path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)

    if validate:
        schema = load_panels_schema(schema_path)
        validate_panels(manifest, schema)

    return manifest


def validate_panels(manifest: dict[str, Any], schema: dict[str, Any]) -> None:
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(manifest), key=_error_sort_key)
    if errors:
        formatted = "\n".join(_format_error(err) for err in errors)
        raise PanelsSchemaError(f"panels.json failed schema validation:\n{formatted}")


def validate_panels_against_metrics(
    panels_manifest: dict[str, Any], metrics_manifest: dict[str, Any]
) -> None:
    metrics = {
        key: spec
        for key, spec in metrics_manifest.items()
        if key != "version" and isinstance(spec, dict)
    }
    panels_root = panels_manifest.get("panels", {})
    if not isinstance(panels_root, dict):
        return

    memo: dict[str, bool] = {}

    def _is_materialized(spec: dict[str, Any]) -> bool:
        storage = spec.get("storage", {})
        materialize = spec.get("materialize")
        return bool(storage.get("tiled", True)) and materialize in (None, "on_packager")

    visiting: set[str] = set()

    def _has_materialized_ancestor(metric_id: str) -> bool:
        cached = memo.get(metric_id)
        if cached is not None:
            return cached
        if metric_id in visiting:
            memo[metric_id] = False
            return False
        visiting.add(metric_id)
        spec = metrics.get(metric_id)
        if spec is None:
            visiting.discard(metric_id)
            memo[metric_id] = False
            return False
        if _is_materialized(spec):
            visiting.discard(metric_id)
            memo[metric_id] = True
            return True
        source = spec.get("source", {})
        if source.get("type") != "derived":
            visiting.discard(metric_id)
            memo[metric_id] = False
            return False
        inputs = source.get("inputs", []) or []
        ok = any(_has_materialized_ancestor(str(dep)) for dep in inputs)
        visiting.discard(metric_id)
        memo[metric_id] = ok
        return ok

    errors: list[str] = []
    for panel_id, panel in panels_root.items():
        graphs = panel.get("graphs", []) if isinstance(panel, dict) else []
        for graph in graphs:
            graph_id = graph.get("id", "<graph>")
            series_list = graph.get("series", []) if isinstance(graph, dict) else []
            for series in series_list:
                metric_id = series.get("metric")
                if metric_id not in metrics:
                    errors.append(
                        f"panels/{panel_id}/graphs/{graph_id}: unknown metric '{metric_id}'"
                    )
                    continue
                if not _has_materialized_ancestor(metric_id):
                    errors.append(
                        f"panels/{panel_id}/graphs/{graph_id}: metric '{metric_id}' "
                        "has no materialized ancestor"
                    )
    if errors:
        raise PanelsSchemaError(
            "panels.json failed metric linkage validation:\n- " + "\n- ".join(errors)
        )


def _error_sort_key(error) -> tuple[int, str]:
    return (len(error.path), "/".join(str(p) for p in error.path))


def _format_error(error) -> str:
    path = "/".join(str(p) for p in error.path)
    if path:
        return f"- {path}: {error.message}"
    return f"- {error.message}"
