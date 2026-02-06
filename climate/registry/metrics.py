from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA_PATH = Path(__file__).with_name("metrics.schema.json")
DEFAULT_METRICS_PATH = REPO_ROOT / "registry" / "metrics.json"
DEFAULT_DATASETS_SCHEMA_PATH = Path(__file__).with_name("datasets.schema.json")
DEFAULT_DATASETS_PATH = REPO_ROOT / "registry" / "datasets.json"


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
    datasets_path: Path | str = DEFAULT_DATASETS_PATH,
    datasets_schema_path: Path | str = DEFAULT_DATASETS_SCHEMA_PATH,
    validate: bool = True,
) -> dict[str, Any]:
    metrics_path = Path(path)
    with metrics_path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)

    if validate:
        schema = load_schema(schema_path)
        validate_metrics(manifest, schema)

    datasets = load_datasets(
        path=datasets_path, schema_path=datasets_schema_path, validate=validate
    )
    manifest = _apply_dataset_refs(manifest, datasets)
    return manifest


def load_datasets(
    path: Path | str = DEFAULT_DATASETS_PATH,
    *,
    schema_path: Path | str = DEFAULT_DATASETS_SCHEMA_PATH,
    validate: bool = True,
) -> dict[str, Any]:
    datasets_path = Path(path)
    if not datasets_path.exists():
        return {}
    with datasets_path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    if validate:
        schema = load_schema(schema_path)
        validate_datasets(manifest, schema)
    return manifest


def validate_datasets(manifest: dict[str, Any], schema: dict[str, Any]) -> None:
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(manifest), key=_error_sort_key)
    if errors:
        formatted = "\n".join(_format_error(err) for err in errors)
        raise MetricsSchemaError(f"datasets.json failed schema validation:\n{formatted}")
    _validate_ids_match_keys(manifest)


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


def _apply_dataset_refs(
    metrics: dict[str, Any], datasets: dict[str, Any]
) -> dict[str, Any]:
    if not datasets:
        return metrics

    def _merge_source(source: dict[str, Any]) -> dict[str, Any]:
        dataset_ref = source.get("dataset_ref")
        if not dataset_ref:
            return source
        dataset = datasets.get(dataset_ref)
        if not dataset:
            raise MetricsSchemaError(f"Unknown dataset_ref: {dataset_ref}")
        ds_source = dict(dataset.get("source", {}))
        if not ds_source:
            raise MetricsSchemaError(
                f"dataset_ref {dataset_ref} missing source definition"
            )
        if ds_source.get("type") != source.get("type"):
            raise MetricsSchemaError(
                f"dataset_ref {dataset_ref} type mismatch: "
                f"{ds_source.get('type')} != {source.get('type')}"
            )
        merged = dict(ds_source)
        merged.update({k: v for k, v in source.items() if k != "dataset_ref"})
        return merged

    out: dict[str, Any] = dict(metrics)
    for key, spec in metrics.items():
        if key == "version":
            continue
        if not isinstance(spec, dict):
            continue
        source = spec.get("source")
        if isinstance(source, dict):
            merged = _merge_source(source)
            if merged is not source:
                spec = dict(spec)
                spec["source"] = merged
                out[key] = spec
    return out


def _error_sort_key(error) -> tuple[int, str]:
    return (len(error.path), "/".join(str(p) for p in error.path))


def _format_error(error) -> str:
    path = "/".join(str(p) for p in error.path)
    if path:
        return f"- {path}: {error.message}"
    return f"- {error.message}"
