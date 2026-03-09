#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/deploy/smoke_check.sh [options]

Options:
  --local                Check localhost endpoints (default true)
  --domain <domain>      Check public endpoint for this domain/IP
  --release <name>       API release id (default: latest)
  --help                 Show this help
USAGE
}

CHECK_LOCAL=1
DOMAIN=""
RELEASE="latest"
API_PORT="${API_PORT:-8001}"
WEB_PORT="${WEB_PORT:-3000}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --local)
      CHECK_LOCAL=1
      shift
      ;;
    --domain)
      DOMAIN="$2"
      shift 2
      ;;
    --release)
      RELEASE="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ $CHECK_LOCAL -eq 1 ]]; then
  curl --fail --silent --show-error "http://127.0.0.1:${API_PORT}/healthz" >/dev/null
  curl --fail --silent --show-error "http://127.0.0.1:${WEB_PORT}" >/dev/null
  curl --fail --silent --show-error "http://127.0.0.1:${API_PORT}/api/v/${RELEASE}/release" >/dev/null
fi

if [[ -n "$DOMAIN" ]]; then
  DOMAIN_SCHEME="https"
  if [[ "$DOMAIN" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
    DOMAIN_SCHEME="http"
  fi
  curl --fail --silent --show-error "${DOMAIN_SCHEME}://${DOMAIN}/" >/dev/null
  curl --fail --silent --show-error "${DOMAIN_SCHEME}://${DOMAIN}/api/v/${RELEASE}/release" >/dev/null
fi

echo "Smoke checks passed."
