#!/usr/bin/env python3
"""Precompute regional aggregate time series for climate metrics.

For each metric that declares an "aggregates" field in metrics.json, this script
computes mean/min/max time series for all countries, continents, oceans, and the
globe, then writes them to:

  data/releases/<release>/series/<grid_id>/<metric_id>/aggregates/<aggregation>.json

Usage:
    python scripts/precompute_regional_aggregates.py --release dev
    python scripts/precompute_regional_aggregates.py --release dev --metrics t2m_yearly_mean_c
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from climate.geo.continents import CONTINENT_TO_CC
from climate.registry.metrics import load_metrics
from climate.tiles.layout import GridSpec, tile_counts, tile_path
from climate.tiles.spec import read_tile_array


_DEFAULT_RELEASES_ROOT = REPO_ROOT / "data" / "releases"
_DEFAULT_COUNTRY_MASK = REPO_ROOT / "data" / "locations" / "country_mask.npz"
_DEFAULT_COUNTRY_CODES = REPO_ROOT / "data" / "locations" / "country_codes.json"
_DEFAULT_COUNTRY_NAMES = REPO_ROOT / "data" / "locations" / "country_names.json"
_DEFAULT_OCEAN_MASK = REPO_ROOT / "data" / "locations" / "ocean_mask.npz"
_DEFAULT_OCEAN_NAMES = REPO_ROOT / "data" / "locations" / "ocean_names.json"


# ---------------------------------------------------------------------------
# Mask loading
# ---------------------------------------------------------------------------


def _load_npz_mask(path: Path) -> tuple[np.ndarray, float]:
    """Load mask data and deg from NPZ file. Returns (data, deg)."""
    with np.load(path, allow_pickle=False) as f:
        return np.asarray(f["data"]), float(f["deg"])


def _slugify(name: str) -> str:
    """Convert ocean name to a URL-safe slug: lowercase, spaces→underscores."""
    normalized = unicodedata.normalize("NFD", name)
    ascii_str = normalized.encode("ascii", "ignore").decode("ascii")
    return ascii_str.lower().replace(" ", "_").replace("-", "_")


# ---------------------------------------------------------------------------
# Region weights building
# ---------------------------------------------------------------------------


def _build_fractional_weights(
    mask: np.ndarray,
    mask_deg: float,
    grid: GridSpec,
) -> dict[int, np.ndarray]:
    """
    For each unique non-zero mask ID, compute a (nlat, nlon) array of fractional
    weights (0..1) representing how much of each metric cell belongs to that region.

    Requires mask_deg to divide evenly into grid.deg (e.g. 0.05 → 0.25).
    """
    factor = int(round(grid.deg / mask_deg))
    if abs(factor * mask_deg - grid.deg) > 1e-9:
        raise ValueError(
            f"Mask resolution {mask_deg}° does not evenly divide metric resolution {grid.deg}°"
        )

    nlat, nlon = grid.nlat, grid.nlon

    # Reshape mask (nlat*factor, nlon*factor) → (nlat, factor, nlon, factor)
    sub = mask.reshape(nlat, factor, nlon, factor)
    # → (nlat, nlon, factor*factor) for easy per-cell counting
    sub = sub.transpose(0, 2, 1, 3).reshape(nlat, nlon, factor * factor)

    n_sub = factor * factor
    unique_ids = np.unique(sub)
    unique_ids = unique_ids[unique_ids > 0]

    weights: dict[int, np.ndarray] = {}
    for uid in unique_ids:
        frac = (sub == uid).sum(axis=-1).astype(np.float32) / n_sub
        if np.any(frac > 0):
            weights[int(uid)] = frac

    return weights


# ---------------------------------------------------------------------------
# Aggregation computation
# ---------------------------------------------------------------------------


def _area_weights(grid: GridSpec) -> np.ndarray:
    """Return (nlat,) array of cos(lat) area weights, north-to-south."""
    i_lat = np.arange(grid.nlat, dtype=np.float64)
    lat_centers = grid.lat_max - (i_lat + 0.5) * grid.deg
    return np.cos(np.deg2rad(lat_centers)).astype(np.float32)


def _compute_globe_mean_incremental(
    tiles_root: Path,
    grid: GridSpec,
    metric_id: str,
    ext: str,
) -> tuple[list[float | None], int] | None:
    """Area-weighted globe mean computed tile-by-tile to avoid loading the full grid.

    Returns (values, cell_count) or None if no tiles found.
    """
    n_tiles_lat, n_tiles_lon = tile_counts(grid)
    ts = int(grid.tile_size)

    ntime: int | None = None
    for tr in range(n_tiles_lat):
        for tc in range(n_tiles_lon):
            p = tile_path(tiles_root, grid, metric=metric_id, tile_r=tr, tile_c=tc, ext=ext)
            if p.exists():
                hdr, _ = read_tile_array(p)
                ntime = hdr.nyears if hdr.nyears > 0 else 1
                break
        if ntime is not None:
            break

    if ntime is None:
        return None

    i_lat = np.arange(grid.nlat, dtype=np.float64)
    lat_centers = grid.lat_max - (i_lat + 0.5) * grid.deg
    w_area = np.cos(np.deg2rad(lat_centers)).astype(np.float32)

    weighted_sum = np.zeros(ntime, dtype=np.float64)
    weight_sum = np.zeros(ntime, dtype=np.float64)
    cell_count = 0

    for tr in range(n_tiles_lat):
        r0 = tr * ts
        r1 = min(r0 + ts, grid.nlat)
        tile_w_area = w_area[r0:r1]

        for tc in range(n_tiles_lon):
            p = tile_path(tiles_root, grid, metric=metric_id, tile_r=tr, tile_c=tc, ext=ext)
            if not p.exists():
                continue

            _, arr = read_tile_array(p)
            if arr.ndim == 2:
                arr = arr[:, :, np.newaxis]

            # Clip to the valid rows for boundary tiles
            valid_rows = min(arr.shape[0], tile_w_area.shape[0])
            arr = arr[:valid_rows, :, :]
            w = tile_w_area[:valid_rows, np.newaxis, np.newaxis]
            valid = ~np.isnan(arr)
            weighted_sum += np.where(valid, arr * w, 0.0).sum(axis=(0, 1))
            weight_sum += np.where(valid, w, 0.0).sum(axis=(0, 1))
            cell_count += int(np.any(~np.isnan(arr), axis=-1).sum())

    with np.errstate(invalid="ignore"):
        result = np.where(weight_sum > 0, weighted_sum / weight_sum, np.nan)

    values = [None if np.isnan(v) else round(float(v), 4) for v in result]
    return values, cell_count


def _compute_aggregates_incremental(
    tiles_root: Path,
    grid: GridSpec,
    metric_id: str,
    ext: str,
    aggregations: list[str],
    named_regions: list[tuple[str, np.ndarray]],
    w_area: np.ndarray,
) -> tuple[dict[str, dict[str, list[float | None]]], int] | None:
    """Compute all region × aggregation time series by streaming one tile at a time.

    named_regions is a list of (region_key, frac) where frac is a (nlat, nlon)
    float32 fractional-coverage array. Cells with frac == 0 are excluded from
    each region's computation. All aggregations are accumulated in a single tile
    pass, so peak memory is proportional to one tile rather than the full grid.

    Returns ({aggregation: {region_key: values}}, ntime), or None if no tiles found.
    """
    n_tiles_lat, n_tiles_lon = tile_counts(grid)
    ts = int(grid.tile_size)

    ntime: int | None = None
    for tr in range(n_tiles_lat):
        for tc in range(n_tiles_lon):
            p = tile_path(tiles_root, grid, metric=metric_id, tile_r=tr, tile_c=tc, ext=ext)
            if p.exists():
                hdr, _ = read_tile_array(p)
                ntime = hdr.nyears if hdr.nyears > 0 else 1
                break
        if ntime is not None:
            break
    if ntime is None:
        return None

    do_mean = "mean" in aggregations
    do_min = "min" in aggregations
    do_max = "max" in aggregations

    # Per-region running accumulators (float64 for numerical stability)
    mean_wsum: dict[str, np.ndarray] = {}
    mean_wsumw: dict[str, np.ndarray] = {}
    min_acc: dict[str, np.ndarray] = {}
    max_acc: dict[str, np.ndarray] = {}

    for key, _ in named_regions:
        if do_mean:
            mean_wsum[key] = np.zeros(ntime, dtype=np.float64)
            mean_wsumw[key] = np.zeros(ntime, dtype=np.float64)
        if do_min:
            min_acc[key] = np.full(ntime, np.inf, dtype=np.float64)
        if do_max:
            max_acc[key] = np.full(ntime, -np.inf, dtype=np.float64)

    for tr in range(n_tiles_lat):
        r0 = tr * ts
        r1 = min(r0 + ts, grid.nlat)
        w_row = w_area[r0:r1]  # (tile_rows,)

        for tc in range(n_tiles_lon):
            p = tile_path(tiles_root, grid, metric=metric_id, tile_r=tr, tile_c=tc, ext=ext)
            if not p.exists():
                continue

            _, arr = read_tile_array(p)
            if arr.ndim == 2:
                arr = arr[:, :, np.newaxis]

            h = min(arr.shape[0], r1 - r0)
            c0 = tc * ts
            w = min(arr.shape[1], grid.nlon - c0)
            arr = arr[:h, :w, :].astype(np.float32, copy=False)
            valid = ~np.isnan(arr)  # (h, w, ntime)

            for region_key, frac in named_regions:
                frac_tile = frac[r0: r0 + h, c0: c0 + w]
                ri, ci = np.where(frac_tile > 0)
                if ri.size == 0:
                    continue

                cell_data = arr[ri, ci, :]     # (ncells, ntime)
                cell_valid = valid[ri, ci, :]  # (ncells, ntime)

                if do_mean:
                    wt = (w_row[ri] * frac_tile[ri, ci])[:, np.newaxis]  # (ncells, 1)
                    mean_wsum[region_key] += np.where(cell_valid, cell_data * wt, 0.0).sum(axis=0)
                    mean_wsumw[region_key] += np.where(cell_valid, wt, 0.0).sum(axis=0)

                if do_min:
                    tile_min = np.where(cell_valid, cell_data, np.inf).min(axis=0)
                    np.minimum(min_acc[region_key], tile_min, out=min_acc[region_key])

                if do_max:
                    tile_max = np.where(cell_valid, cell_data, -np.inf).max(axis=0)
                    np.maximum(max_acc[region_key], tile_max, out=max_acc[region_key])

    out: dict[str, dict[str, list[float | None]]] = {}

    if do_mean:
        res: dict[str, list[float | None]] = {}
        for key, _ in named_regions:
            with np.errstate(invalid="ignore"):
                v = np.where(mean_wsumw[key] > 0, mean_wsum[key] / mean_wsumw[key], np.nan)
            res[key] = [None if np.isnan(x) else round(float(x), 4) for x in v]
        out["mean"] = res

    if do_min:
        res = {}
        for key, _ in named_regions:
            res[key] = [None if np.isinf(x) else round(float(x), 4) for x in min_acc[key]]
        out["min"] = res

    if do_max:
        res = {}
        for key, _ in named_regions:
            res[key] = [None if np.isinf(x) else round(float(x), 4) for x in max_acc[key]]
        out["max"] = res

    return out, ntime


# ---------------------------------------------------------------------------
# Main precompute logic
# ---------------------------------------------------------------------------


def precompute_aggregates(
    *,
    release: str,
    releases_root: Path,
    metrics_path: Path,
    metric_filter: list[str] | None,
    country_mask_path: Path,
    country_codes_path: Path,
    country_names_path: Path,
    ocean_mask_path: Path,
    ocean_names_path: Path,
) -> int:
    releases_root = Path(releases_root)
    series_root = releases_root / release / "series"
    if not series_root.is_dir():
        print(f"ERROR: series root not found: {series_root}", file=sys.stderr)
        return 1

    manifest = load_metrics(path=metrics_path, validate=True)

    # -----------------------------------------------------------------
    # Load masks and code/name lookups
    # -----------------------------------------------------------------
    print("[aggregates] loading country mask ...", end="", flush=True)
    country_mask, country_mask_deg = _load_npz_mask(country_mask_path)
    country_id_to_code: dict[int, str] = {}
    if country_codes_path.exists():
        for k, v in json.loads(country_codes_path.read_text(encoding="utf-8")).items():
            country_id_to_code[int(k)] = str(v)
    # code → display name
    country_code_to_name: dict[str, str] = {}
    if country_names_path.exists():
        country_code_to_name = json.loads(country_names_path.read_text(encoding="utf-8"))
    print(f" {len(country_id_to_code)} countries")

    print("[aggregates] loading ocean mask ...", end="", flush=True)
    ocean_mask, ocean_mask_deg = _load_npz_mask(ocean_mask_path)
    ocean_id_to_name: dict[int, str] = {}
    if ocean_names_path.exists():
        for k, v in json.loads(ocean_names_path.read_text(encoding="utf-8")).items():
            ocean_id_to_name[int(k)] = str(v)
    print(f" {len(ocean_id_to_name)} ocean regions")

    # -----------------------------------------------------------------
    # Iterate metrics
    # -----------------------------------------------------------------
    generated = 0
    for metric_id, spec in manifest.items():
        if metric_id == "version":
            continue
        aggregations: list[str] = spec.get("aggregates", [])
        if not aggregations:
            continue
        if metric_filter and metric_id not in metric_filter:
            continue

        grid_id: str = spec.get("grid_id", "global_0p25")
        storage = spec.get("storage", {})
        tile_size = int(storage.get("tile_size", 64))
        codec = storage.get("compression", {}).get("codec", "zstd")
        ext = ".bin.zst" if codec == "zstd" else ".bin"

        if grid_id == "global_0p25":
            grid = GridSpec.global_0p25(tile_size=tile_size)
        elif grid_id == "global_0p05":
            grid = GridSpec.global_0p05(tile_size=tile_size)
        else:
            print(f"[aggregates] skip {metric_id}: unknown grid_id={grid_id}", file=sys.stderr)
            continue

        domain: str = spec.get("domain", "global")
        if domain == "dataset_mask":
            # Compute globe-only aggregate incrementally (no full grid load).
            tiles_path = series_root / grid_id / metric_id
            if not tiles_path.is_dir():
                print(
                    f"[aggregates] skip {metric_id}: tiles not found in {tiles_path}",
                    file=sys.stderr,
                )
                continue
            time_axis_path = tiles_path / "time" / "yearly.json"
            time_axis = (
                json.loads(time_axis_path.read_text(encoding="utf-8"))
                if time_axis_path.exists()
                else []
            )
            aggregates_dir = tiles_path / "aggregates"
            aggregates_dir.mkdir(parents=True, exist_ok=True)
            for aggregation in aggregations:
                if aggregation != "mean":
                    continue
                print(
                    f"[aggregates] computing {metric_id}/{aggregation} (incremental globe) ...",
                    end="",
                    flush=True,
                )
                t0 = time.monotonic()
                result = _compute_globe_mean_incremental(
                    tiles_root=series_root,
                    grid=grid,
                    metric_id=metric_id,
                    ext=ext,
                )
                if result is None:
                    print(" no tiles found, skipping")
                    continue
                globe_values, cell_count = result
                out_path = aggregates_dir / f"{aggregation}.json"
                out_path.write_text(
                    json.dumps(
                        {
                            "metric_id": metric_id,
                            "aggregation": aggregation,
                            "generated_at": datetime.now(timezone.utc).isoformat(),
                            "time_axis": time_axis,
                            "regions": {
                                "globe": {
                                    "name": "Global",
                                    "type": "globe",
                                    "cell_count": cell_count,
                                    "values": globe_values,
                                }
                            },
                        },
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                print(f" {time.monotonic() - t0:.1f}s -> {out_path}")
                generated += 1
            continue

        # Check mask alignment
        for mask_deg, label in [(country_mask_deg, "country"), (ocean_mask_deg, "ocean")]:
            factor = grid.deg / mask_deg
            if abs(round(factor) - factor) > 1e-9:
                print(
                    f"[aggregates] skip {metric_id}: {label} mask deg={mask_deg} "
                    f"does not align with grid deg={grid.deg}",
                    file=sys.stderr,
                )
                continue

        tiles_path = series_root / grid_id / metric_id
        if not tiles_path.is_dir():
            print(
                f"[aggregates] skip {metric_id}: tiles not found in {tiles_path}",
                file=sys.stderr,
            )
            continue

        # -----------------------------------------------------------------
        # Build region weights
        # -----------------------------------------------------------------
        print(f"[aggregates] building weights for {metric_id} ...", end="", flush=True)
        t0 = time.monotonic()

        w_area = _area_weights(grid)

        # Country weights (only for global domain)
        country_weights: dict[int, np.ndarray] = {}
        if domain in ("global",):
            country_weights = _build_fractional_weights(country_mask, country_mask_deg, grid)

        # Ocean weights
        ocean_weights: dict[int, np.ndarray] = {}
        if domain in ("global", "ocean"):
            ocean_weights = _build_fractional_weights(ocean_mask, ocean_mask_deg, grid)

        # Continent weights: union of country cell fractions
        continent_weights: dict[str, np.ndarray] = {}
        if domain in ("global",) and country_weights:
            for cont_name, cc_set in CONTINENT_TO_CC.items():
                cont_frac = np.zeros((grid.nlat, grid.nlon), dtype=np.float32)
                for uid, code in country_id_to_code.items():
                    if code in cc_set and uid in country_weights:
                        cont_frac += country_weights[uid]
                cont_frac = np.clip(cont_frac, 0.0, 1.0)
                if np.any(cont_frac > 0):
                    continent_weights[cont_name] = cont_frac

        print(f" {time.monotonic() - t0:.1f}s")

        # -----------------------------------------------------------------
        # Gather all (region_key, frac) pairs and their display metadata
        # -----------------------------------------------------------------
        named_regions: list[tuple[str, np.ndarray]] = []
        region_meta: dict[str, dict] = {}

        for uid, frac in country_weights.items():
            code = country_id_to_code.get(uid)
            if code is None:
                continue
            key = f"country:{code}"
            named_regions.append((key, frac))
            region_meta[key] = {
                "name": country_code_to_name.get(code, code),
                "type": "country",
                "cell_count": int(np.sum(frac > 0)),
            }

        for cont_name, frac in continent_weights.items():
            key = f"continent:{cont_name.replace(' ', '_')}"
            named_regions.append((key, frac))
            region_meta[key] = {
                "name": cont_name.title(),
                "type": "continent",
                "cell_count": int(np.sum(frac > 0)),
            }

        for uid, frac in ocean_weights.items():
            name = ocean_id_to_name.get(uid, f"ocean_{uid}")
            key = f"ocean:{_slugify(name)}"
            named_regions.append((key, frac))
            region_meta[key] = {
                "name": name,
                "type": "ocean",
                "cell_count": int(np.sum(frac > 0)),
            }

        # Globe: frac=1 everywhere; NaN cells contribute zero weight automatically
        globe_frac = np.ones((grid.nlat, grid.nlon), dtype=np.float32)
        named_regions.append(("globe", globe_frac))
        region_meta["globe"] = {
            "name": "Global",
            "type": "globe",
            "cell_count": grid.nlat * grid.nlon,
        }

        # -----------------------------------------------------------------
        # Compute all aggregations in a single tile-streaming pass
        # -----------------------------------------------------------------
        aggregates_dir = tiles_path / "aggregates"
        aggregates_dir.mkdir(parents=True, exist_ok=True)

        print(
            f"[aggregates] computing {metric_id} ({', '.join(aggregations)}) ...",
            end="",
            flush=True,
        )
        t0 = time.monotonic()
        agg_result = _compute_aggregates_incremental(
            tiles_root=series_root,
            grid=grid,
            metric_id=metric_id,
            ext=ext,
            aggregations=aggregations,
            named_regions=named_regions,
            w_area=w_area,
        )
        if agg_result is None:
            print(" no tiles found, skipping")
            continue
        agg_values, ntime = agg_result
        print(f" {time.monotonic() - t0:.1f}s")

        # Load canonical time axis using the metric's time_axis spec field
        axis_name = spec.get("time_axis", "yearly")
        time_axis_path = tiles_path / "time" / f"{axis_name}.json"
        if time_axis_path.exists():
            time_axis = json.loads(time_axis_path.read_text(encoding="utf-8"))
        else:
            time_axis = list(range(ntime))

        # Write one JSON file per aggregation
        for aggregation in aggregations:
            if aggregation not in agg_values:
                continue
            region_vals = agg_values[aggregation]
            regions: dict[str, dict] = {
                key: {**region_meta[key], "values": region_vals[key]}
                for key, _ in named_regions
                if key in region_vals
            }
            out_path = aggregates_dir / f"{aggregation}.json"
            out_path.write_text(
                json.dumps(
                    {
                        "metric_id": metric_id,
                        "aggregation": aggregation,
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                        "time_axis": time_axis,
                        "regions": regions,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            print(
                f"[aggregates] {metric_id}/{aggregation}:"
                f" {len(regions)} regions -> {out_path}"
            )
            generated += 1

    print(f"[aggregates] done: {generated} aggregate file(s) generated")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--release", default="dev", help="Release id (default: dev)")
    ap.add_argument(
        "--releases-root",
        type=Path,
        default=_DEFAULT_RELEASES_ROOT,
        help=f"Releases root (default: {_DEFAULT_RELEASES_ROOT})",
    )
    ap.add_argument(
        "--metrics-path",
        type=Path,
        default=REPO_ROOT / "registry" / "metrics.json",
        help="Path to metrics.json",
    )
    ap.add_argument(
        "--metrics",
        nargs="+",
        default=None,
        metavar="METRIC_ID",
        help="Limit to specific metric_id(s); default is all metrics with an aggregates field",
    )
    ap.add_argument(
        "--country-mask",
        type=Path,
        default=_DEFAULT_COUNTRY_MASK,
        help=f"Country mask NPZ (default: {_DEFAULT_COUNTRY_MASK})",
    )
    ap.add_argument(
        "--country-codes",
        type=Path,
        default=_DEFAULT_COUNTRY_CODES,
        help=f"Country codes JSON (default: {_DEFAULT_COUNTRY_CODES})",
    )
    ap.add_argument(
        "--country-names",
        type=Path,
        default=_DEFAULT_COUNTRY_NAMES,
        help=f"Country names JSON (default: {_DEFAULT_COUNTRY_NAMES})",
    )
    ap.add_argument(
        "--ocean-mask",
        type=Path,
        default=_DEFAULT_OCEAN_MASK,
        help=f"Ocean mask NPZ (default: {_DEFAULT_OCEAN_MASK})",
    )
    ap.add_argument(
        "--ocean-names",
        type=Path,
        default=_DEFAULT_OCEAN_NAMES,
        help=f"Ocean names JSON (default: {_DEFAULT_OCEAN_NAMES})",
    )
    args = ap.parse_args()

    return precompute_aggregates(
        release=args.release,
        releases_root=args.releases_root,
        metrics_path=args.metrics_path,
        metric_filter=args.metrics,
        country_mask_path=args.country_mask,
        country_codes_path=args.country_codes,
        country_names_path=args.country_names,
        ocean_mask_path=args.ocean_mask,
        ocean_names_path=args.ocean_names,
    )


if __name__ == "__main__":
    raise SystemExit(main())
