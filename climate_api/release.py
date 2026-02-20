from __future__ import annotations

import functools
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from climate.registry.layers import (
    DEFAULT_LAYERS_PATH,
    load_layers,
    validate_layers_against_maps,
)
from climate.registry.maps import (
    DEFAULT_MAPS_PATH,
    load_maps,
    validate_maps_against_metrics,
)
from climate.registry.metrics import (
    DEFAULT_DATASETS_PATH,
    DEFAULT_METRICS_PATH,
    load_metrics,
)
from climate.registry.panels import (
    DEFAULT_PANELS_PATH,
    load_panels,
    validate_panels_against_maps,
    validate_panels_against_metrics,
)

from .config import Settings
from .services.panels import preload_score_maps_cache
from .store.tile_data_store import TileDataStore

_RELEASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True)
class ReleaseContext:
    release: str
    release_root: Path
    tile_store: TileDataStore
    panels_manifest: dict[str, Any]
    maps_manifest: dict[str, Any]
    maps_root: Path
    layers: list[dict[str, Any]]


def _resolve_texture_file_format(map_spec: dict[str, Any]) -> str:
    explicit = map_spec.get("file_format")
    output = map_spec.get("output", {}) or {}
    filename = output.get("filename")
    if isinstance(filename, str):
        suffix = Path(filename).suffix.lower()
        if suffix in (".png", ".webp"):
            suffix_format = suffix[1:]
            if explicit is None:
                return suffix_format
            explicit_norm = str(explicit).strip().lower()
            if explicit_norm != suffix_format:
                raise ValueError(
                    f"Texture output filename extension '.{suffix_format}' does not match "
                    f"file_format '{explicit_norm}'."
                )
            return explicit_norm
    if explicit is None:
        return "png"
    explicit_norm = str(explicit).strip().lower()
    if explicit_norm not in ("png", "webp"):
        raise ValueError(
            f"Unsupported texture file_format '{explicit}'. Expected one of: png, webp."
        )
    return explicit_norm


def _resolve_texture_filename(*, map_id: str, map_spec: dict[str, Any]) -> str:
    output = map_spec.get("output", {}) or {}
    filename = output.get("filename")
    file_format = _resolve_texture_file_format(map_spec)
    if isinstance(filename, str) and filename:
        if Path(filename).suffix:
            return filename
        return f"{filename}.{file_format}"
    return f"{map_id}.{file_format}"


def _build_release_layers(
    *,
    layers_manifest: dict[str, Any],
    maps_manifest: dict[str, Any],
    metrics_manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    maps = {
        key: spec
        for key, spec in maps_manifest.items()
        if key != "version" and isinstance(spec, dict)
    }
    metrics = {
        key: spec
        for key, spec in metrics_manifest.items()
        if key != "version" and isinstance(spec, dict)
    }
    out: list[dict[str, Any]] = []
    for layer_id, layer_spec in layers_manifest.items():
        if layer_id == "version" or not isinstance(layer_spec, dict):
            continue
        map_id = str(layer_spec["map_id"])
        map_spec = maps.get(map_id)
        if map_spec is None:
            raise ValueError(f"Layer '{layer_id}' references unknown map_id '{map_id}'.")
        if map_spec.get("type") != "texture":
            raise ValueError(
                f"Layer '{layer_id}' references non-texture map_id '{map_id}'."
            )
        source_metric = str(map_spec.get("source_metric", ""))
        metric_spec = metrics.get(source_metric)
        if not isinstance(metric_spec, dict):
            raise ValueError(
                f"Map '{map_id}' references unknown source_metric '{source_metric}'."
            )
        grid_id = str(map_spec.get("grid_id") or metric_spec.get("grid_id") or "")
        if not grid_id:
            raise ValueError(f"Map '{map_id}' does not define a grid_id.")
        filename = _resolve_texture_filename(map_id=map_id, map_spec=map_spec)
        descriptor: dict[str, Any] = {
            "id": str(layer_spec["id"]),
            "label": str(layer_spec["label"]),
            "map_id": map_id,
            "asset_path": f"maps/{grid_id}/{map_id}/{filename}",
        }
        if "description" in layer_spec:
            descriptor["description"] = layer_spec.get("description")
        if "icon" in layer_spec:
            descriptor["icon"] = layer_spec.get("icon")
        if "opacity" in layer_spec:
            descriptor["opacity"] = layer_spec.get("opacity")
        if "legend" in layer_spec:
            descriptor["legend"] = layer_spec.get("legend")
        out.append(descriptor)
    return out


class ReleaseResolver:
    def __init__(self, *, settings: Settings, logger: logging.Logger) -> None:
        self._settings = settings
        self._logger = logger
        self._releases_root_resolved = settings.releases_root.resolve()

    def _validate_release_id(self, release: str) -> str:
        candidate = str(release).strip()
        if not candidate:
            raise HTTPException(status_code=400, detail="Release id cannot be empty.")
        if not _RELEASE_ID_PATTERN.fullmatch(candidate):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Invalid release id. Allowed characters: letters, digits, '.', '_', '-'."
                ),
            )
        return candidate

    def resolve_release_alias(self, requested_release: str) -> str:
        requested = self._validate_release_id(requested_release)
        if requested != "latest":
            return requested

        latest_file = self._settings.latest_release_file
        if not latest_file.exists():
            return "dev"
        resolved = latest_file.read_text(encoding="utf-8").strip()
        if not resolved:
            raise HTTPException(
                status_code=500,
                detail=f"Latest release pointer is empty: {latest_file}",
            )
        return self._validate_release_id(resolved)

    def release_root(self, canonical_release: str) -> Path:
        candidate = (self._settings.releases_root / canonical_release).resolve()
        try:
            candidate.relative_to(self._releases_root_resolved)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid release path.") from exc
        if not candidate.exists() or not candidate.is_dir():
            raise HTTPException(
                status_code=404,
                detail=f"Unknown release: {canonical_release}",
            )
        return candidate

    @functools.lru_cache(maxsize=32)
    def _load_release_context(self, canonical_release: str) -> ReleaseContext:
        release_root = self.release_root(canonical_release)
        if canonical_release == "dev":
            manifest_path = release_root / "manifest.json"
            registry_root = release_root / "registry"
            self._logger.info(
                "Release %s uses repo-root registry files for development mode.",
                canonical_release,
            )
            if manifest_path.exists():
                self._logger.warning(
                    "Development release ignores manifest file at %s.",
                    manifest_path,
                )
            if registry_root.exists():
                self._logger.warning(
                    "Development release ignores release-scoped registry directory at %s.",
                    registry_root,
                )
            metrics_path = DEFAULT_METRICS_PATH
            datasets_path = DEFAULT_DATASETS_PATH
            maps_path = DEFAULT_MAPS_PATH
            panels_path = DEFAULT_PANELS_PATH
            layers_path = DEFAULT_LAYERS_PATH
        else:
            registry_root = release_root / "registry"
            metrics_path = registry_root / "metrics.json"
            datasets_path = registry_root / "datasets.json"
            maps_path = registry_root / "maps.json"
            panels_path = registry_root / "panels.json"
            layers_path = registry_root / "layers.json"
        for required_path in (metrics_path, datasets_path, maps_path, panels_path):
            if not required_path.exists():
                raise FileNotFoundError(
                    f"Release '{canonical_release}' is missing required file: {required_path}"
                )

        metrics_manifest = load_metrics(
            path=metrics_path,
            datasets_path=datasets_path,
            validate=True,
        )
        tile_store = TileDataStore.discover(
            release_root / "series",
            start_year_fallback=1979,
            metrics_path=metrics_path,
            datasets_path=datasets_path,
        )
        panels_manifest = load_panels(path=panels_path, validate=True)
        maps_manifest = load_maps(path=maps_path, validate=True)
        validate_maps_against_metrics(maps_manifest, metrics_manifest)
        validate_panels_against_metrics(panels_manifest, metrics_manifest)
        validate_panels_against_maps(panels_manifest, maps_manifest)
        layers: list[dict[str, Any]] = []
        if layers_path.exists():
            layers_manifest = load_layers(path=layers_path, validate=True)
            validate_layers_against_maps(layers_manifest, maps_manifest)
            layers = _build_release_layers(
                layers_manifest=layers_manifest,
                maps_manifest=maps_manifest,
                metrics_manifest=metrics_manifest,
            )
        else:
            self._logger.warning(
                "Release %s has no layers registry at %s; returning empty layers list.",
                canonical_release,
                layers_path,
            )

        maps_root = release_root / "maps"
        if self._settings.score_map_preload:
            loaded_count, skipped_constant_count = preload_score_maps_cache(
                maps_manifest=maps_manifest,
                tile_store=tile_store,
                maps_root=maps_root,
            )
            self._logger.info(
                "Preloaded score maps for release %s: loaded=%d skipped_constant=%d",
                canonical_release,
                loaded_count,
                skipped_constant_count,
            )

        return ReleaseContext(
            release=canonical_release,
            release_root=release_root,
            tile_store=tile_store,
            panels_manifest=panels_manifest,
            maps_manifest=maps_manifest,
            maps_root=maps_root,
            layers=layers,
        )

    def resolve_release_context(self, requested_release: str) -> ReleaseContext:
        canonical_release = self.resolve_release_alias(requested_release)
        try:
            return self._load_release_context(canonical_release)
        except HTTPException:
            raise
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
