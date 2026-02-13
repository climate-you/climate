#!/usr/bin/env bash
set -euo pipefail

# Local-network-friendly FastAPI dev server defaults.
# Override with env vars, for example:
#   API_HOST=127.0.0.1 API_PORT=9000 ./scripts/dev_api_lan.sh

API_HOST="${API_HOST:-0.0.0.0}"
API_PORT="${API_PORT:-8001}"

exec uvicorn apps.api.climate_api.main:app \
  --reload \
  --reload-dir apps/api \
  --reload-exclude 'data/*' \
  --reload-exclude 'web/*' \
  --host "${API_HOST}" \
  --port "${API_PORT}" \
  "$@"
