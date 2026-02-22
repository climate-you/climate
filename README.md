# Climate Data Pipeline + API + Web Demo

## What this repo contains

- `scripts/build/packager.py`: registry-driven data packaging pipeline
- `climate_api/`: FastAPI backend (`panel`, `resolve`, `nearest`, `autocomplete`)
- `web/src/app/page.tsx`: main Next.js front-end page at `/`

## Environment setup

1. Activate Python env and expose the repo package:

```bash
conda activate climate
export PYTHONPATH="$(pwd)"
```

2. Optional CDS credentials in `~/.cdsapirc` for ERA5 downloads:

```yaml
url: https://cds.climate.copernicus.eu/api
key: <your-key>
```

## Data preparation workflow

1. Build locations files used by resolver/autocomplete:

```bash
python scripts/build/build_locations.py --source cities500 --write-index --write-kdtree
```

2. Build ocean mask files used for ocean naming:

```bash
python scripts/build/build_ocean_mask.py
```

3. Package metrics + maps from registry:

```bash
python scripts/build/packager.py --release dev --all --all-maps
```

Useful variants:

```bash
python scripts/build/packager.py --release dev --all --all-maps --pipeline --workers 4
python scripts/build/packager.py --release dev --all --all-maps --batch-tiles 4
```

## DHW reef mask workflow (0.05 deg)

Use this when rebuilding the Coral Reef DHW domain mask.

1. Build reef masks (UNEP + NE, both `all_touched`).
   These scripts auto-download and cache sources under `data/cache/geojson/` by default:

```bash
python scripts/build/build_reef_mask.py \
  --source unep_wcmc \
  --grid-id global_0p05 \
  --all-touched \
  --output-npz data/masks/reef_unep_all_touched_global_0p05_mask.npz

python scripts/build/build_reef_mask.py \
  --source natural_earth \
  --grid-id global_0p05 \
  --all-touched \
  --output-npz data/masks/reef_ne_all_touched_global_0p05_mask.npz
```

If UNEP TLS fails on your machine, pass `--insecure` for that command only.

2. Build DHW availability union mask (sampled dates):

```bash
python scripts/build/build_dataset_mask.py --dataset-id crw_dhw_daily --start-date 1985-06-15 --end-date 1985-06-15 --output data/masks/dhw_available_1985_06_15_global_0p05_mask.npz --cache-dir /Volumes/SDCard/Climate/cache/erddap_masks
python scripts/build/build_dataset_mask.py --dataset-id crw_dhw_daily --start-date 2000-06-15 --end-date 2000-06-15 --output data/masks/dhw_available_2000_06_15_global_0p05_mask.npz --cache-dir /Volumes/SDCard/Climate/cache/erddap_masks
python scripts/build/build_dataset_mask.py --dataset-id crw_dhw_daily --start-date 2010-06-15 --end-date 2010-06-15 --output data/masks/dhw_available_2010_06_15_global_0p05_mask.npz --cache-dir /Volumes/SDCard/Climate/cache/erddap_masks
python scripts/build/build_dataset_mask.py --dataset-id crw_dhw_daily --start-date 2020-06-15 --end-date 2020-06-15 --output data/masks/dhw_available_2020_06_15_global_0p05_mask.npz --cache-dir /Volumes/SDCard/Climate/cache/erddap_masks
python scripts/build/build_dataset_mask.py --dataset-id crw_dhw_daily --start-date 2025-06-15 --end-date 2025-06-15 --output data/masks/dhw_available_2025_06_15_global_0p05_mask.npz --cache-dir /Volumes/SDCard/Climate/cache/erddap_masks

python scripts/build/combine_masks.py \
  --mode or \
  --input data/masks/dhw_available_1985_06_15_global_0p05_mask.npz \
  --input data/masks/dhw_available_2000_06_15_global_0p05_mask.npz \
  --input data/masks/dhw_available_2010_06_15_global_0p05_mask.npz \
  --input data/masks/dhw_available_2020_06_15_global_0p05_mask.npz \
  --input data/masks/dhw_available_2025_06_15_global_0p05_mask.npz \
  --output data/masks/dhw_available_global_0p05_mask.npz
```

3. Build water mask and final reef-domain mask with sea-only dilation:

```bash
python scripts/build/build_water_mask.py \
  --grid-id global_0p05 \
  --output-npz data/masks/water_global_0p05_mask.npz

python scripts/build/build_reef_domain_mask.py \
  --reef-mask data/masks/reef_unep_all_touched_global_0p05_mask.npz \
  --reef-mask data/masks/reef_ne_all_touched_global_0p05_mask.npz \
  --water-mask data/masks/water_global_0p05_mask.npz \
  --dhw-mask data/masks/dhw_available_global_0p05_mask.npz \
  --dilate-iterations 1 \
  --output data/masks/crw_dhw_daily_global_0p05_mask.npz
```

Final formula implemented by `build_reef_domain_mask.py`:

```text
reef_seed = UNEP_all_touched OR NE_all_touched
dil = reef_seed OR (dilate(reef_seed) AND water_mask)
mask = dil AND dhw_available_union
```

## Run backend (uvicorn)

Preferred launcher:

```bash
./scripts/api_backend.sh
```

LAN mode:

```bash
./scripts/api_backend.sh --lan
```

With Redis + score-map preload:

```bash
./scripts/api_backend.sh \
  --redis-url redis://localhost:6379/0 \
  --score-map-preload
```

Usage help:

```bash
./scripts/api_backend.sh --help
```

Multi-worker run (without autoreload):

```bash
./scripts/api_backend.sh --no-reload -- --workers 2
```

Direct uvicorn alternative:

```bash
uvicorn climate_api.main:app --reload --reload-dir climate_api --port 8001
```

Local API base URL: `http://localhost:8001`

## Run web app (Next.js)

```bash
cd web
npm install
npm run dev
```

Open: `http://localhost:3000/`

Optional environment overrides:

```bash
export NEXT_PUBLIC_CLIMATE_API_BASE="http://localhost:8001"
export NEXT_PUBLIC_RELEASE="latest"
export NEXT_PUBLIC_MAP_ASSET_BASE="http://localhost:8001"
```

Release override in UI preview mode:

```text
http://localhost:3000/?release=dev
```

## Validation and tests

Registry validation:

```bash
python scripts/validate/all.py
# or for a packaged release:
python scripts/validate/all.py --release dev
```

Python tests:

```bash
PYTHONPATH=. pytest -q
```

API e2e tests (opt-in; require release/location data in `data/releases/<release>` and `data/locations`):

```bash
PYTHONPATH=. RUN_API_E2E=1 API_E2E_RELEASE=dev pytest -q tests/test_api_e2e.py
```

Notes:

- `tests/test_api_e2e.py` is discovered by `pytest`, but skipped by default unless `RUN_API_E2E=1`.
- You can also run all tests including e2e in one pass:

```bash
PYTHONPATH=. RUN_API_E2E=1 API_E2E_RELEASE=dev pytest -q
```

API smoke tests (panel + autocomplete + resolve + nearest + release + latest release):

```bash
python scripts/bench_api_endpoints.py --base-url http://127.0.0.1:8001 --release dev --smoke --smoke-only --n 1 --timeout-s 5
```

Single-command validation suite (registry + tile coverage + pytest + API smoke):

```bash
python scripts/validate_suite.py --base-url http://127.0.0.1:8001 --release dev
```

Validation suite with opt-in API e2e:

```bash
python scripts/validate_suite.py --base-url http://127.0.0.1:8001 --release dev --run-api-e2e
```

Use a different release for e2e inputs:

```bash
python scripts/validate_suite.py --release dev --run-api-e2e --api-e2e-release new
```

Release validation (release registry + release manifest + referenced metrics tile coverage at 100% + smoke):

```bash
python scripts/validate_suite.py \
  --release dev \
  --smoke-only \
  --smoke-n 1
```

## Utility scripts

Benchmarks:

- `scripts/bench_api_endpoints.py`

Operations:

- `scripts/redis_monitor.py`
- `scripts/tile_coverage.py`
