#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/api_backend.sh [options] [-- <extra uvicorn args>]

Options:
  --lan                 Bind on 0.0.0.0 and apply LAN-friendly reload excludes.
  --no-reload           Disable autoreload (required for multi-worker mode).
  --redis-url URL       Export REDIS_URL before starting uvicorn.
  --score-map-preload   Export SCORE_MAP_PRELOAD=1 before starting uvicorn.
  --help                Show this help and exit.

Environment overrides:
  API_HOST (default: 127.0.0.1, or 0.0.0.0 with --lan)
  API_PORT (default: 8001)

Examples:
  ./scripts/api_backend.sh
  ./scripts/api_backend.sh --lan
  ./scripts/api_backend.sh --redis-url redis://localhost:6379/0 --score-map-preload
  ./scripts/api_backend.sh --no-reload -- --workers 2
USAGE
}

LAN_MODE=0
RELOAD_MODE=1
REDIS_URL_VALUE=""
SCORE_MAP_PRELOAD_VALUE=""
EXTRA_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --lan)
      LAN_MODE=1
      shift
      ;;
    --no-reload)
      RELOAD_MODE=0
      shift
      ;;
    --redis-url)
      if [[ $# -lt 2 ]]; then
        echo "error: --redis-url requires a value" >&2
        exit 2
      fi
      REDIS_URL_VALUE="$2"
      shift 2
      ;;
    --redis-url=*)
      REDIS_URL_VALUE="${1#*=}"
      shift
      ;;
    --score-map-preload)
      SCORE_MAP_PRELOAD_VALUE="1"
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    --)
      shift
      while [[ $# -gt 0 ]]; do
        EXTRA_ARGS+=("$1")
        shift
      done
      ;;
    *)
      EXTRA_ARGS+=("$1")
      shift
      ;;
  esac
done

if [[ -n "$REDIS_URL_VALUE" ]]; then
  export REDIS_URL="$REDIS_URL_VALUE"
fi
if [[ -n "$SCORE_MAP_PRELOAD_VALUE" ]]; then
  export SCORE_MAP_PRELOAD="$SCORE_MAP_PRELOAD_VALUE"
fi

API_PORT="${API_PORT:-8001}"
if [[ $LAN_MODE -eq 1 ]]; then
  API_HOST="${API_HOST:-0.0.0.0}"
else
  API_HOST="${API_HOST:-127.0.0.1}"
fi

UVICORN_ARGS=(
  climate_api.main:app
  --host "$API_HOST"
  --port "$API_PORT"
)

if [[ $RELOAD_MODE -eq 1 ]]; then
  UVICORN_ARGS+=(--reload --reload-dir climate_api)
  if [[ $LAN_MODE -eq 1 ]]; then
    UVICORN_ARGS+=(--reload-exclude 'data/*' --reload-exclude 'web/*')
  fi
fi

if [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; then
  UVICORN_ARGS+=("${EXTRA_ARGS[@]}")
fi

exec uvicorn "${UVICORN_ARGS[@]}"
