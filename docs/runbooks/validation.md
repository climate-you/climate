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
- tile/map assets under `data/releases/<release>/` (v1) or `data/artifacts/` (v2)
- locations assets under `data/locations/` (for API smoke/e2e location calls)

`dev` release behavior:

- registry validation uses repo-root `registry/*.json` (not `data/releases/dev/registry/*.json`)
- `data/releases/dev/manifest.json` is not required
- sparse-risk mask validation for `dev` reads dataset definitions from `registry/datasets.json`

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

For local validation runs, disable API rate limiting first; otherwise benchmark+smoke requests can trigger `429` responses:

```bash
RATE_LIMIT_ENABLED=0 ./scripts/api_backend.sh
```

```bash
python scripts/bench_api_endpoints.py --base-url http://127.0.0.1:8001 --release dev --smoke --smoke-only --n 1 --timeout-s 5
```

## Ranking files validation

Verify that all precomputed ranking JSON files declared in `registry/metrics.json` are present on disk:

```bash
python scripts/validate/rankings.py
```

For a non-`dev` release, pass explicit paths:

```bash
python scripts/validate/rankings.py \
  --series-root data/releases/2026_04_10/series \
  --metrics data/releases/2026_04_10/registry/metrics.json
```

This check is also available as a flag in the one-pass suite:

```bash
python scripts/validate_suite.py --release dev --check-rankings --skip-smoke
```

`publish_release.py` always passes `--check-rankings` in its pre-flight validation, so a missing ranking file will block a production deploy.

## Regional aggregate files validation

Verify that all precomputed regional aggregate JSON files declared in `registry/metrics.json` are present and structurally correct (non-empty regions, time-axis length matches value count):

```bash
python scripts/validate/aggregates.py
```

For a non-`dev` release, pass explicit paths:

```bash
python scripts/validate/aggregates.py \
  --series-root data/releases/2026_04_10/series \
  --metrics data/releases/2026_04_10/registry/metrics.json
```

This check is also available as a flag in the one-pass suite:

```bash
python scripts/validate_suite.py --release dev --check-aggregates --skip-smoke
```

## One-pass validation suite

When running suite smoke checks against a local backend, start the API with rate limiting disabled:

```bash
RATE_LIMIT_ENABLED=0 ./scripts/api_backend.sh
```

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

### Validating a v2 release manifest

For v2 releases (artifact-store), pass `--artifacts-root` so the validator can check that referenced artifact directories and their `manifest.json` files exist:

```bash
python scripts/validate/release_manifest.py \
  --release 2026_04_01 \
  --releases-root data/releases \
  --artifacts-root data/artifacts
```

Or via the validation suite:

```bash
python scripts/validate_suite.py \
  --release 2026_04_01 \
  --artifacts-root data/artifacts \
  --skip-smoke
```
