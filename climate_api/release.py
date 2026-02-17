from __future__ import annotations

import functools
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from climate.registry.maps import load_maps, validate_maps_against_metrics
from climate.registry.metrics import load_metrics
from climate.registry.panels import (
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
        registry_root = release_root / "registry"
        metrics_path = registry_root / "metrics.json"
        datasets_path = registry_root / "datasets.json"
        maps_path = registry_root / "maps.json"
        panels_path = registry_root / "panels.json"
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
