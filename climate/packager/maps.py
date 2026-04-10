from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from climate.tiles.layout import GridSpec, grid_from_id, tile_counts, tile_path
from climate.tiles.spec import read_tile_array

MERCATOR_MAX_LAT = 85.05112878
LONGITUDE_EDGE_STITCH_COLS = 8


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
        if map_type == "score" and map_spec.get("constant_score") is not None:
            if debug:
                print(f"[maps] Skip virtual constant score map (no files): {map_id}")
            continue

        source_metric = str(map_spec["source_metric"])
        metric_spec = metrics_manifest.get(source_metric)
        if not isinstance(metric_spec, dict):
            raise ValueError(f"Map {map_id} references missing metric: {source_metric}")
        reducer = map_spec.get("reducer") or {}
        if reducer.get("op") == "blended_preindustrial_anomaly":
            values, grid, axis = _compute_blended_preindustrial_values(
                series_root=series_root,
                source_metric=source_metric,
                source_metric_spec=metric_spec,
                reducer=reducer,
                metrics_manifest=metrics_manifest,
            )
        else:
            values, grid, axis = _load_scalar_grid_from_metric(
                series_root=series_root,
                metric_id=source_metric,
                metric_spec=metric_spec,
                reducer=reducer,
            )
        if map_spec.get("grid_id") and map_spec.get("grid_id") != grid.grid_id:
            raise ValueError(
                f"Map {map_id} grid_id={map_spec.get('grid_id')} does not match "
                f"source metric grid_id={grid.grid_id}"
            )

        out_dir = maps_root / grid.grid_id / map_id
        out_dir.mkdir(parents=True, exist_ok=True)

        if map_type == "texture":
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

        if map_type == "score":
            if _write_score_map(
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


def _compute_blended_preindustrial_values(
    *,
    series_root: Path,
    source_metric: str,
    source_metric_spec: dict[str, Any],
    reducer: dict[str, Any],
    metrics_manifest: dict[str, Any],
) -> tuple[np.ndarray, GridSpec, list[int]]:
    recent_start = int(reducer["recent_start_year"])
    recent_end = int(reducer["recent_end_year"])
    era5_ref_start = int(reducer["era5_ref_start_year"])
    era5_ref_end = int(reducer["era5_ref_end_year"])
    cmip_offset_metric = reducer.get("cmip_offset_metric")
    if not isinstance(cmip_offset_metric, str) or not cmip_offset_metric:
        raise ValueError(
            "blended_preindustrial_anomaly reducer requires non-empty "
            "'cmip_offset_metric'."
        )

    era5_recent, grid, axis = _load_scalar_grid_from_metric(
        series_root=series_root,
        metric_id=source_metric,
        metric_spec=source_metric_spec,
        reducer={
            "op": "mean",
            "start_year": recent_start,
            "end_year": recent_end,
        },
    )
    era5_ref, grid_ref, _ = _load_scalar_grid_from_metric(
        series_root=series_root,
        metric_id=source_metric,
        metric_spec=source_metric_spec,
        reducer={
            "op": "mean",
            "start_year": era5_ref_start,
            "end_year": era5_ref_end,
        },
    )
    cmip_offset_spec = metrics_manifest.get(cmip_offset_metric)
    if not isinstance(cmip_offset_spec, dict):
        raise ValueError(f"Unknown cmip_offset_metric: {cmip_offset_metric}")
    cmip_offset, grid_cmip_offset, _ = _load_scalar_grid_from_metric(
        series_root=series_root,
        metric_id=cmip_offset_metric,
        metric_spec=cmip_offset_spec,
        reducer={"op": "latest_year"},
    )
    if not (grid.grid_id == grid_ref.grid_id == grid_cmip_offset.grid_id):
        raise ValueError(
            "Grid mismatch in blended_preindustrial_anomaly reducer: "
            f"{grid.grid_id}, {grid_ref.grid_id}, {grid_cmip_offset.grid_id}"
        )
    values = (era5_recent - era5_ref) + cmip_offset
    return values, grid, axis


def load_series_grid_from_metric(
    *,
    series_root: Path,
    metric_id: str,
    metric_spec: dict[str, Any],
) -> tuple[np.ndarray, GridSpec, list[int]]:
    """Load the full time-series grid for a metric.

    Returns (arr, grid, axis) where arr has shape (nlat, nlon, nyears).
    """
    storage = metric_spec.get("storage", {})
    compression = storage.get("compression")
    ext = _compression_ext(compression)
    tile_size = int(storage.get("tile_size", 64))
    grid = grid_from_id(str(metric_spec["grid_id"]), tile_size=tile_size)
    axis = _load_metric_axis(
        series_root, grid, metric_id, str(metric_spec.get("time_axis", "yearly"))
    )
    nyears = len(axis)

    ntr, ntc = tile_counts(grid)
    out = np.full((grid.nlat, grid.nlon, nyears), np.nan, dtype=np.float64)

    for tr in range(ntr):
        i_lat0 = tr * grid.tile_size
        valid_h = min(grid.tile_size, grid.nlat - i_lat0)
        for tc in range(ntc):
            i_lon0 = tc * grid.tile_size
            valid_w = min(grid.tile_size, grid.nlon - i_lon0)
            p = tile_path(series_root, grid, metric=metric_id, tile_r=tr, tile_c=tc, ext=ext)
            if not p.exists():
                raise FileNotFoundError(f"Missing source tile: {p}")
            _hdr, arr = read_tile_array(p)
            tile_series = np.asarray(arr, dtype=np.float64)
            if tile_series.ndim != 3:
                raise ValueError(f"Expected 3-D tile for {p}: {tile_series.shape}")
            out[i_lat0 : i_lat0 + valid_h, i_lon0 : i_lon0 + valid_w, :] = (
                tile_series[:valid_h, :valid_w, :]
            )

    return out, grid, axis


def compute_trend_slope_per_decade(
    series: np.ndarray,
    axis: list[int],
) -> np.ndarray:
    """Compute OLS trend slope in units/decade for every grid cell.

    Args:
        series: shape (nlat, nlon, nyears)
        axis: list of integer years, length == nyears

    Returns:
        scalar grid shape (nlat, nlon) with slope in units/decade.
        Cells where all values are NaN are returned as NaN.
    """
    years = np.asarray(axis, dtype=np.float64)
    decades = (years - years[0]) / 10.0  # normalise to decades
    n = len(decades)
    # Precompute OLS components (valid across all cells)
    xm = decades - decades.mean()
    xm2 = float((xm**2).sum())

    nlat, nlon, _ = series.shape
    out = np.full((nlat, nlon), np.nan, dtype=np.float64)
    flat = series.reshape(-1, n)
    for i, row in enumerate(flat):
        if np.all(np.isnan(row)):
            continue
        # Use only non-NaN pairs
        mask = ~np.isnan(row)
        if mask.sum() < 2:
            continue
        xm_i = xm[mask]
        ym_i = row[mask] - np.nanmean(row)
        slope = float((xm_i * ym_i).sum() / (xm_i**2).sum())
        out.flat[i] = slope

    return out


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
    grid = grid_from_id(str(metric_spec["grid_id"]), tile_size=tile_size)
    axis = _load_metric_axis(
        series_root, grid, metric_id, str(metric_spec.get("time_axis", "yearly"))
    )

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
                raise FileNotFoundError(f"Missing source tile for map generation: {p}")
            hdr, arr = read_tile_array(p)
            if hdr.nyears == 0:
                tile_scalar = np.asarray(arr, dtype=np.float64)
                if tile_scalar.ndim != 2:
                    raise ValueError(
                        f"Unexpected scalar tile shape for {p}: {tile_scalar.shape}"
                    )
            else:
                tile_series = np.asarray(arr, dtype=np.float64)
                if tile_series.ndim != 3:
                    raise ValueError(
                        f"Unexpected series tile shape for {p}: {tile_series.shape}"
                    )
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
        raise ValueError(
            f"Expected y shape (h, w, n) with n={x.shape[0]}, got {y.shape}"
        )

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
    slope = np.divide(
        num, den, out=np.full_like(num, np.nan), where=(n >= 2) & (den > 0.0)
    )
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
    output = spec.get("output", {}) or {}
    file_format = _resolve_texture_file_format(spec)
    texture_path = _texture_output_path(map_id=map_id, out_dir=out_dir, spec=spec)
    mobile_texture_path = _mobile_texture_output_path(
        map_id=map_id, out_dir=out_dir, spec=spec
    )
    manifest_path = out_dir / "manifest.json"
    if resume and texture_path.exists() and manifest_path.exists():
        if mobile_texture_path is not None and not mobile_texture_path.exists():
            pass
        else:
            if debug:
                print(f"[maps] Skip existing texture map: {texture_path}")
            return False

    scale = spec.get("scale", {})
    vmin, vmax = _resolve_scale(values, scale)
    palette = spec.get("palette", {}) or {}
    colors = palette.get(
        "colors", ["#313695", "#74add1", "#f7f7f7", "#f46d43", "#a50026"]
    )
    nan_color = str(palette.get("nan_color", "#000000"))
    nan_alpha_raw = palette.get("nan_alpha")
    nan_alpha = float(nan_alpha_raw) if nan_alpha_raw is not None else None
    if nan_alpha is not None and not (0.0 <= nan_alpha <= 1.0):
        raise ValueError(
            f"Invalid palette.nan_alpha for {map_id}: {nan_alpha}. Expected 0..1."
        )
    projection = _resolve_projection(spec)
    mercator_lat_max = float(spec.get("mercator_lat_max", MERCATOR_MAX_LAT))
    projected_values, bounds = _project_texture_values(
        values, projection=projection, mercator_lat_max=mercator_lat_max
    )
    projected_values = _stitch_longitude_edges(projected_values)

    image = _apply_palette(
        projected_values,
        vmin=vmin,
        vmax=vmax,
        colors=colors,
        nan_color=nan_color,
        nan_alpha=nan_alpha,
    )
    image = _resize_if_needed(
        image,
        width=output.get("width"),
        height=output.get("height"),
    )
    _save_texture(texture_path, image, file_format=file_format)
    mobile_image: np.ndarray | None = None
    if mobile_texture_path is not None:
        mobile_width, mobile_height = _resolve_mobile_size(image=image, output=output)
        if _is_default_half_size(image, width=mobile_width, height=mobile_height):
            mobile_image = _downsample_half_preserve_alpha(image)
        else:
            mobile_image = _resize_if_needed(
                image, width=mobile_width, height=mobile_height
            )
        _save_texture(mobile_texture_path, mobile_image, file_format=file_format)

    finite = projected_values[np.isfinite(projected_values)]
    manifest = {
        "id": map_id,
        "type": "texture",
        "grid_model": "cell",
        "file_format": file_format,
        "projection": projection,
        "projection_bounds": bounds,
        "source_metric": source_metric,
        "source_axis_years": axis,
        "output_texture": str(texture_path),
        "output_mobile_texture": (
            str(mobile_texture_path) if mobile_texture_path else None
        ),
        "shape": [int(projected_values.shape[0]), int(projected_values.shape[1])],
        "output_shape": [int(image.shape[0]), int(image.shape[1])],
        "output_mobile_shape": (
            [int(mobile_image.shape[0]), int(mobile_image.shape[1])]
            if mobile_image is not None
            else None
        ),
        "scale": {
            "mode": "linear",
            "vmin": float(vmin),
            "vmax": float(vmax),
            "qlo": float(scale.get("qlo", 0.02)),
            "qhi": float(scale.get("qhi", 0.98)),
        },
        "palette": {
            "colors": list(colors),
            "nan_color": nan_color,
            "nan_alpha": nan_alpha,
        },
        "stats": {
            "min": float(np.min(finite)) if finite.size else None,
            "max": float(np.max(finite)) if finite.size else None,
            "nan_count": int(np.size(values) - finite.size),
        },
    }
    if file_format == "png":
        manifest["output_png"] = str(texture_path)
        if mobile_texture_path is not None:
            manifest["output_mobile_png"] = str(mobile_texture_path)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if mobile_texture_path is not None:
        print(
            f"[maps] Wrote texture map: {texture_path} (mobile: {mobile_texture_path})"
        )
    else:
        print(f"[maps] Wrote texture map: {texture_path}")
    return True


def _write_score_map(
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
    binary_name = str(output.get("binary_filename") or f"{map_id}.i16.bin")
    png_path = out_dir / png_name
    bin_path = out_dir / binary_name
    meta_path = out_dir / "binary_manifest.json"
    manifest_path = out_dir / "manifest.json"
    if (
        resume
        and png_path.exists()
        and bin_path.exists()
        and meta_path.exists()
        and manifest_path.exists()
    ):
        if debug:
            print(f"[maps] Skip existing score map: {out_dir}")
        return False

    default_score = int(spec.get("default_score", 0))
    score_rules = spec.get("score_rules", []) or []
    score = np.full(values.shape, default_score, dtype=np.int16)
    finite = np.isfinite(values)
    for rule in score_rules:
        predicate = rule.get("predicate", {})
        score_value = int(rule.get("score"))
        mask = _apply_predicate(values, predicate)
        score[mask] = np.maximum(score[mask], np.int16(score_value))
    score[~finite] = 0

    rgb = _score_to_rgb(score)
    _save_png(png_path, rgb)

    flat = score.reshape(-1).astype("<i2", copy=False)
    payload = flat.tobytes(order="C")
    bin_path.write_bytes(payload)

    bin_manifest = {
        "id": map_id,
        "grid_model": "cell",
        "format": "int16",
        "endianness": "little",
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
        "type": "score",
        "grid_model": "cell",
        "source_metric": source_metric,
        "source_axis_years": axis,
        "output_png": str(png_path),
        "output_binary": str(bin_path),
        "output_binary_manifest": str(meta_path),
        "default_score": default_score,
        "score_rules": score_rules,
        "score_counts": {
            "0": int(np.count_nonzero(score == 0)),
            "1": int(np.count_nonzero(score == 1)),
            "2": int(np.count_nonzero(score == 2)),
            "3": int(np.count_nonzero(score == 3)),
            "4": int(np.count_nonzero(score == 4)),
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"[maps] Wrote score map: {png_path} + {bin_path}")
    return True


def _resolve_texture_file_format(spec: dict[str, Any]) -> str:
    explicit = spec.get("file_format")
    output = spec.get("output", {}) or {}
    filename = output.get("filename")
    suffix_format: str | None = None
    if filename:
        suffix = Path(str(filename)).suffix.lower()
        if suffix in (".png", ".webp"):
            suffix_format = suffix[1:]

    if explicit is None:
        return suffix_format or "png"

    file_format = str(explicit).strip().lower()
    if file_format not in ("png", "webp"):
        raise ValueError(
            f"Unsupported texture file_format '{explicit}'. Expected one of: png, webp."
        )
    if suffix_format and suffix_format != file_format:
        raise ValueError(
            f"Texture output filename extension '.{suffix_format}' does not match "
            f"file_format '{file_format}'."
        )
    return file_format


def _texture_output_path(*, map_id: str, out_dir: Path, spec: dict[str, Any]) -> Path:
    output = spec.get("output", {}) or {}
    filename = output.get("filename")
    file_format = _resolve_texture_file_format(spec)
    if filename:
        filename_str = str(filename)
        suffix = Path(filename_str).suffix
        if suffix:
            return out_dir / filename_str
        return out_dir / f"{filename_str}.{file_format}"
    return out_dir / f"{map_id}.{file_format}"


def _mobile_texture_output_path(
    *,
    map_id: str,
    out_dir: Path,
    spec: dict[str, Any],
) -> Path | None:
    output = spec.get("output", {}) or {}
    mobile_filename = output.get("mobile_filename")
    if not isinstance(mobile_filename, str) or not mobile_filename.strip():
        return None
    file_format = _resolve_texture_file_format(spec)
    filename_str = str(mobile_filename)
    suffix = Path(filename_str).suffix.lower()
    if suffix:
        if suffix[1:] != file_format:
            raise ValueError(
                f"Texture mobile output extension '.{suffix[1:]}' does not match "
                f"file_format '{file_format}'."
            )
        return out_dir / filename_str
    return out_dir / f"{filename_str}.{file_format}"


def _resolve_mobile_size(
    *, image: np.ndarray, output: dict[str, Any]
) -> tuple[int, int]:
    mobile_width_raw = output.get("mobile_width")
    mobile_height_raw = output.get("mobile_height")
    if mobile_width_raw is None and mobile_height_raw is None:
        return max(1, int(round(image.shape[1] / 2.0))), max(
            1, int(round(image.shape[0] / 2.0))
        )
    if mobile_width_raw is None or mobile_height_raw is None:
        raise ValueError(
            "Both output.mobile_width and output.mobile_height must be set together."
        )
    return int(mobile_width_raw), int(mobile_height_raw)


def _is_default_half_size(image: np.ndarray, *, width: int, height: int) -> bool:
    return width == (image.shape[1] + 1) // 2 and height == (image.shape[0] + 1) // 2


def _downsample_half_preserve_alpha(image: np.ndarray) -> np.ndarray:
    """Downsample by ~2x by choosing, per 2x2 block, the pixel with max alpha.

    This preserves sparse opaque features better than bilinear averaging.
    """
    arr = np.asarray(image, dtype=np.uint8)
    if arr.ndim != 3 or arr.shape[2] not in (3, 4):
        raise ValueError(f"Expected RGB/RGBA image, got shape={arr.shape}")

    h, w, c = arr.shape
    h2 = (h + 1) // 2
    w2 = (w + 1) // 2
    pad_h = h2 * 2 - h
    pad_w = w2 * 2 - w
    if pad_h or pad_w:
        arr = np.pad(arr, ((0, pad_h), (0, pad_w), (0, 0)), mode="edge")

    # (h2, w2, 4, c): flatten each 2x2 neighborhood to 4 candidates.
    blocks = arr.reshape(h2, 2, w2, 2, c).transpose(0, 2, 1, 3, 4).reshape(h2, w2, 4, c)
    if c == 4:
        alpha = blocks[..., 3]
    else:
        alpha = np.full((h2, w2, 4), 255, dtype=np.uint8)

    pick = np.argmax(alpha, axis=2)
    rr = np.arange(h2)[:, None]
    cc = np.arange(w2)[None, :]
    out = blocks[rr, cc, pick, :]
    return np.asarray(out, dtype=np.uint8)


def _score_to_rgb(score: np.ndarray) -> np.ndarray:
    score = np.asarray(score, dtype=np.int16)
    palette = np.asarray(
        [
            [0, 0, 0],  # 0 invalid
            [255, 230, 0],  # 1
            [255, 170, 0],  # 2
            [255, 90, 0],  # 3
            [215, 25, 28],  # 4
        ],
        dtype=np.uint8,
    )
    idx = np.clip(score, 0, 4).astype(np.int32)
    return palette[idx]


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


def _resolve_projection(spec: dict[str, Any]) -> str:
    projection = str(spec.get("projection", "equirectangular")).strip().lower()
    if projection not in ("equirectangular", "mercator"):
        raise ValueError(
            f"Unsupported texture projection '{projection}'. "
            "Expected one of: equirectangular, mercator."
        )
    return projection


def _project_texture_values(
    values: np.ndarray,
    *,
    projection: str,
    mercator_lat_max: float = MERCATOR_MAX_LAT,
) -> tuple[np.ndarray, dict[str, float]]:
    arr = np.asarray(values, dtype=np.float64)
    if projection == "equirectangular":
        return (
            arr,
            {
                "lat_min": -90.0,
                "lat_max": 90.0,
                "lon_min": -180.0,
                "lon_max": 180.0,
            },
        )
    if projection == "mercator":
        merc = _warp_lat_to_mercator(arr, mercator_lat_max=mercator_lat_max)
        # Derive actual bounds from the outermost valid grid-cell centres, matching
        # how _warp_lat_to_mercator sets up y_tgt.  Using the raw mercator_lat_max
        # would overstate the covered range near 90° (Mercator Y diverges steeply),
        # causing visible texture misalignment in the frontend.
        nlat = arr.shape[0]
        deg = 180.0 / float(nlat)
        lat_src = 90.0 - (np.arange(nlat, dtype=np.float64) + 0.5) * deg
        lat_clip = lat_src[(lat_src >= -mercator_lat_max) & (lat_src <= mercator_lat_max)]
        if lat_clip.size >= 1:
            actual_lat_max = float(round(float(lat_clip[0]), 10))
            actual_lat_min = float(round(float(lat_clip[-1]), 10))
        else:
            actual_lat_max = float(mercator_lat_max)
            actual_lat_min = -float(mercator_lat_max)
        return (
            merc,
            {
                "lat_min": actual_lat_min,
                "lat_max": actual_lat_max,
                "lon_min": -180.0,
                "lon_max": 180.0,
            },
        )
    raise ValueError(f"Unsupported texture projection: {projection}")


def _warp_lat_to_mercator(
    values: np.ndarray, *, mercator_lat_max: float = MERCATOR_MAX_LAT
) -> np.ndarray:
    arr = np.asarray(values, dtype=np.float64)
    if arr.ndim != 2:
        raise ValueError(
            f"Expected 2D scalar grid for texture map, got shape: {arr.shape}"
        )
    nlat, nlon = arr.shape
    if nlat < 2 or nlon < 1:
        return arr.copy()

    # Row centers on a strict global cell grid.
    deg = 180.0 / float(nlat)
    lat_src = 90.0 - (np.arange(nlat, dtype=np.float64) + 0.5) * deg
    valid = (lat_src <= mercator_lat_max) & (lat_src >= -mercator_lat_max)
    if np.count_nonzero(valid) < 2:
        return arr.copy()

    arr_clip = arr[valid, :]
    lat_clip = lat_src[valid]
    phi = np.deg2rad(lat_clip)
    y_src = np.log(np.tan(np.pi / 4.0 + phi / 2.0))
    # Target rows match the latitude extent represented by the clipped source
    # rows, avoiding NaN bands at the very top/bottom due tiny extent mismatch.
    y_tgt = np.linspace(
        float(np.max(y_src)),
        float(np.min(y_src)),
        num=arr_clip.shape[0],
        dtype=np.float64,
    )

    out = np.full_like(arr_clip, np.nan, dtype=np.float64)
    order = np.argsort(y_src)
    y_src_sorted = y_src[order]
    for j in range(arr_clip.shape[1]):
        col = arr_clip[:, j]
        col_sorted = col[order]
        finite_idx = np.flatnonzero(np.isfinite(col_sorted))
        if finite_idx.size < 2:
            continue

        # Preserve NaN gaps (e.g. land masks in SST) by interpolating only
        # inside contiguous finite runs instead of bridging across missing spans.
        split_points = np.where(np.diff(finite_idx) > 1)[0] + 1
        runs = np.split(finite_idx, split_points)
        for run in runs:
            if run.size < 2:
                continue
            x = y_src_sorted[run]
            y = col_sorted[run]
            use = (y_tgt >= x[0]) & (y_tgt <= x[-1])
            if not np.any(use):
                continue
            out[use, j] = np.interp(y_tgt[use], x, y)
    return out


def _stitch_longitude_edges(values: np.ndarray) -> np.ndarray:
    arr = np.asarray(values, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[1] < 2:
        return arr

    out = arr.copy()
    # Blend a narrow longitude band around the dateline to avoid visible seams
    # in single-image globe rendering when source fields are not perfectly
    # periodic at +/-180.
    w = max(1, min(int(LONGITUDE_EDGE_STITCH_COLS), out.shape[1] // 2))
    for k in range(w):
        left = out[:, k]
        right = out[:, -(k + 1)]
        left_finite = np.isfinite(left)
        right_finite = np.isfinite(right)

        both = left_finite & right_finite
        if np.any(both):
            avg = (left[both] + right[both]) * 0.5
            out[both, k] = avg
            out[both, -(k + 1)] = avg

        left_only = left_finite & ~right_finite
        if np.any(left_only):
            out[left_only, -(k + 1)] = left[left_only]

        right_only = right_finite & ~left_finite
        if np.any(right_only):
            out[right_only, k] = right[right_only]

    return out


def _apply_palette(
    values: np.ndarray,
    *,
    vmin: float,
    vmax: float,
    colors: list[str],
    nan_color: str,
    nan_alpha: float | None,
) -> np.ndarray:
    rgb_stops = np.asarray([_hex_to_rgb(c) for c in colors], dtype=np.float64)
    nan_rgb = np.asarray(_hex_to_rgb(nan_color), dtype=np.uint8)

    values = np.asarray(values, dtype=np.float64)
    if nan_alpha is None:
        out = np.zeros(values.shape + (3,), dtype=np.uint8)
    else:
        out = np.zeros(values.shape + (4,), dtype=np.uint8)

    mask = np.isfinite(values)
    if nan_alpha is None:
        out[~mask] = nan_rgb
    else:
        out[~mask, :3] = nan_rgb
        out[~mask, 3] = int(round(nan_alpha * 255.0))
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
    out[mask, :3] = np.clip(interp, 0, 255).astype(np.uint8)
    if out.shape[-1] == 4:
        out[mask, 3] = 255
    return out


def _resize_if_needed(
    image: np.ndarray,
    *,
    width: int | None,
    height: int | None,
) -> np.ndarray:
    if width is None and height is None:
        return image
    if width is None or height is None:
        raise ValueError("Both output.width and output.height must be set together.")
    if image.shape[1] == int(width) and image.shape[0] == int(height):
        return image
    mode = _texture_image_mode(image)
    im = Image.fromarray(image, mode=mode)
    im = im.resize((int(width), int(height)), resample=Image.BILINEAR)
    return np.asarray(im, dtype=np.uint8)


def _texture_image_mode(image: np.ndarray) -> str:
    arr = np.asarray(image)
    if arr.ndim != 3:
        raise ValueError(f"Expected texture image ndim=3, got shape={arr.shape}")
    if arr.shape[-1] == 3:
        return "RGB"
    if arr.shape[-1] == 4:
        return "RGBA"
    raise ValueError(f"Expected texture image channels=3|4, got shape={arr.shape}")


def _save_png(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = _texture_image_mode(image)
    Image.fromarray(image, mode=mode).save(path, format="PNG")


def _save_texture(path: Path, image: np.ndarray, *, file_format: str) -> None:
    fmt = file_format.lower()
    if fmt == "png":
        _save_png(path, image)
        return

    if fmt == "webp":
        path.parent.mkdir(parents=True, exist_ok=True)
        mode = _texture_image_mode(image)
        Image.fromarray(image, mode=mode).save(
            path, format="WEBP", quality=85, method=6
        )
        return

    raise ValueError(f"Unsupported texture file format: {file_format}")


def _compression_ext(compression: dict | None) -> str:
    codec = "zstd"
    if compression is not None:
        codec = compression.get("codec", codec)
    if codec == "zstd":
        return ".bin.zst"
    if codec == "none":
        return ".bin"
    raise ValueError(f"Unsupported compression codec: {codec}")


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
        raise ValueError(
            f"Year {year} not found in metric axis {axis[0]}..{axis[-1]}"
        ) from exc


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
