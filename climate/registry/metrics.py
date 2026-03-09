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


_SOURCE_DOWNLOAD_FIELDS = {
    "dataset",
    "dataset_id",
    "dataset_key",
    "variable",
    "postprocess",
    "block_years",
    "block_months",
    "batch_tiles",
    "time_range",
    "stride_time",
    "stride_lat",
    "stride_lon",
    "mask_file",
}


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
    if validate:
        validate_metric_dependencies(manifest)
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
        raise MetricsSchemaError(
            f"datasets.json failed schema validation:\n{formatted}"
        )
    _validate_ids_match_keys(manifest, manifest_name="datasets.json")


def validate_metrics(manifest: dict[str, Any], schema: dict[str, Any]) -> None:
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(manifest), key=_error_sort_key)
    if errors:
        formatted = "\n".join(_format_error(err) for err in errors)
        raise MetricsSchemaError(f"metrics.json failed schema validation:\n{formatted}")

    _validate_ids_match_keys(manifest, manifest_name="metrics.json")


def _validate_ids_match_keys(manifest: dict[str, Any], *, manifest_name: str) -> None:
    mismatches: list[str] = []
    for key, spec in manifest.items():
        if key == "version":
            continue
        if isinstance(spec, dict) and "id" in spec and spec["id"] != key:
            mismatches.append(f"{key} -> id: {spec['id']}")

    if mismatches:
        raise MetricsSchemaError(
            f"{manifest_name} has id fields that do not match their keys:\n"
            + "\n".join(mismatches)
        )


def _apply_dataset_refs(
    metrics: dict[str, Any], datasets: dict[str, Any]
) -> dict[str, Any]:
    out: dict[str, Any] = dict(metrics)

    for key, spec in metrics.items():
        if key == "version" or not isinstance(spec, dict):
            continue

        source = spec.get("source")
        if not isinstance(source, dict):
            continue

        source_type = source.get("type")
        if source_type in {"cds", "erddap"} and not source.get("dataset_ref"):
            raise MetricsSchemaError(
                f"Metric {key} source.type={source_type} must set dataset_ref."
            )

        dataset_ref = source.get("dataset_ref")
        if not dataset_ref:
            out[key] = dict(spec)
            continue

        dataset = datasets.get(dataset_ref)
        if not isinstance(dataset, dict):
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

        merged_source = dict(ds_source)
        metric_time_range = source.get("time_range")
        for k2, v2 in source.items():
            if k2 in {"dataset_ref", "time_range"}:
                continue
            if k2 in _SOURCE_DOWNLOAD_FIELDS:
                continue
            if (
                k2 == "params"
                and isinstance(merged_source.get("params"), dict)
                and isinstance(v2, dict)
            ):
                merged_params = dict(merged_source.get("params", {}))
                merged_params.update(v2)
                merged_source["params"] = merged_params
                continue
            merged_source[k2] = v2
        if isinstance(metric_time_range, dict):
            merged_source["_analysis_time_range"] = metric_time_range
        merged_source["_dataset_ref"] = dataset_ref

        merged_spec = dict(spec)
        merged_spec["source"] = merged_source

        ds_grid_id = dataset.get("grid_id")
        if ds_grid_id is not None:
            metric_grid_id = merged_spec.get("grid_id")
            if metric_grid_id is None:
                merged_spec["grid_id"] = ds_grid_id
            elif metric_grid_id != ds_grid_id:
                raise MetricsSchemaError(
                    f"Metric {key} grid_id={metric_grid_id} does not match "
                    f"dataset_ref {dataset_ref} grid_id={ds_grid_id}."
                )

        ds_tile_size = dataset.get("tile_size")
        if ds_tile_size is not None:
            storage = dict(merged_spec.get("storage", {}))
            metric_tile_size = storage.get("tile_size")
            if metric_tile_size is None:
                storage["tile_size"] = ds_tile_size
            elif int(metric_tile_size) != int(ds_tile_size):
                raise MetricsSchemaError(
                    f"Metric {key} storage.tile_size={metric_tile_size} does not match "
                    f"dataset_ref {dataset_ref} tile_size={ds_tile_size}."
                )
            merged_spec["storage"] = storage

        out[key] = merged_spec

    return _apply_derived_inheritance(out)


def _apply_derived_inheritance(metrics: dict[str, Any]) -> dict[str, Any]:
    out = dict(metrics)
    for key, spec in metrics.items():
        if key == "version" or not isinstance(spec, dict):
            continue
        source = spec.get("source")
        if not isinstance(source, dict) or source.get("type") != "derived":
            continue

        inputs = source.get("inputs", [])
        if not inputs:
            continue
        input_specs = []
        for input_id in inputs:
            input_spec = out.get(input_id)
            if not isinstance(input_spec, dict):
                raise MetricsSchemaError(
                    f"Metric {key} references missing input metric: {input_id}"
                )
            input_specs.append(input_spec)

        base_grid = input_specs[0].get("grid_id")
        base_tile_size = (
            input_specs[0].get("storage", {}).get("tile_size")
            if isinstance(input_specs[0].get("storage"), dict)
            else None
        )
        for input_id, input_spec in zip(inputs[1:], input_specs[1:]):
            grid_id = input_spec.get("grid_id")
            tile_size = (
                input_spec.get("storage", {}).get("tile_size")
                if isinstance(input_spec.get("storage"), dict)
                else None
            )
            if grid_id != base_grid:
                raise MetricsSchemaError(
                    f"Metric {key} derived inputs have mismatched grid_id: "
                    f"{inputs[0]}={base_grid}, {input_id}={grid_id}"
                )
            if tile_size != base_tile_size:
                raise MetricsSchemaError(
                    f"Metric {key} derived inputs have mismatched tile_size: "
                    f"{inputs[0]}={base_tile_size}, {input_id}={tile_size}"
                )

        merged = dict(spec)
        if merged.get("grid_id") is None and base_grid is not None:
            merged["grid_id"] = base_grid
        elif (
            merged.get("grid_id") is not None
            and base_grid is not None
            and merged.get("grid_id") != base_grid
        ):
            raise MetricsSchemaError(
                f"Metric {key} grid_id={merged.get('grid_id')} does not match "
                f"derived input grid_id={base_grid}"
            )

        storage = dict(merged.get("storage", {}))
        metric_tile_size = storage.get("tile_size")
        if metric_tile_size is None and base_tile_size is not None:
            storage["tile_size"] = base_tile_size
        elif (
            metric_tile_size is not None
            and base_tile_size is not None
            and int(metric_tile_size) != int(base_tile_size)
        ):
            raise MetricsSchemaError(
                f"Metric {key} storage.tile_size={metric_tile_size} does not match "
                f"derived input tile_size={base_tile_size}"
            )
        if storage:
            merged["storage"] = storage

        base_domain = input_specs[0].get("domain")
        for input_id, input_spec in zip(inputs[1:], input_specs[1:]):
            input_domain = input_spec.get("domain")
            if base_domain is None or input_domain is None:
                continue
            if input_domain != base_domain:
                raise MetricsSchemaError(
                    f"Metric {key} derived inputs have mismatched domain: "
                    f"{inputs[0]}={base_domain}, {input_id}={input_domain}"
                )
        if merged.get("domain") is None and base_domain is not None:
            merged["domain"] = base_domain
        elif (
            merged.get("domain") is not None
            and base_domain is not None
            and merged.get("domain") != base_domain
        ):
            raise MetricsSchemaError(
                f"Metric {key} domain={merged.get('domain')} does not match "
                f"derived input domain={base_domain}"
            )

        out[key] = merged

    return out


def validate_metric_dependencies(manifest: dict[str, Any]) -> None:
    metrics = {
        key: spec
        for key, spec in manifest.items()
        if key != "version" and isinstance(spec, dict)
    }

    deps: dict[str, list[str]] = {}
    for metric_id, spec in metrics.items():
        source = spec.get("source", {})
        source_type = source.get("type")
        if source_type == "derived":
            inputs = source.get("inputs", [])
            if not isinstance(inputs, list) or not inputs:
                raise MetricsSchemaError(
                    f"Metric {metric_id} derived source must define non-empty inputs"
                )
            deps[metric_id] = [str(x) for x in inputs]
        else:
            deps[metric_id] = []

    state: dict[str, int] = {}
    stack: list[str] = []

    def _visit(node: str) -> None:
        s = state.get(node, 0)
        if s == 1:
            if node in stack:
                i = stack.index(node)
                cycle = stack[i:] + [node]
                raise MetricsSchemaError(
                    "Cyclic metric dependency detected: " + " -> ".join(cycle)
                )
            raise MetricsSchemaError(f"Cyclic metric dependency detected at {node}")
        if s == 2:
            return

        state[node] = 1
        stack.append(node)
        for dep in deps.get(node, []):
            if dep not in metrics:
                raise MetricsSchemaError(
                    f"Metric {node} depends on missing metric: {dep}"
                )
            _visit(dep)
        stack.pop()
        state[node] = 2

    for metric_id in metrics:
        _visit(metric_id)

    memo: dict[str, bool] = {}

    def _has_dataset_ancestor(metric_id: str) -> bool:
        cached = memo.get(metric_id)
        if cached is not None:
            return cached
        spec = metrics[metric_id]
        source = spec.get("source", {})
        source_type = source.get("type")
        if source_type in {"cds", "erddap"}:
            ok = bool(source.get("_dataset_ref") or source.get("dataset_ref"))
            memo[metric_id] = ok
            return ok
        if source_type == "derived":
            ok = any(_has_dataset_ancestor(dep) for dep in deps[metric_id])
            memo[metric_id] = ok
            return ok
        memo[metric_id] = False
        return False

    missing = [m for m in metrics if not _has_dataset_ancestor(m)]
    if missing:
        raise MetricsSchemaError(
            "Metrics without dataset ancestor: " + ", ".join(sorted(missing))
        )

    def _dataset_mask_file(metric_id: str) -> str | None:
        spec = metrics[metric_id]
        source = spec.get("source", {})
        source_type = source.get("type")
        if source_type in {"cds", "erddap"}:
            mask_file = source.get("mask_file")
            if isinstance(mask_file, str) and mask_file.strip():
                return mask_file
            return None
        if source_type == "derived":
            files: set[str] = set()
            for dep in deps[metric_id]:
                dep_mask = _dataset_mask_file(dep)
                if dep_mask:
                    files.add(dep_mask)
            if not files:
                return None
            if len(files) > 1:
                raise MetricsSchemaError(
                    f"Metric {metric_id} domain=dataset_mask has multiple dataset masks in ancestry: "
                    + ", ".join(sorted(files))
                )
            return next(iter(files))
        return None

    missing_dataset_mask = [
        m
        for m, spec in metrics.items()
        if spec.get("domain") == "dataset_mask" and not _dataset_mask_file(m)
    ]
    if missing_dataset_mask:
        raise MetricsSchemaError(
            "Metrics with domain=dataset_mask must have a dataset source.mask_file in their ancestry: "
            + ", ".join(sorted(missing_dataset_mask))
        )


def _error_sort_key(error) -> tuple[int, str]:
    return (len(error.path), "/".join(str(p) for p in error.path))


def _format_error(error) -> str:
    path = "/".join(str(p) for p in error.path)
    if path:
        return f"- {path}: {error.message}"
    return f"- {error.message}"
