# Runbook: Demo Release Package

Use this runbook to build a self-contained `demo` release bundle that can be unpacked into `data/` on a fresh clone.

## Environment

```bash
conda activate climate
export PYTHONPATH="$(pwd)"
```

## What The Script Does

`scripts/build/build_demo_release.py` orchestrates:

1. GBR-truncated reef mask creation:
   - `data/masks/crw_dhw_daily_gbr_demo_global_0p05_mask.npz`
2. Demo registry filtering:
   - `data/releases/demo_build/registry/{datasets,metrics,maps,layers,panels}.json`
3. Release packaging into:
   - `data/releases/demo/{series,maps,registry,manifest.json}`
4. Archive + checksum generation:
   - `dist/climate-demo-YYYY_MM_DD.tar.gz`
   - `dist/climate-demo-YYYY_MM_DD.tar.gz.sha256`

Packaging can run in two modes:

- compute mode (default): generate series/maps from cache (and download if cache is missing)
- copy mode (`--source-release <name>`): copy required demo assets from `data/releases/<name>` without recomputing tiles

The archive layout is rooted under `data/` (`data/locations`, `data/masks`, `data/releases/demo`), so users can extract directly at repository root.

## Dry Run (No Packaging, No Archive)

Use this to validate GBR mask + registry pruning only:

```bash
PYTHONPATH=. python scripts/build/build_demo_release.py --skip-package --skip-archive
```

## Full Build

```bash
PYTHONPATH=. python scripts/build/build_demo_release.py --release demo
```

## Fast Build For Testing (No Tile Recompute)

Use this when you only need a quick demo bundle (for example, cloud VM install testing) and already have a populated source release like `dev`.

```bash
PYTHONPATH=. python scripts/build/build_demo_release.py \
  --release demo \
  --source-release dev \
  --resume
```

Notes:

- In copy mode, the script copies only metrics/maps selected by the demo registries.
- `--skip-dhw-metrics` is respected in copy mode (DHW assets are not copied).
- If a required selected asset is missing in the source release, the script fails fast with an error.

Useful flags:

- `--resume` to continue interrupted packager runs
- `--source-release <release>` to reuse packaged assets from `data/releases/<release>` (copy selected demo assets only)
- `--cache-dir /path/to/cache` to reuse an external cache root
- `--skip-dhw-metrics` to exclude coral/DHW metrics for faster non-DHW testing
- `--pipeline --workers N` to use packager pipeline mode
- `--dask --dask-chunk-lat 64 --dask-chunk-lon 64` for dask-backed processing
- `--start-year <int> --end-year <int>` to cap packaged years
- `--gbr-bbox "lat_min,lat_max,lon_min,lon_max"` to override defaults
- `--clean` to remove prior `data/releases/demo` and `data/releases/demo_build`
- `--keep-local-release` to keep `data/releases/demo` and `data/releases/demo_build` after archive creation (default is cleanup)
- `--archive-output dist/custom-name.tar.gz` to set archive filename

## Local Smoke Check

```bash
RELEASE=demo ./scripts/api_backend.sh
cd web
npm run dev
```

Verify:

- map layers load and switch correctly
- panel graphs load for air/sea/coral reef workflows

## Publishing

Upload `dist/*.tar.gz` and its `.sha256` file as GitHub Release assets.
