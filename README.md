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
export NEXT_PUBLIC_MAP_LAYER_ROOT="/data/maps"
```

## Validation and tests

Registry validation:

```bash
python scripts/validate_all.py
```

Python tests:

```bash
PYTHONPATH=. pytest -q
```

## Utility scripts

Benchmarks:

- `scripts/benchmark/bench_api_endpoints.py`
- `scripts/benchmark/bench_place_resolver.py`

Operations:

- `scripts/redis_monitor.py`
- `scripts/tile_coverage.py`
