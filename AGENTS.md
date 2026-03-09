# Agent Notes

## Scope

This repository is focused on:

- climate data packaging (`scripts/build/packager.py` + `climate/packager/*`)
- API backend (`climate_api/*`)
- web demo (`web/*`)

Legacy streamlit/prototype workflows are intentionally removed.

## Python environment

Use:

```bash
conda activate climate
export PYTHONPATH="$(pwd)"
```

## Main run commands

Backend:

```bash
./scripts/api_backend.sh --help
```

Web:

```bash
cd web
npm install
npm run dev
```

Packager:

```bash
python scripts/build/packager.py --release dev --all --all-maps
```

## Validation

```bash
python scripts/validate/all.py
PYTHONPATH=. pytest -q
cd web && npm run lint && npm run build
```

## File layout

- `climate_api/`: FastAPI app and endpoint services
- `climate/`: shared package code for dataset derivation, registries, tiles, packager
- `registry/*.json`: authoritative metric/map/panel manifests
- `scripts/`: operational scripts (packager, backend launcher, validation, benchmark, monitoring)

## Conventions

- Keep backend imports rooted at `climate_api.*`.
- Keep bench scripts in `scripts/` with a `bench_` prefix.
- If changing API routes/contracts, update `web/src/app/page.tsx` accordingly.
