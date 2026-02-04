from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA_PATH = Path(__file__).with_name("metrics.schema.json")
DEFAULT_METRICS_PATH = REPO_ROOT / "registry" / "metrics.json"


class MetricsSchemaError(ValueError):
    pass


def load_schema(path: Path | str = DEFAULT_SCHEMA_PATH) -> dict[str, Any]:
    schema_path = Path(path)
    with schema_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_metrics(
    path: Path | str = DEFAULT_METRICS_PATH,
    *,
    schema_path: Path | str = DEFAULT_SCHEMA_PATH,
    validate: bool = True,
) -> dict[str, Any]:
    metrics_path = Path(path)
    with metrics_path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)

    if validate:
        schema = load_schema(schema_path)
        validate_metrics(manifest, schema)

    return manifest


def validate_metrics(manifest: dict[str, Any], schema: dict[str, Any]) -> None:
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(manifest), key=_error_sort_key)
    if errors:
        formatted = "\n".join(_format_error(err) for err in errors)
        raise MetricsSchemaError(f"metrics.json failed schema validation:\n{formatted}")

    _validate_ids_match_keys(manifest)


def _validate_ids_match_keys(manifest: dict[str, Any]) -> None:
    mismatches: list[str] = []
    for key, spec in manifest.items():
        if key == "version":
            continue
        if isinstance(spec, dict) and "id" in spec and spec["id"] != key:
            mismatches.append(f"{key} -> id: {spec['id']}")

    if mismatches:
        raise MetricsSchemaError(
            "metrics.json has id fields that do not match their keys:\n"
            + "\n".join(mismatches)
        )


def _error_sort_key(error) -> tuple[int, str]:
    return (len(error.path), "/".join(str(p) for p in error.path))


def _format_error(error) -> str:
    path = "/".join(str(p) for p in error.path)
    if path:
        return f"- {path}: {error.message}"
    return f"- {error.message}"
