#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/deploy/enable_beta_auth.sh --user <username> [--password <password>]

Options:
  --user <username>     Basic auth username (required)
  --password <value>    Basic auth password (optional; prompt if omitted)
  --help                Show this help

Notes:
  - Requires root privileges.
  - Writes /etc/caddy/conf.d/10-beta-auth.caddy and reloads Caddy.
USAGE
}

AUTH_USER=""
AUTH_PASSWORD=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --user)
      AUTH_USER="$2"
      shift 2
      ;;
    --password)
      AUTH_PASSWORD="$2"
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

if [[ -z "$AUTH_USER" ]]; then
  echo "error: --user is required" >&2
  usage
  exit 2
fi

if [[ $EUID -ne 0 ]]; then
  echo "error: run as root (sudo)" >&2
  exit 1
fi

if [[ -z "$AUTH_PASSWORD" ]]; then
  read -r -s -p "Beta auth password: " AUTH_PASSWORD
  echo
fi

if [[ -z "$AUTH_PASSWORD" ]]; then
  echo "error: password cannot be empty" >&2
  exit 2
fi

if ! command -v caddy >/dev/null 2>&1; then
  echo "error: caddy is not installed" >&2
  exit 1
fi

AUTH_HASH="$(caddy hash-password --plaintext "$AUTH_PASSWORD")"

install -d -o root -g root -m 0755 /etc/caddy/conf.d
cat > /etc/caddy/conf.d/10-beta-auth.caddy <<CONFIG
# Managed by scripts/deploy/enable_beta_auth.sh
basicauth * {
  ${AUTH_USER} ${AUTH_HASH}
}

# Keep pre-release environments out of search indexes.
header {
  X-Robots-Tag "noindex, nofollow, noarchive"
}
CONFIG

chmod 0640 /etc/caddy/conf.d/10-beta-auth.caddy
chgrp caddy /etc/caddy/conf.d/10-beta-auth.caddy || true
chmod 0644 /etc/caddy/conf.d/10-beta-auth.caddy

caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
systemctl reload caddy

echo "Beta auth enabled and Caddy reloaded."
