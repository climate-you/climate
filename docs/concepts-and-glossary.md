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

### Maps and Layers

- A layer is a spatial raster asset (or mask) with visual styling and metadata.
- A map is a composition of one or more layers and supporting configuration used by the web application.

Maps/layers are generated under `data/releases/<release>/maps/`.

### Releases

A release is a versioned package of registry snapshots, metric tiles, and map assets.

Typical layout:

- `data/releases/<release>/series/`
- `data/releases/<release>/maps/`
- `data/releases/<release>/registry/`

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
