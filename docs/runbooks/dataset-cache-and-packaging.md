# Runbook: Dataset Cache and Packaging (Metrics + Maps)

Use this runbook to materialize release assets from source datasets and registries.

What you are building:

- time-series tiles for registry metrics
- map/layer assets consumed by the web application
- release-structured outputs under `data/releases/<release>/`

Where it is used:

- backend panel/graph/map APIs
- frontend rendering of maps, layers, and derived metric series
- validation and release smoke checks

## Data Sources

This pipeline typically pulls source data from two families of services:

- CDS (Copernicus Climate Data Store): catalog/API used to retrieve climate reanalysis datasets (including ERA5). In this repository, CDS-backed fetches feed part of the dataset cache used by metric materialization.
- ERDDAP servers: REST-style dataset servers used to query gridded data subsets and time ranges. In this repository, ERDDAP-backed fetches feed caches and mask derivation workflows used by metrics/maps.

Reference links:

- CDS portal: <https://cds.climate.copernicus.eu/>
- CDS datasets (ERA5 single levels): <https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels>
- CDS API setup and credentials: <https://cds.climate.copernicus.eu/how-to-api>
- ERDDAP home: <https://coastwatch.pfeg.noaa.gov/erddap/index.html>
- ERDDAP documentation/info: <https://coastwatch.pfeg.noaa.gov/erddap/information.html>
- ERDDAP griddap documentation: <https://coastwatch.pfeg.noaa.gov/erddap/griddap/documentation.html>

## Input Data Sources

- Dataset registry (`registry/datasets.json`): declares source backend/type, variables, masks, and processing metadata
- Metrics/maps/layers registries (`registry/metrics.json`, `registry/maps.json`, `registry/layers.json`): define what to compute and publish
- Remote source data fetched through CDS and/or ERDDAP according to registry definitions

## Environment Setup (Recommended)

Conda (Anaconda or Miniconda) is recommended for reproducible local runs.

```bash
conda create -n <your-env-name> python=3.11
conda activate <your-env-name>
export PYTHONPATH="$(pwd)"
```

You can install Python dependencies manually outside Conda, but this is not recommended.

Optional CDS credentials (`~/.cdsapirc`) are required for ERA5-backed downloads. See the CDS API/credential guide: <https://cds.climate.copernicus.eu/how-to-api>.

## Core packaging command

```bash
python scripts/build/packager.py --release dev --all --all-maps
```

## Suggested Approach

When starting from scratch, avoid running a full multi-metric build first. A full run may trigger very large downloads (often tens of thousands of files depending on variable granularity/time partitioning).

Recommended sequence:

1. Start with one metric (or a very small metric subset).
2. Inspect `data/cache/` and `data/releases/<release>/` outputs to understand file layout and growth.
3. Validate that the API/frontend can read those assets.
4. Expand progressively to additional metrics/maps.

Outputs under:

- `data/releases/dev/series/` (metric tile binaries and time-axis artifacts used by API graph/panel reads)
- `data/releases/dev/maps/` (generated map/layer assets used by frontend map rendering)
- `data/releases/dev/registry/` (release-pinned registry snapshots for non-`dev` release workflows)

## Useful variants

Pipeline mode with workers:

```bash
python scripts/build/packager.py --release dev --all --all-maps --pipeline --workers 4
```

Batch tiles:

```bash
python scripts/build/packager.py --release dev --all --all-maps --batch-tiles 4
```

Resume an interrupted run:

```bash
python scripts/build/packager.py --release dev --all --all-maps --resume
```

Download-only prefill:

```bash
python scripts/build/packager.py --release dev --all --all-maps --download-only
```

## Cache location

Default cache directory:

- `data/cache/` (downloaded/intermediate source data used during packaging and aggregation)

Override cache root:

```bash
python scripts/build/packager.py --release dev --all --all-maps --cache-dir /path/to/cache
```

## Related runbooks

- Locations/ocean prerequisites: [`docs/runbooks/locations-and-ocean-mask.md`](locations-and-ocean-mask.md)
- Reef-domain masks: [`docs/runbooks/reef-mask.md`](reef-mask.md)
