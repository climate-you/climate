#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/deploy/smoke_check.sh [options]

Options:
  --local                Check localhost endpoints (default true)
  --domain <domain>      Check HTTPS endpoint for this domain
  --release <name>       API release id (default: latest)
  --help                 Show this help
USAGE
}

CHECK_LOCAL=1
DOMAIN=""
RELEASE="latest"

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
  curl --fail --silent --show-error "http://127.0.0.1:8001/healthz" >/dev/null
  curl --fail --silent --show-error "http://127.0.0.1:3000" >/dev/null
  curl --fail --silent --show-error "http://127.0.0.1:8001/api/v/${RELEASE}/release" >/dev/null
fi

if [[ -n "$DOMAIN" ]]; then
  curl --fail --silent --show-error "https://${DOMAIN}/healthz" >/dev/null
  curl --fail --silent --show-error "https://${DOMAIN}/api/v/${RELEASE}/release" >/dev/null
fi

echo "Smoke checks passed."
