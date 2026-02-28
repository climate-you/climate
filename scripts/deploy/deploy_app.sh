#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/deploy/deploy_app.sh [options]

Options:
  --app-root <path>       Application root (default: /opt/climate/source)
  --ref <git-ref>         Branch/tag/SHA to deploy (default: current branch)
  --tag <tag>             Deploy an exact git tag (recommended for releases)
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
GIT_TAG=""
SKIP_PULL=0
SKIP_BACKEND_INSTALL=0
SKIP_WEB_BUILD=0
SMOKE_INITIAL_WAIT_S="${SMOKE_INITIAL_WAIT_S:-8}"
SMOKE_RETRIES="${SMOKE_RETRIES:-3}"
SMOKE_RETRY_DELAY_S="${SMOKE_RETRY_DELAY_S:-30}"

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
    --tag)
      GIT_TAG="$2"
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

if [[ -n "$GIT_REF" && -n "$GIT_TAG" ]]; then
  echo "error: --ref and --tag are mutually exclusive" >&2
  exit 2
fi

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
  if [[ -n "$GIT_TAG" ]]; then
    if ! git -C "$APP_ROOT" rev-parse -q --verify "refs/tags/$GIT_TAG" >/dev/null; then
      echo "error: unknown tag: $GIT_TAG" >&2
      exit 2
    fi
    git -C "$APP_ROOT" checkout --detach "refs/tags/$GIT_TAG"
  elif [[ -n "$GIT_REF" ]]; then
    git -C "$APP_ROOT" checkout "$GIT_REF"
    git -C "$APP_ROOT" pull --ff-only || true
  else
    git -C "$APP_ROOT" pull --ff-only || true
  fi
fi

if [[ $SKIP_BACKEND_INSTALL -eq 0 ]]; then
  /opt/climate/venv/bin/pip install -e "$APP_ROOT[api]"
fi

if [[ $SKIP_WEB_BUILD -eq 0 ]]; then
  if [[ -f /etc/climate/web.env ]]; then
    # NEXT_PUBLIC_* must be present at build time for Next.js.
    set -a
    # shellcheck disable=SC1091
    source /etc/climate/web.env
    set +a
  fi
  npm --prefix "$APP_ROOT/web" ci --include=dev
  npm --prefix "$APP_ROOT/web" run build
fi

systemctl daemon-reload
systemctl restart climate-backend climate-web

sleep "$SMOKE_INITIAL_WAIT_S"
for attempt in $(seq 1 "$SMOKE_RETRIES"); do
  if "$APP_ROOT/scripts/deploy/smoke_check.sh" --local; then
    echo "Deploy complete."
    exit 0
  fi
  if [[ "$attempt" -lt "$SMOKE_RETRIES" ]]; then
    echo "Smoke check attempt $attempt/$SMOKE_RETRIES failed; retrying in ${SMOKE_RETRY_DELAY_S}s..."
    sleep "$SMOKE_RETRY_DELAY_S"
  fi
done

echo "error: smoke checks failed after $SMOKE_RETRIES attempts" >&2
exit 1
