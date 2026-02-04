from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import json
import numpy as np

from climate.registry.metrics import DEFAULT_METRICS_PATH, DEFAULT_SCHEMA_PATH, REPO_ROOT, load_metrics
from climate.tiles.layout import GridSpec, locate_tile, tile_path
from climate.tiles.spec import read_cell_series


def _grid_from_id(grid_id: str, *, tile_size: int) -> GridSpec:
    if grid_id == "global_0p25":
        return GridSpec.global_0p25(tile_size=tile_size)
    raise RuntimeError(f"Unknown grid_id={grid_id}. Add a mapping in TileDataStore.")


def _load_registry_metrics(
    metrics_path: Path | str | None,
    schema_path: Path | str | None,
) -> tuple[dict[str, dict[str, Any]], dict[str, GridSpec]]:
    if metrics_path is None:
        return {}, {}
    path = Path(metrics_path)
    if not path.exists():
        return {}, {}
    schema = Path(schema_path) if schema_path is not None else DEFAULT_SCHEMA_PATH
    manifest = load_metrics(path=path, schema_path=schema, validate=True)

    metrics: dict[str, dict[str, Any]] = {}
    grids: dict[str, GridSpec] = {}
    for metric_id, spec in manifest.items():
        if metric_id == "version":
            continue
        if not isinstance(spec, dict):
            continue
        storage = spec.get("storage", {})
        if not storage.get("tiled", True):
            continue
        if spec.get("materialize") not in (None, "on_packager"):
            continue
        metrics[metric_id] = spec

        grid_id = spec.get("grid_id")
        if not grid_id:
            continue
        tile_size = int(storage.get("tile_size", 64))
        if grid_id not in grids:
            grids[grid_id] = _grid_from_id(grid_id, tile_size=tile_size)

    return metrics, grids


@dataclass(frozen=True)
class TileDataStore:
    """
    Tiles are the source of truth for climate metrics.

    tiles_root points at ".../series" so we can build:
      {tiles_root}/{grid_id}/{metric}/z64/rXXX_cYYY.bin.zst
    """

    tiles_root: Path
    grid: GridSpec
    start_year_fallback: int = 1979  # used only if yearly.json missing
    metrics: dict[str, dict[str, Any]] = field(default_factory=dict)
    grids: dict[str, GridSpec] = field(default_factory=dict)

    @classmethod
    def discover(
        cls,
        tiles_root: Path,
        *,
        start_year_fallback: int = 1979,
        metrics_path: Path | str | None = DEFAULT_METRICS_PATH,
        schema_path: Path | str | None = DEFAULT_SCHEMA_PATH,
    ) -> "TileDataStore":
        """
        Discover grid_id and tile_size from folder layout.

        Expected layout:
          {tiles_root}/{grid_id}/{metric}/z{tile_size}/rXXX_cYYY.bin.zst
        """
        tiles_root = Path(tiles_root)
        metrics, grids = _load_registry_metrics(metrics_path, schema_path)
        if grids:
            grid = grids.get("global_0p25") or next(iter(grids.values()))
            return cls(
                tiles_root=tiles_root,
                grid=grid,
                start_year_fallback=int(start_year_fallback),
                metrics=metrics,
                grids=grids,
            )

        # pick first grid directory (or prefer global_0p25 if present)
        grids = sorted([p for p in tiles_root.iterdir() if p.is_dir()])
        if not grids:
            raise RuntimeError(f"No grid folders found under tiles_root={tiles_root}")

        grid_dir = None
        for p in grids:
            if p.name == "global_0p25":
                grid_dir = p
                break
        if grid_dir is None:
            grid_dir = grids[0]

        grid_id = grid_dir.name

        # find a metric dir that has a zNN folder
        metric_dirs = sorted([p for p in grid_dir.iterdir() if p.is_dir()])
        zdir = None
        for md in metric_dirs:
            for child in md.iterdir():
                if (
                    child.is_dir()
                    and child.name.startswith("z")
                    and child.name[1:].isdigit()
                ):
                    zdir = child
                    break
            if zdir is not None:
                break
        if zdir is None:
            raise RuntimeError(
                f"Could not find any zNN folder under grid={grid_id} in {grid_dir}"
            )

        tile_size = int(zdir.name[1:])

        # Convert grid_id -> GridSpec (centralize the knowledge here, not in main)
        if grid_id == "global_0p25":
            grid = GridSpec.global_0p25(tile_size=tile_size)
        else:
            raise RuntimeError(
                f"Unknown grid_id={grid_id}. Add a mapping in TileDataStore.discover()."
            )

        return cls(
            tiles_root=tiles_root,
            grid=grid,
            start_year_fallback=int(start_year_fallback),
            grids={grid_id: grid},
        )

    def yearly_axis(self, metric: str) -> list[int]:
        """
        Returns list of int years for a given yearly metric.
        Expected file (per-metric axis):
        {tiles_root}/{grid_id}/{metric}/time/yearly.json

        (Optional backward-compat: if the per-metric file is missing, also try the old
        grid-level path for a while.)
        """
        axis = self.axis(metric)
        if axis and any(isinstance(v, str) for v in axis):
            raise ValueError(f"Expected numeric years for metric={metric}, got strings")
        return [int(v) for v in axis]

    def axis(self, metric: str) -> list[Any]:
        spec = self.metrics.get(metric)
        axis_name = None
        if spec is not None:
            axis_name = spec.get("time_axis")
            axis_spec = spec.get("axis")
            if isinstance(axis_spec, dict):
                if "values" in axis_spec:
                    return list(axis_spec["values"])
                if "path" in axis_spec:
                    p = Path(axis_spec["path"])
                    if not p.is_absolute():
                        p = REPO_ROOT / p
                    if p.exists():
                        return json.loads(p.read_text(encoding="utf-8"))

        if not axis_name:
            axis_name = "yearly"

        grid = self._metric_grid(metric)
        p = self.tiles_root / grid.grid_id / metric / "time" / f"{axis_name}.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))

        p_old = self.tiles_root / grid.grid_id / "time" / f"{axis_name}.json"
        if p_old.exists():
            return json.loads(p_old.read_text(encoding="utf-8"))

        return []

    def _metric_grid(self, metric: str) -> GridSpec:
        spec = self.metrics.get(metric)
        if spec is None:
            return self.grid
        grid_id = spec.get("grid_id")
        if not grid_id:
            return self.grid
        grid = self.grids.get(grid_id)
        if grid is None:
            raise RuntimeError(f"No grid spec loaded for grid_id={grid_id}")
        return grid

    def _metric_tile_ext(self, metric: str) -> str:
        spec = self.metrics.get(metric)
        if spec is None:
            return ".bin.zst"
        storage = spec.get("storage", {})
        compression = storage.get("compression", {})
        codec = compression.get("codec", "zstd")
        if codec == "zstd":
            return ".bin.zst"
        if codec == "none":
            return ".bin"
        raise ValueError(f"Unsupported compression codec: {codec}")

    def _metric_tile_path(self, metric: str, tile_r: int, tile_c: int) -> Path:
        grid = self._metric_grid(metric)
        ext = self._metric_tile_ext(metric)
        return tile_path(
            self.tiles_root,
            grid,
            metric=metric,
            tile_r=tile_r,
            tile_c=tile_c,
            ext=ext,
        )

    def try_get_metric_vector(
        self, metric: str, lat: float, lon: float
    ) -> np.ndarray | None:
        """
        Return vector for the snapped cell:
          - yearly series metric -> shape (nyears,)
          - scalar metric -> shape (1,)
        None if tile missing or the cell is NaN-filled (dev harness sparse tiles).
        """
        grid = self._metric_grid(metric)
        _cell, t = locate_tile(lat, lon, grid)
        p = self._metric_tile_path(metric, t.tile_r, t.tile_c)
        if not p.exists():
            raise FileNotFoundError(f"Missing tile file: {p}")

        hdr, vec = read_cell_series(p, o_lat=t.o_lat, o_lon=t.o_lon)

        # dev harness uses NaN for empty cells
        if np.issubdtype(vec.dtype, np.floating) and np.all(np.isnan(vec)):
            return None

        # for yearly metrics we expect float32 tiles; but allow anything for now
        return np.asarray(vec)
