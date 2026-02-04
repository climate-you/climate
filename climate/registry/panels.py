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


def _error_sort_key(error) -> tuple[int, str]:
    return (len(error.path), "/".join(str(p) for p in error.path))


def _format_error(error) -> str:
    path = "/".join(str(p) for p in error.path)
    if path:
        return f"- {path}: {error.message}"
    return f"- {error.message}"
