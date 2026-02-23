# Runbook: Validation and Tests

Use this runbook to validate registries, data artifacts, and runtime endpoints.

What this runbook verifies:

- registry and release-manifest integrity
- tile/materialization coverage constraints
- Python test suite behavior
- API endpoint availability and smoke behavior against a target release

## Validation Inputs

- registry files (`registry/*.json` or `data/releases/<release>/registry/*.json`)
- release manifest (`data/releases/<release>/manifest.json`)
- tile/map assets under `data/releases/<release>/`
- locations assets under `data/locations/` (for API smoke/e2e location calls)

## Environment Setup (Recommended)

Conda (Anaconda or Miniconda) is recommended for reproducible local runs.

```bash
conda create -n <your-env-name> python=3.11
conda activate <your-env-name>
export PYTHONPATH="$(pwd)"
```

You can install Python dependencies manually outside Conda, but this is not recommended.

## Registry validation

```bash
python scripts/validate/all.py
python scripts/validate/all.py --release dev --releases-root data/releases
```

## Python tests

```bash
PYTHONPATH=. pytest -q
```

## `climate_api` coverage only

Use this when you want a backend-only coverage signal (without `climate/` in the report):

```bash
PYTHONPATH=. pytest -q --override-ini addopts="--cov=climate_api --cov-report=term-missing"
```

Include opt-in API e2e coverage in the same report:

```bash
PYTHONPATH=. RUN_API_E2E=1 API_E2E_RELEASE=dev pytest -q --override-ini addopts="--cov=climate_api --cov-report=term-missing"
```

## Opt-in API e2e tests

Requires release/location data in `data/releases/<release>` and `data/locations`.

```bash
PYTHONPATH=. RUN_API_E2E=1 API_E2E_RELEASE=dev pytest -q tests/test_api_e2e.py
```

## API smoke checks

```bash
python scripts/bench_api_endpoints.py --base-url http://127.0.0.1:8001 --release dev --smoke --smoke-only --n 1 --timeout-s 5
```

## One-pass validation suite

```bash
python scripts/validate_suite.py --base-url http://127.0.0.1:8001 --release dev
```

With opt-in API e2e:

```bash
python scripts/validate_suite.py --base-url http://127.0.0.1:8001 --release dev --run-api-e2e
```

Release-focused checks:

```bash
python scripts/validate_suite.py --release dev --smoke-only --smoke-n 1
```
