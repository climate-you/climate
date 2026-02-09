from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .metrics import REPO_ROOT

DEFAULT_MAPS_PATH = REPO_ROOT / "registry" / "maps.json"
DEFAULT_MAPS_SCHEMA_PATH = Path(__file__).with_name("maps.schema.json")


class MapsSchemaError(ValueError):
    pass


def load_maps_schema(path: Path | str = DEFAULT_MAPS_SCHEMA_PATH) -> dict[str, Any]:
    schema_path = Path(path)
    with schema_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_maps(
    path: Path | str = DEFAULT_MAPS_PATH,
    *,
    schema_path: Path | str = DEFAULT_MAPS_SCHEMA_PATH,
    validate: bool = True,
) -> dict[str, Any]:
    maps_path = Path(path)
    with maps_path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)

    if validate:
        schema = load_maps_schema(schema_path)
        validate_maps(manifest, schema)

    return manifest


def validate_maps(manifest: dict[str, Any], schema: dict[str, Any]) -> None:
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(manifest), key=_error_sort_key)
    if errors:
        formatted = "\n".join(_format_error(err) for err in errors)
        raise MapsSchemaError(f"maps.json failed schema validation:\n{formatted}")

    _validate_ids_match_keys(manifest, manifest_name="maps.json")


def validate_maps_against_metrics(
    maps_manifest: dict[str, Any], metrics_manifest: dict[str, Any]
) -> None:
    metrics = {
        key: spec
        for key, spec in metrics_manifest.items()
        if key != "version" and isinstance(spec, dict)
    }
    maps_root = {
        key: spec
        for key, spec in maps_manifest.items()
        if key != "version" and isinstance(spec, dict)
    }

    errors: list[str] = []
    for map_id, spec in maps_root.items():
        source_metric = spec.get("source_metric")
        if source_metric is None:
            continue
        if source_metric not in metrics:
            errors.append(f"{map_id}: unknown source_metric '{source_metric}'")
            continue

        metric = metrics[source_metric]
        storage = metric.get("storage", {})
        if not storage.get("tiled", True) or metric.get("materialize") not in (
            None,
            "on_packager",
        ):
            errors.append(
                f"{map_id}: source_metric '{source_metric}' is not materialized as tiled data"
            )

        map_grid_id = spec.get("grid_id")
        metric_grid_id = metric.get("grid_id")
        if map_grid_id and metric_grid_id and map_grid_id != metric_grid_id:
            errors.append(
                f"{map_id}: grid_id '{map_grid_id}' does not match source_metric grid_id "
                f"'{metric_grid_id}'"
            )

    if errors:
        raise MapsSchemaError(
            "maps.json failed metric linkage validation:\n- " + "\n- ".join(errors)
        )


def _validate_ids_match_keys(manifest: dict[str, Any], *, manifest_name: str) -> None:
    mismatches: list[str] = []
    for key, spec in manifest.items():
        if key == "version":
            continue
        if isinstance(spec, dict) and "id" in spec and spec["id"] != key:
            mismatches.append(f"{key} -> id: {spec['id']}")

    if mismatches:
        raise MapsSchemaError(
            f"{manifest_name} has id fields that do not match their keys:\n"
            + "\n".join(mismatches)
        )


def _error_sort_key(error) -> tuple[int, str]:
    return (len(error.path), "/".join(str(p) for p in error.path))


def _format_error(error) -> str:
    path = "/".join(str(p) for p in error.path)
    if path:
        return f"- {path}: {error.message}"
    return f"- {error.message}"
