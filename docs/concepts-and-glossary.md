# Concepts and Glossary

This page defines key concepts used across the pipeline, API, and web application.

## Core Concepts

### Grids

A grid is a regular latitude/longitude lattice used to store data as 2D rasters or 3D time stacks.

Examples used in this repository:

- `global_0p25`: global grid with `0.25°` spacing (coarser, faster)
- `global_0p05`: global grid with `0.05°` spacing (finer, heavier)

Interpretation:

- `0.25°` means one cell every quarter degree in latitude and longitude
- smaller degree size = more cells = higher storage/compute cost

### Grid Geometry Model (Strict Cell Grid)

This repository uses a strict **cell-grid** model end-to-end (packaging, API cell lookup, debug bbox, and map textures).

- Each `(i_lat, i_lon)` index represents one area cell.
- Cell centers are:
  - `lat_center = 90 - (i_lat + 0.5) * deg`
  - `lon_center = -180 + (i_lon + 0.5) * deg`
- Cell bounds are:
  - `lat_min = lat_center - deg/2`, `lat_max = lat_center + deg/2`
  - `lon_min = lon_center - deg/2`, `lon_max = lon_center + deg/2`

Strict global dimensions used here:

- `global_0p25`: `720 x 1440` (centers `89.875..-89.875`)
- `global_0p05`: `3600 x 7200` (centers `89.975..-89.975`)

This avoids mixed point-grid/cell-grid semantics and keeps debug cell overlays aligned with raster map pixels.

Illustration (monochrome): [`docs/images/grid-concept-0p25.svg`](images/grid-concept-0p25.svg)

#### Grids by Resolution (Cell Count + Storage Impact)

| Resolution | Grid Dimensions (lat x lon) | Total Cells | Approx size per timestep (float32) | Approx raw size for 40y daily (float32) | Used by |
|---|---|---:|---:|---:|---|
| `1.0°` | `180 x 360` | `64,800` | `0.25 MiB` | `3.5 GiB` | reference |
| `0.25°` (`global_0p25`) | `720 x 1440` | `1,036,800` | `3.96 MiB` | `56.5 GiB` | `t2m`, `sst` |
| `0.05°` (`global_0p05`) | `3600 x 7200` | `25,920,000` | `98.88 MiB` | `1.38 TiB` | `dhw` |

Assumptions:

- raw/uncompressed `float32` storage
- one variable
- `40` years x `365.25` days/year (`~14,610` timesteps)

Practical disk usage in this repository depends on compression, tiling/chunking, time aggregation strategy, and cache retention policy.

### Metrics

A metric is a computed climate variable published to the release artifacts, for example annual means, thresholds, trends, or stress indicators.

In this project, metrics are defined in registries and materialized by the packager into tile-based outputs under `data/releases/<release>/series/`.

#### Derived metrics

A metric can be declared with `"source": {"type": "derived"}` and `"storage": {"tiled": true}` in `registry/metrics.json`. The packager computes these automatically from already-packaged input tiles after the main download loop, without fetching any external data. Supported derivation functions include `trend_slope_per_decade` (OLS warming trend) and `blended_preindustrial_anomaly` (total warming since pre-industrial baseline).

Derived metrics can declare their own `rankings` field (see below) and appear in the LLM metric catalogue like any other metric. An optional `llm_note` string in the metric spec is surfaced as a hint to guide the model toward the right metric for a given question.

#### Rankings

A metric can declare a `rankings` field in `registry/metrics.json` listing one or more aggregations (e.g. `["mean", "trend_slope"]`). After the packager runs, `scripts/precompute_city_rankings.py` computes those aggregations across all cities and writes sorted JSON files:

```
data/releases/<release>/series/<grid_id>/<metric_id>/rankings/<aggregation>.json
```

These files are loaded into memory at API startup and used by the `find_extreme_location` chat tool as a fast path (sub-50 ms) for unfiltered global and continent-scoped queries, avoiding the otherwise 30-second live tile scan.

### Maps and Layers

- A layer is a spatial raster asset (or mask) with visual styling and metadata.
- A map is a composition of one or more layers and supporting configuration used by the web application.

Maps/layers are generated under `data/releases/<release>/maps/`.

### Releases

A release is a versioned package of registry snapshots and pointers to metric tile and map assets.

There are two release formats:

**Format v1** (self-contained): all tiles and maps live inside the release directory.

```
data/releases/<release>/series/<grid_id>/<metric>/z64/...
data/releases/<release>/maps/<grid_id>/<map_id>/<filename>
data/releases/<release>/registry/
```

**Format v2** (artifact-store): tiles and maps are stored as independently versioned artifacts; the release manifest contains pointers to them.

```
data/releases/<release>/manifest.json   ← format_version: 2, series/maps pointers
data/releases/<release>/registry/
data/artifacts/series/<metric_id>/<date>/<grid_id>/<metric_id>/z64/...
data/artifacts/maps/<map_id>/<date>/<filename>
```

The `dev` release always uses the self-contained format and reads registry files from the repo root.

### Artifact Store

The artifact store (`data/artifacts/`) holds independently versioned metric tile sets and map image files. Each artifact is identified by `(<id>, <date>)` and contains a `manifest.json` with a `tree_sha256` checksum written after a successful build.

- Series artifacts: `data/artifacts/series/<metric_id>/<YYYY_MM_DD>/`
- Map artifacts: `data/artifacts/maps/<map_id>/<YYYY_MM_DD>/`

A v2 release manifest declares which artifact version to use for each metric and map. This means only changed artifacts need to be rebuilt and redeployed when updating a release.

## Acronyms

- `CDS`: Climate Data Store (Copernicus) used to access datasets such as ERA5.  
  Link: <https://cds.climate.copernicus.eu/>
- `DHW`: Degree Heating Weeks, a coral heat-stress indicator used in reef workflows.  
  Link: <https://coralreefwatch.noaa.gov/product/5km/index_5km_dhw.php>
- `ERA5`: ECMWF global atmospheric reanalysis dataset family distributed via CDS.  
  Link: <https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels>
- `ERDDAP`: NOAA-developed data server/API for gridded and tabular datasets.  
  Link: <https://coastwatch.pfeg.noaa.gov/erddap/index.html>
- `IPCC`: Intergovernmental Panel on Climate Change.  
  Link: <https://www.ipcc.ch/>
- `NHD`: Number of Hot Days (metric acronym used in this project context).
- `SST`: Sea Surface Temperature.
- `t2m`: 2-meter air temperature (near-surface air temperature variable name).

## Related Docs

- Pipeline diagrams: [`docs/project_pipeline_diagrams.md`](project_pipeline_diagrams.md)
- Packaging runbook: [`docs/runbooks/dataset-cache-and-packaging.md`](runbooks/dataset-cache-and-packaging.md)
