from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .metrics import REPO_ROOT

DEFAULT_LAYERS_PATH = REPO_ROOT / "registry" / "layers.json"
DEFAULT_LAYERS_SCHEMA_PATH = Path(__file__).with_name("layers.schema.json")


class LayersSchemaError(ValueError):
    pass


def load_layers_schema(path: Path | str = DEFAULT_LAYERS_SCHEMA_PATH) -> dict[str, Any]:
    schema_path = Path(path)
    with schema_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_layers(
    path: Path | str = DEFAULT_LAYERS_PATH,
    *,
    schema_path: Path | str = DEFAULT_LAYERS_SCHEMA_PATH,
    validate: bool = True,
) -> dict[str, Any]:
    layers_path = Path(path)
    with layers_path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)

    if validate:
        schema = load_layers_schema(schema_path)
        validate_layers(manifest, schema)

    return manifest


def validate_layers(manifest: dict[str, Any], schema: dict[str, Any]) -> None:
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(manifest), key=_error_sort_key)
    if errors:
        formatted = "\n".join(_format_error(err) for err in errors)
        raise LayersSchemaError(f"layers.json failed schema validation:\n{formatted}")

    _validate_ids_match_keys(manifest, manifest_name="layers.json")


def validate_layers_against_maps(
    layers_manifest: dict[str, Any], maps_manifest: dict[str, Any]
) -> None:
    maps = {
        key: spec
        for key, spec in maps_manifest.items()
        if key != "version" and isinstance(spec, dict)
    }
    layers = {
        key: spec
        for key, spec in layers_manifest.items()
        if key != "version" and isinstance(spec, dict)
    }

    errors: list[str] = []
    for layer_id, spec in layers.items():
        map_id = spec.get("map_id")
        if not isinstance(map_id, str) or not map_id:
            errors.append(f"{layer_id}: missing map_id")
            continue
        map_spec = maps.get(map_id)
        if map_spec is None:
            errors.append(f"{layer_id}: unknown map_id '{map_id}'")
            continue
        if map_spec.get("type") != "texture":
            errors.append(
                f"{layer_id}: map_id '{map_id}' has type '{map_spec.get('type')}', "
                "expected 'texture'"
            )

    if errors:
        raise LayersSchemaError(
            "layers.json failed map linkage validation:\n- " + "\n- ".join(errors)
        )


def _validate_ids_match_keys(manifest: dict[str, Any], *, manifest_name: str) -> None:
    mismatches: list[str] = []
    for key, spec in manifest.items():
        if key == "version":
            continue
        if isinstance(spec, dict) and "id" in spec and spec["id"] != key:
            mismatches.append(f"{key} -> id: {spec['id']}")

    if mismatches:
        raise LayersSchemaError(
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
