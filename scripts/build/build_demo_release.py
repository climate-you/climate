#!/usr/bin/env python3
"""
Build a self-contained demo release package.

Extracts a regional subset (default: Great Barrier Reef) from a full release,
filters registries to a curated set of metrics/panels/layers, and packages
everything into a distributable tar.gz archive.
"""

from __future__ import annotations

import argparse
import copy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
from typing import Any

import numpy as np

from climate.geo.lon import normalize_lon_pm180
from climate.registry.layers import load_layers, validate_layers_against_maps
from climate.registry.maps import load_maps, validate_maps_against_metrics
from climate.registry.metrics import load_metrics
from climate.registry.panels import (
    load_panels,
    validate_panels_against_maps,
    validate_panels_against_metrics,
)


DEFAULT_PROFILE = "default"
DEFAULT_DATA_ROOT = Path("data")
DEFAULT_RELEASES_ROOT = DEFAULT_DATA_ROOT / "releases"
DEFAULT_DIST_ROOT = Path("dist")
DEFAULT_BASE_REEF_MASK = Path("data/masks/crw_dhw_daily_global_0p05_mask.npz")
DEFAULT_DEMO_REEF_MASK = Path("data/masks/crw_dhw_daily_gbr_demo_global_0p05_mask.npz")
DEFAULT_DEMO_SPARSE_RISK_MASK = Path(
    "data/masks/sparse_risk_gbr_demo_global_0p25_mask.npz"
)
# Approximate Great Barrier Reef bounds: lat_min, lat_max, lon_min, lon_max.
DEFAULT_GBR_BBOX = (-24.5, -10.0, 142.0, 155.5)
DEFAULT_REQUIRED_LOCATION_FILES = (
    Path("data/locations/locations.csv"),
    Path("data/locations/locations.index.csv"),
    Path("data/locations/locations.kdtree.pkl"),
    Path("data/locations/ocean_mask.npz"),
    Path("data/locations/ocean_names.json"),
)


@dataclass(frozen=True)
class DemoProfile:
    name: str
    panel_graph_ids: dict[str, set[str]]
    layer_ids: set[str]


def _default_profile(*, skip_dhw_metrics: bool) -> DemoProfile:
    panel_graph_ids = {
        "air_temperature": {"t2m_annual", "t2m_hot_days"},
    }
    layer_ids = {
        "warming_vs_preindustrial_air",
    }
    if not skip_dhw_metrics:
        panel_graph_ids["coral_reef_dhw"] = {"dhw_risk_days"}
        layer_ids.add("reef_stress")

    return DemoProfile(
        name=DEFAULT_PROFILE,
        panel_graph_ids=panel_graph_ids,
        layer_ids=layer_ids,
    )


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8"
    )


def _parse_bbox(raw: str) -> tuple[float, float, float, float]:
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) != 4:
        raise ValueError("Expected bbox as 'lat_min,lat_max,lon_min,lon_max'.")
    lat_min, lat_max, lon_min, lon_max = [float(p) for p in parts]
    if lat_min > lat_max:
        raise ValueError(f"Invalid bbox latitude range: {lat_min} > {lat_max}")
    return (lat_min, lat_max, lon_min, lon_max)



def _to_mask_bool(data: np.ndarray) -> np.ndarray:
    if data.dtype == np.bool_:
        return data.astype(bool, copy=False)
    if np.issubdtype(data.dtype, np.floating):
        return np.isfinite(data) & (data != 0.0)
    return data != 0


def _build_gbr_demo_mask(
    *,
    base_mask_path: Path,
    output_path: Path,
    bbox: tuple[float, float, float, float],
) -> Path:
    if not base_mask_path.exists():
        raise FileNotFoundError(f"Base reef mask not found: {base_mask_path}")

    with np.load(base_mask_path, allow_pickle=False) as npz:
        if "data" not in npz:
            raise ValueError(f"Invalid mask file {base_mask_path}: missing 'data' key.")
        data = np.asarray(npz["data"])
        if data.ndim != 2:
            raise ValueError(
                f"Invalid mask file {base_mask_path}: expected 2D data, got {data.shape}."
            )
        deg = float(np.asarray(npz["deg"]).reshape(()))
        lat_max = float(np.asarray(npz["lat_max"]).reshape(()))
        lon_min = float(np.asarray(npz["lon_min"]).reshape(()))

    base_mask = _to_mask_bool(data)
    nlat, nlon = base_mask.shape
    lat_min, lat_max_bbox, lon_min_bbox, lon_max_bbox = bbox
    lon_min_bbox = normalize_lon_pm180(lon_min_bbox)
    lon_max_bbox = normalize_lon_pm180(lon_max_bbox)

    lat_centers = lat_max - (np.arange(nlat, dtype=np.float64) + 0.5) * deg
    lon_centers = lon_min + (np.arange(nlon, dtype=np.float64) + 0.5) * deg
    lon_centers = np.asarray([normalize_lon_pm180(v) for v in lon_centers], dtype=np.float64)

    row_idx = np.flatnonzero((lat_centers >= lat_min) & (lat_centers <= lat_max_bbox))
    if lon_min_bbox <= lon_max_bbox:
        col_sel = (lon_centers >= lon_min_bbox) & (lon_centers <= lon_max_bbox)
    else:
        col_sel = (lon_centers >= lon_min_bbox) | (lon_centers <= lon_max_bbox)
    col_idx = np.flatnonzero(col_sel)

    if row_idx.size == 0 or col_idx.size == 0:
        raise ValueError(
            "GBR bbox selected no cells; adjust --gbr-bbox. "
            f"rows={row_idx.size} cols={col_idx.size}"
        )

    bbox_mask = np.zeros_like(base_mask, dtype=bool)
    bbox_mask[np.ix_(row_idx, col_idx)] = True
    demo_mask = base_mask & bbox_mask

    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output_path,
        data=demo_mask.astype(np.uint8, copy=False),
        deg=np.float64(deg),
        lat_max=np.float64(lat_max),
        lon_min=np.float64(lon_min),
    )

    valid = int(np.count_nonzero(demo_mask))
    total = int(demo_mask.size)
    print(
        f"[mask] wrote {output_path} valid={valid}/{total} "
        f"({(100.0 * valid / max(1, total)):.5f}%)"
    )
    return output_path


def _build_sparse_risk_mask_from_fine_mask(
    *,
    fine_mask_path: Path,
    output_path: Path,
    target_deg: float = 0.25,
) -> Path:
    with np.load(fine_mask_path, allow_pickle=False) as npz:
        if "data" not in npz:
            raise ValueError(
                f"Invalid fine mask file {fine_mask_path}: missing 'data' key."
            )
        data = np.asarray(npz["data"])
        if data.ndim != 2:
            raise ValueError(
                f"Invalid fine mask file {fine_mask_path}: expected 2D data, got {data.shape}."
            )
        deg = float(np.asarray(npz["deg"]).reshape(()))
        lat_max = float(np.asarray(npz["lat_max"]).reshape(()))
        lon_min = float(np.asarray(npz["lon_min"]).reshape(()))

    ratio = target_deg / deg
    factor = int(round(ratio))
    if factor <= 0 or abs(ratio - factor) > 1e-9:
        raise ValueError(
            f"Invalid sparse-risk ratio target_deg/source_deg={target_deg}/{deg}={ratio}."
        )
    fine_mask = _to_mask_bool(data)
    nlat, nlon = fine_mask.shape
    coarse_rows = np.floor((np.arange(nlat, dtype=np.float64) + 0.5) / factor).astype(
        np.int64
    )
    coarse_cols = np.floor((np.arange(nlon, dtype=np.float64) + 0.5) / factor).astype(
        np.int64
    )
    nlat_coarse = int(coarse_rows.max()) + 1
    nlon_coarse = int(coarse_cols.max()) + 1
    coarse = np.zeros((nlat_coarse, nlon_coarse), dtype=bool)
    true_i, true_j = np.nonzero(fine_mask)
    if true_i.size:
        coarse[coarse_rows[true_i], coarse_cols[true_j]] = True

    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output_path,
        data=coarse.astype(np.uint8, copy=False),
        deg=np.float64(target_deg),
        lat_max=np.float64(lat_max),
        lon_min=np.float64(lon_min),
    )
    valid = int(np.count_nonzero(coarse))
    total = int(coarse.size)
    print(
        f"[mask] wrote {output_path} valid={valid}/{total} "
        f"({(100.0 * valid / max(1, total)):.5f}%)"
    )
    return output_path


def _extract_graph_metrics(
    panels_manifest: dict[str, Any], profile: DemoProfile
) -> tuple[dict[str, Any], set[str], set[str]]:
    root = panels_manifest.get("panels")
    if not isinstance(root, dict):
        raise ValueError("Invalid panels.json: missing object root at key 'panels'.")

    selected_panels: dict[str, Any] = {}
    metric_ids: set[str] = set()
    score_map_ids: set[str] = set()
    for panel_id, graph_ids in profile.panel_graph_ids.items():
        panel = root.get(panel_id)
        if not isinstance(panel, dict):
            raise ValueError(f"Panel '{panel_id}' not found in panels manifest.")
        panel_copy = copy.deepcopy(panel)
        graphs_in = panel_copy.get("graphs", [])
        if not isinstance(graphs_in, list):
            raise ValueError(f"Panel '{panel_id}' has invalid graphs definition.")

        kept_graphs: list[dict[str, Any]] = []
        for graph in graphs_in:
            if not isinstance(graph, dict):
                continue
            graph_id = graph.get("id")
            if not isinstance(graph_id, str):
                continue
            if graph_ids and graph_id not in graph_ids:
                continue
            kept_graphs.append(copy.deepcopy(graph))
            series = graph.get("series", [])
            if isinstance(series, list):
                for item in series:
                    if not isinstance(item, dict):
                        continue
                    metric = item.get("metric")
                    if isinstance(metric, str) and metric:
                        metric_ids.add(metric)

        panel_copy["graphs"] = kept_graphs
        score_map_id = panel_copy.get("score_map_id")
        if isinstance(score_map_id, str) and score_map_id:
            score_map_ids.add(score_map_id)
        selected_panels[panel_id] = panel_copy

    return selected_panels, metric_ids, score_map_ids


def _sanitize_demo_panel_graphs(selected_panels: dict[str, Any]) -> None:
    air_panel = selected_panels.get("air_temperature")
    if not isinstance(air_panel, dict):
        return
    graphs = air_panel.get("graphs")
    if not isinstance(graphs, list):
        return

    for graph in graphs:
        if not isinstance(graph, dict):
            continue
        if graph.get("id") != "t2m_annual":
            continue

        # Demo variant is static yearly view only.
        graph.pop("animation", None)
        series = graph.get("series")
        if not isinstance(series, list):
            continue
        keep_keys = {"t2m_yearly_mean", "t2m_yearly_mean_5y", "t2m_yearly_trend"}
        graph["series"] = [
            s for s in series if isinstance(s, dict) and s.get("key") in keep_keys
        ]


def _collect_panel_metric_ids(
    selected_panels: dict[str, Any],
) -> tuple[set[str], set[str]]:
    metric_ids: set[str] = set()
    score_map_ids: set[str] = set()
    for panel in selected_panels.values():
        if not isinstance(panel, dict):
            continue
        score_map_id = panel.get("score_map_id")
        if isinstance(score_map_id, str) and score_map_id:
            score_map_ids.add(score_map_id)
        graphs = panel.get("graphs", [])
        if not isinstance(graphs, list):
            continue
        for graph in graphs:
            if not isinstance(graph, dict):
                continue
            series = graph.get("series", [])
            if not isinstance(series, list):
                continue
            for item in series:
                if not isinstance(item, dict):
                    continue
                metric = item.get("metric")
                if isinstance(metric, str) and metric:
                    metric_ids.add(metric)
    return metric_ids, score_map_ids


def _resolve_map_metric_dependencies(map_spec: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    source_metric = map_spec.get("source_metric")
    if isinstance(source_metric, str) and source_metric:
        out.add(source_metric)
    reducer = map_spec.get("reducer")
    if isinstance(reducer, dict):
        cmip_metric = reducer.get("cmip_offset_metric")
        if isinstance(cmip_metric, str) and cmip_metric:
            out.add(cmip_metric)
    return out


def _expand_derived_metrics(
    metric_ids: set[str], metrics_manifest: dict[str, Any]
) -> set[str]:
    out = set(metric_ids)
    queue = list(metric_ids)
    while queue:
        metric_id = queue.pop()
        spec = metrics_manifest.get(metric_id)
        if not isinstance(spec, dict):
            raise ValueError(f"Unknown metric id in demo selection: {metric_id}")
        source = spec.get("source", {})
        if not isinstance(source, dict):
            continue
        if source.get("type") != "derived":
            continue
        for dep in source.get("inputs", []) or []:
            dep_id = str(dep)
            if dep_id not in out:
                out.add(dep_id)
                queue.append(dep_id)
    return out


def _filter_registries(
    *,
    profile: DemoProfile,
    datasets_manifest: dict[str, Any],
    metrics_manifest: dict[str, Any],
    maps_manifest: dict[str, Any],
    layers_manifest: dict[str, Any],
    panels_manifest: dict[str, Any],
    demo_mask_file: str | None,
) -> tuple[
    dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]
]:
    selected_panels, _graph_metrics_raw, _score_map_ids_raw = _extract_graph_metrics(
        panels_manifest, profile
    )
    _sanitize_demo_panel_graphs(selected_panels)
    graph_metrics, score_map_ids = _collect_panel_metric_ids(selected_panels)

    selected_layers: dict[str, Any] = {"version": layers_manifest.get("version", "0.1")}
    selected_map_ids: set[str] = set(score_map_ids)
    for layer_id in sorted(profile.layer_ids):
        spec = layers_manifest.get(layer_id)
        if not isinstance(spec, dict):
            raise ValueError(f"Layer '{layer_id}' not found in layers manifest.")
        selected_layers[layer_id] = copy.deepcopy(spec)
        map_id = spec.get("map_id")
        if isinstance(map_id, str) and map_id:
            selected_map_ids.add(map_id)

    selected_maps: dict[str, Any] = {"version": maps_manifest.get("version", "0.1")}
    map_metrics: set[str] = set()
    for map_id in sorted(selected_map_ids):
        map_spec = maps_manifest.get(map_id)
        if not isinstance(map_spec, dict):
            raise ValueError(f"Map '{map_id}' not found in maps manifest.")
        selected_maps[map_id] = copy.deepcopy(map_spec)
        map_metrics.update(_resolve_map_metric_dependencies(map_spec))

    selected_metric_ids = _expand_derived_metrics(
        graph_metrics | map_metrics,
        metrics_manifest,
    )
    selected_metrics: dict[str, Any] = {
        "version": metrics_manifest.get("version", "0.1")
    }
    selected_dataset_refs: set[str] = set()
    for metric_id in sorted(selected_metric_ids):
        metric_spec = metrics_manifest.get(metric_id)
        if not isinstance(metric_spec, dict):
            raise ValueError(f"Metric '{metric_id}' not found in metrics manifest.")
        selected_metrics[metric_id] = copy.deepcopy(metric_spec)
        source = metric_spec.get("source", {})
        if isinstance(source, dict):
            dataset_ref = source.get("dataset_ref")
            if isinstance(dataset_ref, str) and dataset_ref:
                selected_dataset_refs.add(dataset_ref)

    selected_datasets: dict[str, Any] = {
        "version": datasets_manifest.get("version", "0.1")
    }
    for dataset_id in sorted(selected_dataset_refs):
        dataset_spec = datasets_manifest.get(dataset_id)
        if not isinstance(dataset_spec, dict):
            raise ValueError(f"Dataset '{dataset_id}' not found in datasets manifest.")
        selected_datasets[dataset_id] = copy.deepcopy(dataset_spec)

    if "crw_dhw_daily" in selected_datasets:
        if not demo_mask_file:
            raise ValueError(
                "Demo selection includes 'crw_dhw_daily' but no demo reef mask file was provided."
            )
        source = selected_datasets["crw_dhw_daily"].get("source")
        if not isinstance(source, dict):
            raise ValueError("Dataset 'crw_dhw_daily' has invalid source definition.")
        source["mask_file"] = demo_mask_file

    selected_panels_manifest = {
        "version": panels_manifest.get("version", "0.1"),
        "panels": selected_panels,
    }

    return (
        selected_datasets,
        selected_metrics,
        selected_maps,
        selected_layers,
        selected_panels_manifest,
    )


def _validate_demo_registries(registry_dir: Path) -> None:
    datasets_path = registry_dir / "datasets.json"
    metrics_path = registry_dir / "metrics.json"
    maps_path = registry_dir / "maps.json"
    layers_path = registry_dir / "layers.json"
    panels_path = registry_dir / "panels.json"

    metrics_manifest = load_metrics(
        path=metrics_path,
        datasets_path=datasets_path,
        validate=True,
    )
    maps_manifest = load_maps(path=maps_path, validate=True)
    validate_maps_against_metrics(maps_manifest, metrics_manifest)

    layers_manifest = load_layers(path=layers_path, validate=True)
    validate_layers_against_maps(layers_manifest, maps_manifest)

    panels_manifest = load_panels(path=panels_path, validate=True)
    validate_panels_against_metrics(panels_manifest, metrics_manifest)
    validate_panels_against_maps(panels_manifest, maps_manifest)


def _path_in_data_root(path: Path, data_root: Path) -> Path:
    resolved = path.resolve()
    root_resolved = data_root.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"Path is not under data root: {path}") from exc
    return resolved


def _copy_file_into_stage(*, src: Path, data_root: Path, stage_root: Path) -> None:
    src_resolved = _path_in_data_root(src, data_root)
    rel = src_resolved.relative_to(data_root.resolve())
    dst = stage_root / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_resolved, dst)


def _write_demo_readme(*, path: Path, selected_datasets: dict[str, Any]) -> None:
    dataset_ids = {k for k in selected_datasets if k != "version"}
    lines: list[str] = [
        "# Climate Demo Package",
        "",
        "This archive is a self-contained demo dataset for the Climate project.",
        "It contains pre-processed climate data series, map tiles, and a location",
        "index that let you run the service locally with real data.",
        "",
        "## Contents",
        "",
        "- `data/releases/demo/` — pre-processed climate metrics and map tiles",
        "- `data/locations/` — location search index",
        "- `data/masks/` — domain masks",
        "",
        "## Data Licenses and Attributions",
        "",
    ]

    if {"era5_daily_t2m", "era5_monthly_t2m"} & dataset_ids:
        lines += [
            "### ERA5 — Copernicus Climate Data Store (C3S / ECMWF)",
            "",
            "License: [Creative Commons Attribution 4.0 (CC BY 4.0)]"
            "(https://creativecommons.org/licenses/by/4.0/)",
            "",
            "Contains modified Copernicus Climate Change Service information.",
            "Dataset: [ERA5 daily statistics on single levels]"
            "(https://cds.climate.copernicus.eu/datasets/derived-era5-single-levels-daily-statistics)",
            "",
        ]

    if "cmip6_historical_tas_monthly_5model_mean" in dataset_ids:
        spec = selected_datasets.get("cmip6_historical_tas_monthly_5model_mean", {})
        models: list[str] = []
        try:
            models = list(spec["source"]["params"]["request_template"]["model"])
        except (KeyError, TypeError):
            pass
        model_list = ", ".join(models) if models else "see dataset page"
        lines += [
            "### CMIP6 — Coupled Model Intercomparison Project Phase 6",
            "",
            "License: [CMIP6 Terms of Use](https://pcmdi.llnl.gov/CMIP6/TermsOfUse)",
            "",
            "Sourced via the Copernicus Climate Data Store: [projections-cmip6]"
            "(https://cds.climate.copernicus.eu/datasets/projections-cmip6)",
            f"Models used: {model_list}",
            "",
        ]

    lines += [
        "### GeoNames",
        "",
        "License: [Creative Commons Attribution 4.0 (CC BY 4.0)]"
        "(https://creativecommons.org/licenses/by/4.0/)",
        "",
        "Used for location search index.",
        "Source: [geonames.org](https://www.geonames.org/)",
        "",
        "### Natural Earth",
        "",
        "License: Public Domain"
        " ([terms of use](https://www.naturalearthdata.com/about/terms-of-use/))",
        "",
        "Used for ocean and land mask preprocessing.",
        "Source: [naturalearthdata.com](https://www.naturalearthdata.com/)",
        "",
    ]

    if "oisst_sst_v21_daily" in dataset_ids:
        lines += [
            "### OISST v2.1 — NOAA Optimum Interpolation SST",
            "",
            "May be used and redistributed free of charge; not for legal use.",
            "Dataset: [OISST v2.1 daily SST]"
            "(https://coastwatch.pfeg.noaa.gov/erddap/info/ncdcOisst21Agg_LonPM180/index.html)",
            "",
        ]

    if "crw_dhw_daily" in dataset_ids:
        lines += [
            "### NOAA Coral Reef Watch — Degree Heating Week",
            "",
            "Available without restriction. Data courtesy of NOAA Coral Reef Watch.",
            "Dataset: [CRW DHW daily]"
            "(https://coastwatch.noaa.gov/erddap/info/noaacrwdhwDaily/index.html)",
            "Citation guidance: [recommendations for CRW citation]"
            "(https://coralreefwatch.noaa.gov/satellite/docs/recommendations_crw_citation.php)",
            "",
        ]

    while lines and lines[-1] == "":
        lines.pop()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_archive(
    *,
    archive_path: Path,
    checksum_path: Path,
    data_root: Path,
    release_root: Path,
    mask_paths: set[Path],
    selected_datasets: dict[str, Any],
) -> None:
    with tempfile.TemporaryDirectory(prefix="demo_release_stage_") as tmp:
        stage = Path(tmp)
        stage_data = stage / "data"
        for location_path in DEFAULT_REQUIRED_LOCATION_FILES:
            src = Path(location_path)
            if not src.exists():
                raise FileNotFoundError(f"Missing required location file: {src}")
            _copy_file_into_stage(src=src, data_root=data_root, stage_root=stage_data)

        for mask_path in sorted(mask_paths):
            if not mask_path.exists():
                raise FileNotFoundError(f"Missing required mask file: {mask_path}")
            _copy_file_into_stage(
                src=mask_path, data_root=data_root, stage_root=stage_data
            )

        release_root_resolved = _path_in_data_root(release_root, data_root)
        release_rel = release_root_resolved.relative_to(data_root.resolve())
        release_dst = stage_data / release_rel
        if release_dst.exists():
            shutil.rmtree(release_dst)
        shutil.copytree(release_root_resolved, release_dst)

        _write_demo_readme(path=stage / "README.md", selected_datasets=selected_datasets)

        archive_path.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive_path, mode="w:gz") as tar:
            for file_path in sorted(stage.rglob("*")):
                if not file_path.is_file():
                    continue
                arcname = str(file_path.relative_to(stage))
                tar.add(file_path, arcname=arcname, recursive=False)

    digest = hashlib.sha256()
    with archive_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    checksum_path.write_text(
        f"{digest.hexdigest()}  {archive_path.name}\n", encoding="utf-8"
    )


def _collect_required_masks(
    *,
    datasets_manifest: dict[str, Any],
    explicit_mask: Path | None,
) -> set[Path]:
    out: set[Path] = set()
    if explicit_mask is not None:
        out.add(explicit_mask)
    for key, value in datasets_manifest.items():
        if key == "version" or not isinstance(value, dict):
            continue
        source = value.get("source", {})
        if not isinstance(source, dict):
            continue
        mask_file = source.get("mask_file")
        if isinstance(mask_file, str) and mask_file:
            out.add(Path(mask_file))
    return out


def _validate_packaged_release(*, release_root: Path) -> None:
    required = (
        release_root / "series",
        release_root / "maps",
        release_root / "registry" / "datasets.json",
        release_root / "registry" / "metrics.json",
        release_root / "registry" / "maps.json",
        release_root / "registry" / "layers.json",
        release_root / "registry" / "panels.json",
        release_root / "manifest.json",
    )
    missing = [path for path in required if not path.exists()]
    if missing:
        lines = "\n".join(str(path) for path in missing)
        raise FileNotFoundError(f"Packaged release is missing required files:\n{lines}")

    datasets_path = release_root / "registry" / "datasets.json"
    datasets_manifest = _load_json(datasets_path)
    if isinstance(datasets_manifest.get("crw_dhw_daily"), dict):
        sparse_mask = release_root / "aux" / "sparse_risk_global_0p25_mask.npz"
        if not sparse_mask.exists():
            raise FileNotFoundError(
                "Packaged release includes crw_dhw_daily but is missing sparse-risk mask: "
                f"{sparse_mask}"
            )


def _copy_tree_with_resume(*, src: Path, dst: Path, resume: bool) -> int:
    if not src.exists():
        raise FileNotFoundError(f"Source path does not exist: {src}")
    if not src.is_dir():
        raise ValueError(f"Source path is not a directory: {src}")

    copied = 0
    for path in src.rglob("*"):
        rel = path.relative_to(src)
        out = dst / rel
        if path.is_dir():
            out.mkdir(parents=True, exist_ok=True)
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        if resume and out.exists():
            continue
        shutil.copy2(path, out)
        copied += 1
    return copied


def _copy_selected_series_from_release(
    *,
    source_root: Path,
    release_root: Path,
    selected_metrics: dict[str, Any],
    resume: bool,
) -> tuple[int, int]:
    source_series_root = source_root / "series"
    if not source_series_root.exists():
        raise FileNotFoundError(
            f"Source release missing series folder: {source_series_root}"
        )

    copied_files = 0
    copied_metrics = 0
    for metric_id, spec in sorted(selected_metrics.items()):
        if metric_id == "version" or not isinstance(spec, dict):
            continue
        source = spec.get("source", {})
        if isinstance(source, dict) and source.get("type") == "derived":
            continue

        metric_dirs = sorted(
            p for p in source_series_root.glob(f"*/{metric_id}") if p.is_dir()
        )
        if not metric_dirs:
            raise FileNotFoundError(
                f"Missing metric series in source release for '{metric_id}' under {source_series_root}"
            )
        copied_metrics += 1
        for src_dir in metric_dirs:
            rel = src_dir.relative_to(source_series_root)
            dst_dir = release_root / "series" / rel
            copied_files += _copy_tree_with_resume(
                src=src_dir, dst=dst_dir, resume=resume
            )

    return copied_files, copied_metrics


def _copy_selected_maps_from_release(
    *,
    source_root: Path,
    release_root: Path,
    selected_maps: dict[str, Any],
    resume: bool,
) -> tuple[int, int]:
    source_maps_root = source_root / "maps"
    if not source_maps_root.exists():
        raise FileNotFoundError(
            f"Source release missing maps folder: {source_maps_root}"
        )

    copied_files = 0
    copied_maps = 0
    for map_id, spec in sorted(selected_maps.items()):
        if map_id == "version" or not isinstance(spec, dict):
            continue
        map_dirs = sorted(p for p in source_maps_root.glob(f"*/{map_id}") if p.is_dir())
        if not map_dirs:
            raise FileNotFoundError(
                f"Missing map assets in source release for '{map_id}' under {source_maps_root}"
            )
        copied_maps += 1
        for src_dir in map_dirs:
            rel = src_dir.relative_to(source_maps_root)
            dst_dir = release_root / "maps" / rel
            copied_files += _copy_tree_with_resume(
                src=src_dir, dst=dst_dir, resume=resume
            )

    return copied_files, copied_maps


def _snapshot_registry_to_release(
    *,
    release_root: Path,
    selected_datasets: dict[str, Any],
    selected_metrics: dict[str, Any],
    selected_maps: dict[str, Any],
    selected_layers: dict[str, Any],
    selected_panels: dict[str, Any],
) -> dict[str, str]:
    registry_dir = release_root / "registry"
    _write_json(registry_dir / "datasets.json", selected_datasets)
    _write_json(registry_dir / "metrics.json", selected_metrics)
    _write_json(registry_dir / "maps.json", selected_maps)
    _write_json(registry_dir / "layers.json", selected_layers)
    _write_json(registry_dir / "panels.json", selected_panels)
    return {
        "datasets.json": "registry/datasets.json",
        "metrics.json": "registry/metrics.json",
        "maps.json": "registry/maps.json",
        "layers.json": "registry/layers.json",
        "panels.json": "registry/panels.json",
    }


def _write_release_manifest(
    *,
    release_root: Path,
    release: str,
    series_root: Path,
    maps_root: Path,
    registry_snapshot: dict[str, str],
) -> Path:
    payload = {
        "release": release,
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "series_root": str(series_root.relative_to(release_root)),
        "maps_root": str(maps_root.relative_to(release_root)),
        "registry": registry_snapshot,
    }
    manifest_path = release_root / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8"
    )
    return manifest_path


def _resolve_archive_path(
    *,
    archive_output: Path | None,
    dist_root: Path,
    release: str,
) -> Path:
    if archive_output is not None:
        return archive_output
    stamp = datetime.now().strftime("%Y_%m_%d")
    name = f"climate-{release}-{stamp}.tar.gz"
    return dist_root / name


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a self-contained demo release package under data/releases/<release>.",
    )
    parser.add_argument("--release", type=str, default="demo")
    parser.add_argument(
        "--profile", type=str, default=DEFAULT_PROFILE, choices=[DEFAULT_PROFILE]
    )
    parser.add_argument(
        "--gbr-bbox",
        type=str,
        default=",".join(str(v) for v in DEFAULT_GBR_BBOX),
        help="lat_min,lat_max,lon_min,lon_max",
    )
    parser.add_argument("--base-reef-mask", type=Path, default=DEFAULT_BASE_REEF_MASK)
    parser.add_argument("--demo-reef-mask", type=Path, default=DEFAULT_DEMO_REEF_MASK)
    parser.add_argument(
        "--demo-sparse-risk-mask",
        type=Path,
        default=DEFAULT_DEMO_SPARSE_RISK_MASK,
        help="Output sparse-risk mask path derived from demo reef mask.",
    )

    parser.add_argument(
        "--datasets-path", type=Path, default=Path("registry/datasets.json")
    )
    parser.add_argument(
        "--metrics-path", type=Path, default=Path("registry/metrics.json")
    )
    parser.add_argument("--maps-path", type=Path, default=Path("registry/maps.json"))
    parser.add_argument(
        "--layers-path", type=Path, default=Path("registry/layers.json")
    )
    parser.add_argument(
        "--panels-path", type=Path, default=Path("registry/panels.json")
    )

    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--releases-root", type=Path, default=DEFAULT_RELEASES_ROOT)
    parser.add_argument("--dist-root", type=Path, default=DEFAULT_DIST_ROOT)
    parser.add_argument("--archive-output", type=Path, default=None)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("data/cache"),
        help="Packager cache root for CDS/ERDDAP downloads (default: data/cache).",
    )

    parser.add_argument("--start-year", type=int, default=None)
    parser.add_argument("--end-year", type=int, default=None)
    parser.add_argument("--pipeline", action="store_true")
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--dask", action="store_true")
    parser.add_argument("--dask-chunk-lat", type=int, default=16)
    parser.add_argument("--dask-chunk-lon", type=int, default=16)
    parser.add_argument("--skip-package", action="store_true")
    parser.add_argument("--skip-archive", action="store_true")
    parser.add_argument(
        "--source-release",
        type=str,
        default=None,
        help=(
            "Reuse already packaged assets from data/releases/<source-release> "
            "(copies series/maps instead of recomputing tiles)."
        ),
    )
    parser.add_argument(
        "--skip-dhw-metrics",
        action="store_true",
        help="Exclude coral-reef DHW panel/layers/metrics and skip GBR demo-mask generation.",
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--clean", action="store_true")
    parser.add_argument(
        "--keep-local-release",
        action="store_true",
        help="Keep local data/releases/<release> and data/releases/<release>_build after archive creation.",
    )
    parser.add_argument("--debug", action="store_true")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    if args.clean and args.resume:
        raise ValueError(
            "Do not combine --clean with --resume. --clean removes prior release outputs."
        )
    if args.skip_package and args.source_release:
        raise ValueError("Do not combine --skip-package with --source-release.")
    profile = _default_profile(skip_dhw_metrics=bool(args.skip_dhw_metrics))
    bbox = _parse_bbox(args.gbr_bbox)

    releases_root = Path(args.releases_root)
    release_root = releases_root / args.release
    build_root = releases_root / f"{args.release}_build"
    registry_out = build_root / "registry"

    if args.clean:
        if build_root.exists():
            shutil.rmtree(build_root)
        if release_root.exists():
            shutil.rmtree(release_root)

    demo_mask_path: Path | None = None
    demo_sparse_risk_mask_path: Path | None = None
    if not args.skip_dhw_metrics:
        demo_mask_path = _build_gbr_demo_mask(
            base_mask_path=Path(args.base_reef_mask),
            output_path=Path(args.demo_reef_mask),
            bbox=bbox,
        )
        demo_sparse_risk_mask_path = _build_sparse_risk_mask_from_fine_mask(
            fine_mask_path=Path(demo_mask_path),
            output_path=Path(args.demo_sparse_risk_mask),
            target_deg=0.25,
        )
    else:
        print(
            "[mask] skip-dhw-metrics enabled; skipping GBR demo reef mask generation."
        )

    datasets_manifest = _load_json(Path(args.datasets_path))
    metrics_manifest = _load_json(Path(args.metrics_path))
    maps_manifest = _load_json(Path(args.maps_path))
    layers_manifest = _load_json(Path(args.layers_path))
    panels_manifest = _load_json(Path(args.panels_path))

    (
        selected_datasets,
        selected_metrics,
        selected_maps,
        selected_layers,
        selected_panels,
    ) = _filter_registries(
        profile=profile,
        datasets_manifest=datasets_manifest,
        metrics_manifest=metrics_manifest,
        maps_manifest=maps_manifest,
        layers_manifest=layers_manifest,
        panels_manifest=panels_manifest,
        demo_mask_file=str(demo_mask_path) if demo_mask_path is not None else None,
    )

    _write_json(registry_out / "datasets.json", selected_datasets)
    _write_json(registry_out / "metrics.json", selected_metrics)
    _write_json(registry_out / "maps.json", selected_maps)
    _write_json(registry_out / "layers.json", selected_layers)
    _write_json(registry_out / "panels.json", selected_panels)
    _validate_demo_registries(registry_out)
    print(f"[registry] wrote and validated demo registries in {registry_out}")
    selected_metric_ids = sorted(
        key
        for key, value in selected_metrics.items()
        if key != "version" and isinstance(value, dict)
    )

    if not args.skip_package:
        if args.source_release:
            source_release = str(args.source_release).strip()
            if not source_release:
                raise ValueError("--source-release cannot be empty.")
            if source_release == args.release:
                raise ValueError("--source-release must be different from --release.")

            source_root = releases_root / source_release
            if not source_root.exists():
                raise FileNotFoundError(f"Source release does not exist: {source_root}")

            copied_series_files, copied_metrics = _copy_selected_series_from_release(
                source_root=source_root,
                release_root=release_root,
                selected_metrics=selected_metrics,
                resume=bool(args.resume),
            )
            copied_maps_files, copied_maps = _copy_selected_maps_from_release(
                source_root=source_root,
                release_root=release_root,
                selected_maps=selected_maps,
                resume=bool(args.resume),
            )
            print(
                f"[release] copied assets from {source_root} -> {release_root} "
                f"(metrics={copied_metrics}, maps={copied_maps}, "
                f"series files={copied_series_files}, maps files={copied_maps_files})"
            )

            registry_snapshot = _snapshot_registry_to_release(
                release_root=release_root,
                selected_datasets=selected_datasets,
                selected_metrics=selected_metrics,
                selected_maps=selected_maps,
                selected_layers=selected_layers,
                selected_panels=selected_panels,
            )
            _write_release_manifest(
                release_root=release_root,
                release=args.release,
                series_root=release_root / "series",
                maps_root=release_root / "maps",
                registry_snapshot=registry_snapshot,
            )
        else:
            from climate.packager.registry import package_registry

            package_registry(
                out_root=release_root / "series",
                release=args.release,
                metrics_path=registry_out / "metrics.json",
                datasets_path=registry_out / "datasets.json",
                maps_path=registry_out / "maps.json",
                layers_path=registry_out / "layers.json",
                panels_path=registry_out / "panels.json",
                maps_out_root=release_root / "maps",
                cache_dir=Path(args.cache_dir),
                metric_ids=selected_metric_ids,
                start_year=args.start_year,
                end_year=args.end_year,
                pipeline=bool(args.pipeline),
                workers=args.workers,
                dask_enabled=bool(args.dask),
                dask_chunk_lat=int(args.dask_chunk_lat),
                dask_chunk_lon=int(args.dask_chunk_lon),
                all_maps=True,
                resume=bool(args.resume),
                debug=bool(args.debug),
            )
        if demo_sparse_risk_mask_path is not None:
            aux_mask = release_root / "aux" / "sparse_risk_global_0p25_mask.npz"
            aux_mask.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(demo_sparse_risk_mask_path, aux_mask)
            print(f"[release] wrote sparse-risk aux mask: {aux_mask}")
        _validate_packaged_release(release_root=release_root)
        print(f"[release] packaged and validated {release_root}")
    else:
        print("[release] skip-package enabled; not running packager.")

    if args.skip_archive:
        print("[archive] skip-archive enabled; archive generation skipped.")
        return

    if not release_root.exists():
        raise FileNotFoundError(
            f"Release root does not exist for archiving: {release_root}. "
            "Run without --skip-package or build release assets first."
        )

    archive_path = _resolve_archive_path(
        archive_output=args.archive_output,
        dist_root=Path(args.dist_root),
        release=args.release,
    )
    if archive_path.suffixes[-2:] != [".tar", ".gz"]:
        raise ValueError(f"Archive output must end with .tar.gz, got: {archive_path}")
    checksum_path = archive_path.with_suffix(archive_path.suffix + ".sha256")
    mask_paths = _collect_required_masks(
        datasets_manifest=selected_datasets,
        explicit_mask=demo_mask_path,
    )
    _build_archive(
        archive_path=archive_path,
        checksum_path=checksum_path,
        data_root=Path(args.data_root),
        release_root=release_root,
        mask_paths=mask_paths,
        selected_datasets=selected_datasets,
    )
    print(f"[archive] wrote {archive_path}")
    print(f"[archive] wrote {checksum_path}")
    if not args.keep_local_release:
        if release_root.exists():
            shutil.rmtree(release_root)
            print(f"[cleanup] removed local release folder: {release_root}")
        if build_root.exists():
            shutil.rmtree(build_root)
            print(f"[cleanup] removed local build folder: {build_root}")


if __name__ == "__main__":
    main()
