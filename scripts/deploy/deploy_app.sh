#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/deploy/deploy_app.sh [options]

Options:
  --app-root <path>       Application root (default: /opt/climate/source)
  --ref <git-ref>         Branch/tag/SHA to deploy (default: current branch)
  --skip-pull             Skip git fetch/pull
  --skip-backend-install  Skip Python dependency install
  --skip-web-build        Skip frontend build
  --help                  Show this help

Notes:
  - Run as root on target VM.
  - Restarts climate-backend and climate-web systemd services.
USAGE
}

APP_ROOT="/opt/climate/source"
GIT_REF=""
SKIP_PULL=0
SKIP_BACKEND_INSTALL=0
SKIP_WEB_BUILD=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --app-root)
      APP_ROOT="$2"
      shift 2
      ;;
    --ref)
      GIT_REF="$2"
      shift 2
      ;;
    --skip-pull)
      SKIP_PULL=1
      shift
      ;;
    --skip-backend-install)
      SKIP_BACKEND_INSTALL=1
      shift
      ;;
    --skip-web-build)
      SKIP_WEB_BUILD=1
      shift
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

if [[ $EUID -ne 0 ]]; then
  echo "error: run this script as root" >&2
  exit 1
fi

if [[ ! -d "$APP_ROOT/.git" ]]; then
  echo "error: app root does not look like a git checkout: $APP_ROOT" >&2
  exit 1
fi

if [[ $SKIP_PULL -eq 0 ]]; then
  git -C "$APP_ROOT" fetch --all --tags
  if [[ -n "$GIT_REF" ]]; then
    git -C "$APP_ROOT" checkout "$GIT_REF"
  fi
  git -C "$APP_ROOT" pull --ff-only || true
fi

if [[ $SKIP_BACKEND_INSTALL -eq 0 ]]; then
  /opt/climate/venv/bin/pip install -e "$APP_ROOT"
fi

if [[ $SKIP_WEB_BUILD -eq 0 ]]; then
  npm --prefix "$APP_ROOT/web" ci
  npm --prefix "$APP_ROOT/web" run build
fi

systemctl daemon-reload
systemctl restart climate-backend climate-web

"$APP_ROOT/scripts/deploy/smoke_check.sh" --local

echo "Deploy complete."
