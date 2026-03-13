# Agent Notes

## Scope

This repository is a registry-driven climate data platform:

- climate data packaging (`scripts/build/packager.py` + `climate/packager/*`)
- shared Python modules for dataset derivation, registries, tiles, and geo utilities (`climate/`)
- FastAPI backend serving packaged metrics and map payloads (`climate_api/`)
- Next.js web application (`web/`)
- operational scripts for validation, benchmarking, and deployment (`scripts/`)

## Python environment

```bash
conda activate climate
export PYTHONPATH="$(pwd)"
```

Install Python dependencies from `pyproject.toml`:

```bash
pip install -e ".[api,packager,validate-all,dev]"
```

For build scripts that need optional geo/mask tools:

```bash
pip install -e ".[geo,make-locations,make-reef-mask]"
```

## Main run commands

Backend:

```bash
./scripts/api_backend.sh --help
./scripts/api_backend.sh                              # basic
./scripts/api_backend.sh --redis --score-map-preload  # production-like
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

- `climate/`: shared package
  - `datasets/`: dataset derivation (ERA5, CMIP6, ERDDAP, DHW), calendar/unit helpers
  - `geo/`: geographic utilities (longitude normalization, marine naming)
  - `packager/`: metric and map packaging pipeline
  - `registry/`: registry loaders (metrics, maps, panels, layers)
  - `tiles/`: tile layout, spec read/write (`.bin`, `.bin.zst`)
- `climate_api/`: FastAPI app and endpoint services
- `registry/*.json`: authoritative metric/map/panel/layer manifests
- `data/`: local artifacts (locations, masks, releases) — not committed
- `deploy/`: service files, env templates, reverse-proxy config for VM deployment
- `docs/`: architecture diagrams and runbooks
- `infra/`: cloud infrastructure (Terraform/GCP)
- `scripts/`: operational scripts
  - `build/`: packager, demo release builder, mask and location builders
  - `validate/`: registry and release validators
  - `deploy/`: bootstrap, deploy, smoke-check scripts
- `tests/`: pytest unit/integration tests
- `web/`: Next.js frontend

## Formatting

Always format touched files before saving:

- **Python**: `black <file>` (or `black <dir>/`)
- **JavaScript / TypeScript / Markdown**: `prettier --write <file>`

## Conventions

- Keep backend imports rooted at `climate_api.*`.
- Keep bench scripts in `scripts/` with a `bench_` prefix.
- If changing API routes/contracts, update `web/src/app/page.tsx` accordingly.
- Unit conversion helpers belong in `climate/datasets/derive/units.py`.
- Longitude normalization helpers belong in `climate/geo/lon.py`.
- Shared tile grid factory: `grid_from_id()` in `climate/tiles/layout.py`.

## Third-party notices

`THIRD_PARTY_NOTICES.md` is machine-generated from NPM `web/package-lock.json` and installed
Python distributions (filtered to `pyproject.toml` dependencies). No dedicated script is checked in;
regenerate with a tool such as `pip-licenses` (Python side) and `jq` on `package-lock.json`
(NPM side), then update the file header timestamp.
