# Runbook: Dataset Cache and Packaging (Metrics + Maps)

Use this runbook to materialize release assets from source datasets and registries.

What you are building:

- time-series tiles for registry metrics (including derived tiled metrics)
- precomputed city ranking JSON files for fast extreme-location queries
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

- `data/releases/dev/series/` (metric tile binaries, time-axis artifacts, and ranking JSON files)
- `data/releases/dev/maps/` (generated map/layer assets used by frontend map rendering)
- `data/releases/dev/registry/` (release-pinned registry snapshots for non-`dev` release workflows)

Series layout within a metric folder:

```
data/releases/dev/series/<grid_id>/<metric_id>/
  z64/                          ← tile binaries (r000_c000.bin.zst …)
  time/yearly.json              ← time axis
  rankings/                     ← precomputed city rankings (generated separately, see below)
    mean.json
    trend_slope.json
```

### Derived tiled metrics

Metrics declared with `"source": {"type": "derived"}` and `"storage": {"tiled": true}` in `registry/metrics.json` are computed automatically by the packager at the end of each run — no extra flags needed. The packager reads already-materialized input tiles and writes output tiles using the declared derivation function (e.g. OLS warming trend, blended pre-industrial anomaly). Re-run with `--resume` to skip tiles already written.

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

## Post-packaging: Precompute city rankings

After the packager completes, run this script to generate precomputed ranking files for all metrics that declare a `rankings` field in `registry/metrics.json`:

```bash
python scripts/precompute_city_rankings.py --release dev
```

This scans all cities (population ≥ 1 000) against the tile data and writes one sorted JSON file per declared aggregation under each metric's `rankings/` folder. The API loads these at startup and uses them as a fast path for the chat `find_extreme_location` tool.

To regenerate rankings for a specific metric only:

```bash
python scripts/precompute_city_rankings.py --release dev --metrics t2m_yearly_mean_c
```

For non-`dev` releases, pass `--releases-root` and `--metrics-path` explicitly:

```bash
python scripts/precompute_city_rankings.py \
  --release 2026_04_10 \
  --releases-root data/releases \
  --metrics-path data/releases/2026_04_10/registry/metrics.json
```

Validate that all expected ranking files are present:

```bash
python scripts/validate/rankings.py
```

## Cache location

Default cache directory:

- `data/cache/` (downloaded/intermediate source data used during packaging and aggregation)

Override cache root:

```bash
python scripts/build/packager.py --release dev --all --all-maps --cache-dir /path/to/cache
```

## Publishing to Production (v2 artifact-store releases)

`publish_release.py` is the single command to publish a new release to the production server. There is no separate artifact-build or manifest-compose step — the script handles diffing, syncing, and versioning in one pass.

### How it works

1. Runs `validate_suite.py` on the local dev release as a pre-flight check (includes `--check-rankings` to verify all declared ranking files are present)
2. Scans `data/releases/dev/series/` and `data/releases/dev/maps/`
3. Computes a `tree_sha256` checksum for each metric and map
4. Fetches the current prod release state via SSH and shows a diff (new / changed / unchanged / removed)
5. Prompts for confirmation, then rsyncs only new or changed artifacts
6. Writes a new v2 release manifest and registry snapshot on the server
7. Optionally updates the `LATEST` pointer

### Publish to production

```bash
python scripts/deploy/publish_release.py \
  --remote <SSH_USER>@<PUBLIC_IP> \
  --remote-releases-root /opt/climate/data/releases \
  --update-latest
```

The release id defaults to today's date (`YYYY_MM_DD`). Pass `--release <id>` to override.

`ARTIFACTS_ROOT` does not need to be set on the server — it defaults to the sibling of `RELEASES_ROOT`, i.e. `/opt/climate/data/artifacts`.

### Local testing (no SSH)

Omit `--remote` to run entirely locally. Useful for testing the v2 code path before deploying:

```bash
python scripts/deploy/publish_release.py \
  --remote-releases-root data/releases \
  --release test_v2 \
  --skip-validate \
  -y
```

This writes artifacts to `data/artifacts/` and creates `data/releases/test_v2/manifest.json`. Point the local API at it by setting `RELEASE=test_v2`.

### Skip pre-flight validation

The pre-flight `validate_suite` run can be skipped when migrating existing data or in other situations where the dev release is not available locally:

```bash
  --skip-validate
```

## Related runbooks

- Locations/ocean prerequisites: [`docs/runbooks/locations-and-ocean-mask.md`](locations-and-ocean-mask.md)
- Reef-domain masks: [`docs/runbooks/reef-mask.md`](reef-mask.md)
- Deployment: [`docs/runbooks/deployment.md`](deployment.md)
