from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from climate.tiles.layout import GridSpec, tile_counts, tile_path
from climate.tiles.spec import read_tile_array


def package_maps(
    *,
    series_root: Path,
    maps_root: Path,
    maps_manifest: dict[str, Any],
    metrics_manifest: dict[str, Any],
    map_ids: list[str] | None = None,
    metric_ids: list[str] | None = None,
    resume: bool = False,
    debug: bool = False,
) -> int:
    maps_specs = {
        key: spec
        for key, spec in maps_manifest.items()
        if key != "version" and isinstance(spec, dict)
    }
    if map_ids:
        requested = set(map_ids)
        unknown = sorted(m for m in requested if m not in maps_specs)
        if unknown:
            raise ValueError(f"Unknown map id(s): {', '.join(unknown)}")
        maps_specs = {k: v for k, v in maps_specs.items() if k in requested}
    elif metric_ids:
        selected_metrics = set(metric_ids)
        maps_specs = {
            k: v
            for k, v in maps_specs.items()
            if v.get("source_metric") in selected_metrics
        }

    written = 0
    for map_id, map_spec in maps_specs.items():
        map_type = map_spec.get("type")
        source_metric = str(map_spec["source_metric"])
        metric_spec = metrics_manifest.get(source_metric)
        if not isinstance(metric_spec, dict):
            raise ValueError(f"Map {map_id} references missing metric: {source_metric}")

        values, grid, axis = _load_scalar_grid_from_metric(
            series_root=series_root,
            metric_id=source_metric,
            metric_spec=metric_spec,
            reducer=map_spec.get("reducer"),
        )
        if map_spec.get("grid_id") and map_spec.get("grid_id") != grid.grid_id:
            raise ValueError(
                f"Map {map_id} grid_id={map_spec.get('grid_id')} does not match "
                f"source metric grid_id={grid.grid_id}"
            )

        out_dir = maps_root / grid.grid_id / map_id
        out_dir.mkdir(parents=True, exist_ok=True)

        if map_type == "texture_png":
            if _write_texture_map(
                map_id=map_id,
                out_dir=out_dir,
                values=values,
                spec=map_spec,
                source_metric=source_metric,
                axis=axis,
                resume=resume,
                debug=debug,
            ):
                written += 1
            continue

        if map_type == "interestingness":
            if _write_interestingness_map(
                map_id=map_id,
                out_dir=out_dir,
                values=values,
                spec=map_spec,
                source_metric=source_metric,
                axis=axis,
                grid=grid,
                resume=resume,
                debug=debug,
            ):
                written += 1
            continue

        raise ValueError(f"Unsupported map type: {map_type}")

    return written


def _load_scalar_grid_from_metric(
    *,
    series_root: Path,
    metric_id: str,
    metric_spec: dict[str, Any],
    reducer: dict[str, Any] | None,
) -> tuple[np.ndarray, GridSpec, list[int]]:
    storage = metric_spec.get("storage", {})
    compression = storage.get("compression")
    ext = _compression_ext(compression)
    tile_size = int(storage.get("tile_size", 64))
    grid = _grid_from_id(str(metric_spec["grid_id"]), tile_size=tile_size)
    axis = _load_metric_axis(series_root, grid, metric_id, str(metric_spec.get("time_axis", "yearly")))

    ntr, ntc = tile_counts(grid)
    out = np.full((grid.nlat, grid.nlon), np.nan, dtype=np.float64)

    for tr in range(ntr):
        i_lat0 = tr * grid.tile_size
        valid_h = min(grid.tile_size, grid.nlat - i_lat0)
        for tc in range(ntc):
            i_lon0 = tc * grid.tile_size
            valid_w = min(grid.tile_size, grid.nlon - i_lon0)
            p = tile_path(
                series_root,
                grid,
                metric=metric_id,
                tile_r=tr,
                tile_c=tc,
                ext=ext,
            )
            if not p.exists():
                raise FileNotFoundError(
                    f"Missing source tile for map generation: {p}"
                )
            hdr, arr = read_tile_array(p)
            if hdr.nyears == 0:
                tile_scalar = np.asarray(arr, dtype=np.float64)
                if tile_scalar.ndim != 2:
                    raise ValueError(f"Unexpected scalar tile shape for {p}: {tile_scalar.shape}")
            else:
                tile_series = np.asarray(arr, dtype=np.float64)
                if tile_series.ndim != 3:
                    raise ValueError(f"Unexpected series tile shape for {p}: {tile_series.shape}")
                tile_scalar = _reduce_series(tile_series, axis, reducer)

            out[
                i_lat0 : i_lat0 + valid_h,
                i_lon0 : i_lon0 + valid_w,
            ] = tile_scalar[:valid_h, :valid_w]

    return out, grid, axis


def _reduce_series(
    arr: np.ndarray,
    axis: list[int],
    reducer: dict[str, Any] | None,
) -> np.ndarray:
    if not axis:
        raise ValueError("Series metric is missing time axis; cannot build map.")

    if not reducer:
        reducer = {"op": "latest_year"}
    op = reducer.get("op")

    if op == "latest_year":
        return np.asarray(arr[..., -1], dtype=np.float64)

    if op == "year":
        idx = _year_index(axis, int(reducer["year"]))
        return np.asarray(arr[..., idx], dtype=np.float64)

    if op == "mean":
        i0, i1 = _year_slice(axis, int(reducer["start_year"]), int(reducer["end_year"]))
        return _nanmean_no_warning(arr[..., i0 : i1 + 1], axis=-1)

    if op == "anomaly_vs_mean":
        target_idx = _year_index(axis, int(reducer["target_year"]))
        i0, i1 = _year_slice(
            axis,
            int(reducer["baseline_start_year"]),
            int(reducer["baseline_end_year"]),
        )
        baseline = _nanmean_no_warning(arr[..., i0 : i1 + 1], axis=-1)
        return np.asarray(arr[..., target_idx], dtype=np.float64) - baseline

    if op == "trend_slope":
        start_year = reducer.get("start_year")
        end_year = reducer.get("end_year")
        if start_year is None or end_year is None:
            i0, i1 = 0, len(axis) - 1
        else:
            i0, i1 = _year_slice(axis, int(start_year), int(end_year))
        x = np.asarray(axis[i0 : i1 + 1], dtype=np.float64)
        y = np.asarray(arr[..., i0 : i1 + 1], dtype=np.float64)
        return _slope_per_cell(x, y)

    raise ValueError(f"Unsupported reducer op: {op}")


def _slope_per_cell(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    if x.ndim != 1:
        raise ValueError(f"Expected 1D x axis, got shape {x.shape}")
    if y.ndim != 3 or y.shape[-1] != x.shape[0]:
        raise ValueError(f"Expected y shape (h, w, n) with n={x.shape[0]}, got {y.shape}")

    mask = np.isfinite(y)
    n = np.sum(mask, axis=-1)
    if np.all(n < 2):
        return np.full(y.shape[:2], np.nan, dtype=np.float64)

    x3 = np.broadcast_to(x.reshape(1, 1, -1), y.shape)
    x_sum = np.sum(np.where(mask, x3, 0.0), axis=-1)
    y_sum = np.sum(np.where(mask, y, 0.0), axis=-1)
    x_mean = np.divide(x_sum, n, out=np.zeros_like(x_sum), where=n > 0)
    y_mean = np.divide(y_sum, n, out=np.zeros_like(y_sum), where=n > 0)

    dx = x3 - x_mean[..., None]
    dy = y - y_mean[..., None]
    num = np.sum(np.where(mask, dx * dy, 0.0), axis=-1)
    den = np.sum(np.where(mask, dx * dx, 0.0), axis=-1)
    slope = np.divide(num, den, out=np.full_like(num, np.nan), where=(n >= 2) & (den > 0.0))
    return slope


def _nanmean_no_warning(arr: np.ndarray, axis: int) -> np.ndarray:
    arr = np.asarray(arr, dtype=np.float64)
    mask = np.isfinite(arr)
    count = np.sum(mask, axis=axis)
    total = np.sum(np.where(mask, arr, 0.0), axis=axis)
    out = np.full(count.shape, np.nan, dtype=np.float64)
    np.divide(total, count, out=out, where=count > 0)
    return out


def _write_texture_map(
    *,
    map_id: str,
    out_dir: Path,
    values: np.ndarray,
    spec: dict[str, Any],
    source_metric: str,
    axis: list[int],
    resume: bool,
    debug: bool,
) -> bool:
    output = spec.get("output", {})
    filename = str(output.get("filename") or f"{map_id}.png")
    png_path = out_dir / filename
    manifest_path = out_dir / "manifest.json"
    if resume and png_path.exists() and manifest_path.exists():
        if debug:
            print(f"[maps] Skip existing texture map: {png_path}")
        return False

    scale = spec.get("scale", {})
    vmin, vmax = _resolve_scale(values, scale)
    palette = spec.get("palette", {}) or {}
    colors = palette.get("colors", ["#313695", "#74add1", "#f7f7f7", "#f46d43", "#a50026"])
    nan_color = str(palette.get("nan_color", "#000000"))

    rgb = _apply_palette(values, vmin=vmin, vmax=vmax, colors=colors, nan_color=nan_color)
    rgb = _resize_if_needed(
        rgb,
        width=output.get("width"),
        height=output.get("height"),
    )
    _save_png(png_path, rgb)

    finite = values[np.isfinite(values)]
    manifest = {
        "id": map_id,
        "type": "texture_png",
        "source_metric": source_metric,
        "source_axis_years": axis,
        "output_png": str(png_path),
        "shape": [int(values.shape[0]), int(values.shape[1])],
        "scale": {
            "mode": "linear",
            "vmin": float(vmin),
            "vmax": float(vmax),
            "qlo": float(scale.get("qlo", 0.02)),
            "qhi": float(scale.get("qhi", 0.98)),
        },
        "palette": {"colors": list(colors), "nan_color": nan_color},
        "stats": {
            "min": float(np.min(finite)) if finite.size else None,
            "max": float(np.max(finite)) if finite.size else None,
            "nan_count": int(np.size(values) - finite.size),
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"[maps] Wrote texture map: {png_path}")
    return True


def _write_interestingness_map(
    *,
    map_id: str,
    out_dir: Path,
    values: np.ndarray,
    spec: dict[str, Any],
    source_metric: str,
    axis: list[int],
    grid: GridSpec,
    resume: bool,
    debug: bool,
) -> bool:
    output = spec.get("output", {}) or {}
    png_name = str(output.get("png_filename") or f"{map_id}.png")
    binary_name = str(output.get("binary_filename") or f"{map_id}.bitset.bin")
    pack_bits = bool(output.get("pack_bits", True))

    png_path = out_dir / png_name
    bin_path = out_dir / binary_name
    meta_path = out_dir / "binary_manifest.json"
    manifest_path = out_dir / "manifest.json"
    if resume and png_path.exists() and bin_path.exists() and meta_path.exists() and manifest_path.exists():
        if debug:
            print(f"[maps] Skip existing interestingness map: {out_dir}")
        return False

    predicate = spec.get("predicate", {})
    mask = _apply_predicate(values, predicate)

    bw = np.where(mask, 255, 0).astype(np.uint8)
    rgb = np.repeat(bw[..., None], 3, axis=2)
    _save_png(png_path, rgb)

    flat = mask.reshape(-1).astype(np.uint8)
    if pack_bits:
        payload = np.packbits(flat, bitorder="little").tobytes()
    else:
        payload = flat.tobytes(order="C")
    bin_path.write_bytes(payload)

    bin_manifest = {
        "id": map_id,
        "format": "bitset" if pack_bits else "bytes",
        "bitorder": "little" if pack_bits else None,
        "grid_id": grid.grid_id,
        "nlat": int(grid.nlat),
        "nlon": int(grid.nlon),
        "row_major": True,
        "index_formula": "idx = i_lat * nlon + i_lon",
        "lookup": "(lat, lon) -> snap to (i_lat, i_lon) -> idx -> bit/value",
        "source_metric": source_metric,
    }
    meta_path.write_text(json.dumps(bin_manifest, indent=2) + "\n", encoding="utf-8")

    manifest = {
        "id": map_id,
        "type": "interestingness",
        "source_metric": source_metric,
        "source_axis_years": axis,
        "output_png": str(png_path),
        "output_binary": str(bin_path),
        "output_binary_manifest": str(meta_path),
        "true_count": int(np.count_nonzero(mask)),
        "false_count": int(mask.size - np.count_nonzero(mask)),
        "predicate": predicate,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"[maps] Wrote interestingness map: {png_path} + {bin_path}")
    return True


def _apply_predicate(values: np.ndarray, predicate: dict[str, Any]) -> np.ndarray:
    op = predicate.get("op")
    valid = np.isfinite(values)
    out = np.zeros(values.shape, dtype=bool)

    if op == "gt":
        out[valid] = values[valid] > float(predicate["threshold"])
        return out
    if op == "gte":
        out[valid] = values[valid] >= float(predicate["threshold"])
        return out
    if op == "lt":
        out[valid] = values[valid] < float(predicate["threshold"])
        return out
    if op == "lte":
        out[valid] = values[valid] <= float(predicate["threshold"])
        return out
    if op == "eq":
        out[valid] = values[valid] == float(predicate["threshold"])
        return out
    if op == "neq":
        out[valid] = values[valid] != float(predicate["threshold"])
        return out
    if op == "between":
        lo = float(predicate["min"])
        hi = float(predicate["max"])
        inclusive = bool(predicate.get("inclusive", True))
        if inclusive:
            out[valid] = (values[valid] >= lo) & (values[valid] <= hi)
        else:
            out[valid] = (values[valid] > lo) & (values[valid] < hi)
        return out
    raise ValueError(f"Unsupported predicate op: {op}")


def _resolve_scale(values: np.ndarray, scale: dict[str, Any]) -> tuple[float, float]:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return (0.0, 1.0)

    qlo = float(scale.get("qlo", 0.02))
    qhi = float(scale.get("qhi", 0.98))
    vmin = scale.get("vmin")
    vmax = scale.get("vmax")
    if vmin is None:
        vmin = float(np.quantile(finite, qlo))
    else:
        vmin = float(vmin)
    if vmax is None:
        vmax = float(np.quantile(finite, qhi))
    else:
        vmax = float(vmax)
    if not np.isfinite(vmin) or not np.isfinite(vmax) or vmin >= vmax:
        vmin = float(np.min(finite))
        vmax = float(np.max(finite))
        if vmin >= vmax:
            vmin = vmin - 1.0
            vmax = vmax + 1.0
    return (vmin, vmax)


def _apply_palette(
    values: np.ndarray,
    *,
    vmin: float,
    vmax: float,
    colors: list[str],
    nan_color: str,
) -> np.ndarray:
    rgb_stops = np.asarray([_hex_to_rgb(c) for c in colors], dtype=np.float64)
    nan_rgb = np.asarray(_hex_to_rgb(nan_color), dtype=np.uint8)

    values = np.asarray(values, dtype=np.float64)
    out = np.zeros(values.shape + (3,), dtype=np.uint8)

    mask = np.isfinite(values)
    out[~mask] = nan_rgb
    if not np.any(mask):
        return out

    t = (values[mask] - vmin) / (vmax - vmin)
    t = np.clip(t, 0.0, 1.0)

    nseg = rgb_stops.shape[0] - 1
    pos = t * nseg
    i0 = np.floor(pos).astype(np.int32)
    i1 = np.clip(i0 + 1, 0, nseg)
    frac = pos - i0
    interp = rgb_stops[i0] * (1.0 - frac[:, None]) + rgb_stops[i1] * frac[:, None]
    out[mask] = np.clip(interp, 0, 255).astype(np.uint8)
    return out


def _resize_if_needed(
    rgb: np.ndarray,
    *,
    width: int | None,
    height: int | None,
) -> np.ndarray:
    if width is None and height is None:
        return rgb
    if width is None or height is None:
        raise ValueError("Both output.width and output.height must be set together.")
    if rgb.shape[1] == int(width) and rgb.shape[0] == int(height):
        return rgb
    try:
        from PIL import Image
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "Pillow is required for map PNG resizing. Install with: pip install pillow"
        ) from exc
    im = Image.fromarray(rgb, mode="RGB")
    im = im.resize((int(width), int(height)), resample=Image.BILINEAR)
    return np.asarray(im, dtype=np.uint8)


def _save_png(path: Path, rgb: np.ndarray) -> None:
    try:
        from PIL import Image
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "Pillow is required for map PNG output. Install with: pip install pillow"
        ) from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgb, mode="RGB").save(path, format="PNG")


def _compression_ext(compression: dict | None) -> str:
    codec = "zstd"
    if compression is not None:
        codec = compression.get("codec", codec)
    if codec == "zstd":
        return ".bin.zst"
    if codec == "none":
        return ".bin"
    raise ValueError(f"Unsupported compression codec: {codec}")


def _grid_from_id(grid_id: str, *, tile_size: int) -> GridSpec:
    if grid_id == "global_0p25":
        return GridSpec.global_0p25(tile_size=tile_size)
    if grid_id == "global_0p05":
        return GridSpec.global_0p05(tile_size=tile_size)
    raise ValueError(f"Unsupported grid_id for maps: {grid_id}")


def _load_metric_axis(
    series_root: Path,
    grid: GridSpec,
    metric_id: str,
    axis_name: str,
) -> list[int]:
    p = series_root / grid.grid_id / metric_id / "time" / f"{axis_name}.json"
    if not p.exists():
        return []
    values = json.loads(p.read_text(encoding="utf-8"))
    return [int(v) for v in values]


def _year_index(axis: list[int], year: int) -> int:
    try:
        return axis.index(year)
    except ValueError as exc:
        raise ValueError(f"Year {year} not found in metric axis {axis[0]}..{axis[-1]}") from exc


def _year_slice(axis: list[int], start_year: int, end_year: int) -> tuple[int, int]:
    if start_year > end_year:
        raise ValueError(f"Invalid year range: {start_year}..{end_year}")
    i0 = _year_index(axis, start_year)
    i1 = _year_index(axis, end_year)
    if i0 > i1:
        raise ValueError(f"Invalid year slice for axis: {start_year}..{end_year}")
    return (i0, i1)


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    c = str(color).strip()
    if not c.startswith("#") or len(c) != 7:
        raise ValueError(f"Color must be #RRGGBB, got: {color}")
    return (int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16))
