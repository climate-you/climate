#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  sudo scripts/deploy/install_ops.sh

Installs the VM's unattended maintenance jobs from this checkout:
  - climate-disk-heartbeat.timer: reports free disk space on / every 15 min
    (settings in /etc/climate/heartbeat.env, created from the example if
    missing and never overwritten).

Idempotent. bootstrap_vm.sh calls it; on a live VM it can be run on its own
from any checkout or export of the repository, whatever tag is deployed.
USAGE
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi
if [[ $EUID -ne 0 ]]; then
  echo "error: run as root" >&2
  exit 1
fi

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

install -m 0755 "$SRC/scripts/deploy/disk_heartbeat.sh" /usr/local/bin/climate-disk-heartbeat
install -m 0644 "$SRC/deploy/systemd/climate-disk-heartbeat.service" /etc/systemd/system/climate-disk-heartbeat.service
install -m 0644 "$SRC/deploy/systemd/climate-disk-heartbeat.timer" /etc/systemd/system/climate-disk-heartbeat.timer

install -d -o root -g root -m 0755 /etc/climate
if [[ ! -e /etc/climate/heartbeat.env ]]; then
  install -m 0600 "$SRC/deploy/env/heartbeat.env.example" /etc/climate/heartbeat.env
  echo "Created /etc/climate/heartbeat.env: set DISK_HEARTBEAT_URL in it."
fi

systemctl daemon-reload
systemctl enable --now climate-disk-heartbeat.timer
echo "Installed: climate-disk-heartbeat.timer ($(systemctl is-active climate-disk-heartbeat.timer))"
