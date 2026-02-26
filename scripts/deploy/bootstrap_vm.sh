#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/deploy/bootstrap_vm.sh --domain <domain> [options]

Options:
  --domain <domain>       Public DNS name (required).
  --repo-url <url>        Git repository URL (optional fallback when cloning is required).
  --repo-branch <branch>  Git branch/tag to deploy (default: main).
  --app-root <path>       Install root (default: /opt/climate/source).
  --user <name>           Service user (default: climate).
  --help                  Show this help.

Notes:
  - Must run as root on Ubuntu 24.04 LTS.
  - Installs Python, Node.js, Caddy, and system service templates.
USAGE
}

DOMAIN=""
REPO_URL=""
REPO_BRANCH="main"
APP_ROOT="/opt/climate/source"
SERVICE_USER="climate"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
if [[ ! -d "$SCRIPT_REPO_ROOT/.git" ]]; then
  SCRIPT_REPO_ROOT=""
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain)
      DOMAIN="$2"
      shift 2
      ;;
    --repo-url)
      REPO_URL="$2"
      shift 2
      ;;
    --repo-branch)
      REPO_BRANCH="$2"
      shift 2
      ;;
    --app-root)
      APP_ROOT="$2"
      shift 2
      ;;
    --user)
      SERVICE_USER="$2"
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

if [[ -z "$DOMAIN" ]]; then
  echo "error: --domain is required" >&2
  usage
  exit 2
fi

if [[ $EUID -ne 0 ]]; then
  echo "error: run this script as root" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y \
  git \
  curl \
  unzip \
  python3 \
  python3-venv \
  python3-pip \
  build-essential \
  ufw \
  fail2ban \
  unattended-upgrades \
  caddy

if ! command -v node >/dev/null 2>&1; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y nodejs
fi

id -u "$SERVICE_USER" >/dev/null 2>&1 || useradd -m -s /bin/bash "$SERVICE_USER"
mkdir -p /opt/climate /etc/climate

if [[ ! -d "$APP_ROOT/.git" ]]; then
  rm -rf "$APP_ROOT"
  mkdir -p "$(dirname "$APP_ROOT")"
  if [[ -n "$SCRIPT_REPO_ROOT" && "$SCRIPT_REPO_ROOT" != "$APP_ROOT" ]]; then
    cp -a "$SCRIPT_REPO_ROOT" "$APP_ROOT"
  else
    if [[ -z "$REPO_URL" ]]; then
      REPO_URL="$(git config --get remote.origin.url || true)"
    fi
    if [[ -z "$REPO_URL" ]]; then
      echo "error: --repo-url is required when source repo cannot be copied locally" >&2
      exit 2
    fi
    git clone --depth 1 --branch "$REPO_BRANCH" "$REPO_URL" "$APP_ROOT"
  fi
else
  if [[ -n "$SCRIPT_REPO_ROOT" && "$SCRIPT_REPO_ROOT" == "$APP_ROOT" && -z "$REPO_URL" ]]; then
    echo "Using existing checkout at $APP_ROOT without remote fetch."
  else
    git -C "$APP_ROOT" fetch --all --tags
    git -C "$APP_ROOT" checkout "$REPO_BRANCH"
    git -C "$APP_ROOT" pull --ff-only
  fi
fi

python3 -m venv /opt/climate/venv
/opt/climate/venv/bin/pip install --upgrade pip
/opt/climate/venv/bin/pip install -e "$APP_ROOT"

npm --prefix "$APP_ROOT/web" ci
npm --prefix "$APP_ROOT/web" run build

install -d -o root -g root -m 0755 /etc/climate
install -m 0640 "$APP_ROOT/deploy/env/backend.env.example" /etc/climate/backend.env
install -m 0640 "$APP_ROOT/deploy/env/web.env.example" /etc/climate/web.env

URL_SCHEME="https"
if [[ "$DOMAIN" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
  URL_SCHEME="http"
fi
sed -i "s|https://example.com|$URL_SCHEME://$DOMAIN|g" /etc/climate/backend.env /etc/climate/web.env

install -m 0644 "$APP_ROOT/deploy/systemd/climate-backend.service" /etc/systemd/system/climate-backend.service
install -m 0644 "$APP_ROOT/deploy/systemd/climate-web.service" /etc/systemd/system/climate-web.service

install -m 0644 "$APP_ROOT/deploy/proxy/Caddyfile" /etc/caddy/Caddyfile
sed -i "s|example.com|$DOMAIN|g" /etc/caddy/Caddyfile

chown -R "$SERVICE_USER:$SERVICE_USER" /opt/climate
chmod 0640 /etc/climate/backend.env /etc/climate/web.env

ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

systemctl daemon-reload
systemctl enable caddy climate-backend climate-web
systemctl restart caddy climate-backend climate-web

"$APP_ROOT/scripts/deploy/smoke_check.sh" --domain "$DOMAIN" --local

echo "Bootstrap complete."
