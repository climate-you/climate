# Runbook: Backend + Frontend (with optional Redis)

This runbook starts the API backend and web application locally.

What you are running:

- FastAPI services for release metadata, panels, location resolution, and map assets
- the Next.js web application that consumes those API endpoints
- optional Redis cache to reduce repeated compute/load latency in hot endpoints

## Runtime Inputs

- release assets under `data/releases/<release>/` (series, maps, registry snapshots)
- location assets under `data/locations/` (resolver index, KD-tree, ocean mask, country mask)
- optional Redis instance for cache acceleration: <https://redis.io/docs/latest/>

## Environment Setup (Recommended)

Conda (Anaconda or Miniconda) is recommended for Python/backend runs.

```bash
conda create -n <your-env-name> python=3.11
conda activate <your-env-name>
export PYTHONPATH="$(pwd)"
```

You can install Python dependencies manually outside Conda, but this is not recommended.

Node.js is required for the frontend:

```bash
cd web
npm install
```

## Start backend

Preferred launcher:

```bash
./scripts/api_backend.sh
```

Useful options:

```bash
./scripts/api_backend.sh --help
./scripts/api_backend.sh --lan
./scripts/api_backend.sh --no-reload -- --workers 2
```

Default backend URL: `http://localhost:8001`

## Start frontend

```bash
cd web
npm run dev
```

Default web URL: `http://localhost:3000`

## Configure web-to-API routing

Optional overrides:

```bash
export NEXT_PUBLIC_CLIMATE_API_BASE="http://localhost:8001"
export NEXT_PUBLIC_RELEASE="latest"
export NEXT_PUBLIC_MAP_ASSET_BASE="http://localhost:8001"
```

Preview a specific release:

```text
http://localhost:3000/?release=dev
```

## Dev-only URL query options

The web app supports development-only query options (disabled in production builds):

- `debug`: enables the debug HUD and panel-bbox overlay
- `texture`: forces texture variant selection for QA (`auto`, `mobile`, `full`)

Examples:

```text
http://localhost:3000/?release=dev&debug=on
http://localhost:3000/?release=dev&debug=on&texture=mobile
http://localhost:3000/?release=dev&debug=on&texture=full
```

Notes:

- In production (`NODE_ENV=production`), `texture` override is ignored and selection stays capability-based.
- Valid values for `debug`: `on`, `1`, `true`.
- Valid values for `texture`: `auto`, `mobile`, `full`.

## Optional Redis cache

If Redis is running locally (example URL: `redis://localhost:6379/0`), launch backend with Redis caching:

```bash
./scripts/api_backend.sh --redis-url redis://localhost:6379/0
```

Equivalent environment variable:

```bash
export REDIS_URL="redis://localhost:6379/0"
./scripts/api_backend.sh
```

## Optional Score-Map Preload

Score-map preload is independent from Redis configuration. Enable it when you want startup-time preloading behavior for score maps.

```bash
./scripts/api_backend.sh --score-map-preload
```

Equivalent environment variable:

```bash
export SCORE_MAP_PRELOAD=1
./scripts/api_backend.sh
```
