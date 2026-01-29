from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import json
import numpy as np

from climate.tiles.layout import GridSpec, locate_tile, tile_path
from climate.tiles.spec import read_cell_series


def c_to_f(x: np.ndarray) -> np.ndarray:
    return x * (9.0 / 5.0) + 32.0


def rolling_mean_centered(y: np.ndarray, window: int) -> np.ndarray:
    """
    Centered rolling mean with NaN-aware behavior.
    Returns array same length, with NaN at edges where window doesn't fit
    or where all values in window are NaN.
    """
    n = int(y.size)
    w = int(window)
    out = np.full(n, np.nan, dtype=np.float32)
    if w <= 1 or n == 0:
        return y.astype(np.float32, copy=False)

    half = w // 2
    for i in range(n):
        lo = i - half
        hi = i + half + 1
        if lo < 0 or hi > n:
            continue
        seg = y[lo:hi]
        if np.all(np.isnan(seg)):
            continue
        out[i] = float(np.nanmean(seg))
    return out


def linear_trend_line(x_years: np.ndarray, y: np.ndarray) -> np.ndarray:
    """
    Fit y ~ a*x + b using valid (non-NaN) y points.
    Returns y_hat for all x_years (NaNs if not enough points).
    """
    x = x_years.astype(np.float64)
    yy = y.astype(np.float64)

    mask = np.isfinite(yy)
    if int(mask.sum()) < 2:
        return np.full_like(y, np.nan, dtype=np.float32)

    a, b = np.polyfit(x[mask], yy[mask], deg=1)
    yhat = a * x + b
    return yhat.astype(np.float32)


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

    @classmethod
    def discover(
        cls, tiles_root: Path, *, start_year_fallback: int = 1979
    ) -> "TileDataStore":
        """
        Discover grid_id and tile_size from folder layout.

        Expected layout:
          {tiles_root}/{grid_id}/{metric}/z{tile_size}/rXXX_cYYY.bin.zst
        """
        tiles_root = Path(tiles_root)

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
        )

    def yearly_axis(self, metric: str) -> list[int]:
        """
        Returns list of int years for a given yearly metric.
        Expected file (per-metric axis):
        {tiles_root}/{grid_id}/{metric}/time/yearly.json

        (Optional backward-compat: if the per-metric file is missing, also try the old
        grid-level path for a while.)
        """
        # New (per-metric) location
        p = self.tiles_root / self.grid.grid_id / metric / "time" / "yearly.json"
        if p.exists():
            years = json.loads(p.read_text(encoding="utf-8"))
            return [int(v) for v in years]

        # Backward compat (remove later if you want)
        # TODO(remove)
        p_old = self.tiles_root / self.grid.grid_id / "time" / "yearly.json"
        if p_old.exists():
            years = json.loads(p_old.read_text(encoding="utf-8"))
            return [int(v) for v in years]

        return []

    def _metric_tile_path(self, metric: str, tile_r: int, tile_c: int) -> Path:
        return tile_path(
            self.tiles_root,
            self.grid,
            metric=metric,
            tile_r=tile_r,
            tile_c=tile_c,
            ext=".bin.zst",
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
        _cell, t = locate_tile(lat, lon, self.grid)
        p = self._metric_tile_path(metric, t.tile_r, t.tile_c)
        if not p.exists():
            raise FileNotFoundError(f"Missing tile file: {tile_path}")

        hdr, vec = read_cell_series(p, o_lat=t.o_lat, o_lon=t.o_lon)

        # dev harness uses NaN for empty cells
        if np.issubdtype(vec.dtype, np.floating) and np.all(np.isnan(vec)):
            return None

        # for yearly metrics we expect float32 tiles; but allow anything for now
        return np.asarray(vec)

    def panel_t2m_50y(self, lat: float, lon: float, unit: str = "C") -> dict[str, Any]:
        """
        Builds series payload for the v0 graph:
          - annual mean temperature
          - 5-year mean
          - linear trend (on annual mean)
        """
        metric = "t2m_yearly_mean_c"
        unit = unit.upper()
        if unit not in ("C", "F"):
            raise ValueError(f"unit must be C or F, got {unit}")

        y_c = self.try_get_metric_vector(metric, lat, lon)
        if y_c is None:
            raise FileNotFoundError(
                "No t2m tile data available for this location/cell yet."
            )

        y_c = y_c.astype(np.float32, copy=False).reshape(-1)
        years = self.yearly_axis(metric)
        if not years:
            # fallback: start_year_fallback + length
            years = list(
                range(
                    self.start_year_fallback, self.start_year_fallback + int(y_c.size)
                )
            )

        x = np.asarray(years, dtype=np.int32)
        if x.size != y_c.size:
            raise ValueError(
                f"Year axis length {x.size} does not match series length {y_c.size}"
            )

        y5_c = rolling_mean_centered(y_c, window=5)
        ytrend_c = linear_trend_line(x, y_c)

        if unit == "F":
            y = c_to_f(y_c)
            y5 = c_to_f(y5_c)
            ytrend = c_to_f(ytrend_c)
        else:
            y, y5, ytrend = y_c, y5_c, ytrend_c

        # convert to JSON-friendly lists (NaN -> None)
        def to_list(a: np.ndarray) -> list[float | None]:
            out: list[float | None] = []
            for v in a.tolist():
                if v is None:
                    out.append(None)
                else:
                    fv = float(v)
                    out.append(None if not np.isfinite(fv) else fv)
            return out

        x_list = [int(v) for v in x.tolist()]

        return {
            "series": {
                "t2m_yearly_mean": {"x": x_list, "y": to_list(y), "unit": unit},
                "t2m_yearly_mean_5y": {"x": x_list, "y": to_list(y5), "unit": unit},
                "t2m_yearly_trend": {"x": x_list, "y": to_list(ytrend), "unit": unit},
            }
        }
