#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  sudo scripts/deploy/install_ops.sh [--enable-reboot]

Installs the VM's unattended maintenance jobs from this checkout:
  - climate-disk-heartbeat.timer: reports free disk space on / every 15 min
    (settings in /etc/climate/heartbeat.env, created from the example if
    missing and never overwritten). Enabled.
  - climate-weekly-reboot.timer: reboots every Sunday at 00:00 UTC. Installed
    but only enabled with --enable-reboot, so a new VM does not start
    rebooting before its monitors exist; once enabled it stays enabled.
  - unattended-upgrades switched on (/etc/apt/apt.conf.d/20auto-upgrades), so
    the weekly reboot has security updates to apply.
  - the systemd journal capped at 500 MB
    (/etc/systemd/journald.conf.d/climate.conf), so logs cannot fill the disk.

Options:
  --enable-reboot   Enable the weekly reboot timer. Do this only once the
                    external monitors are set up and have alerted at least once
                    (docs/runbooks/deployment.md, "External monitors").
  --help            Show this help.

Idempotent. bootstrap_vm.sh calls it; on a live VM it can be run on its own
from any checkout or export of the repository, whatever tag is deployed.
USAGE
}

ENABLE_REBOOT=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --enable-reboot)
      ENABLE_REBOOT=1
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
  echo "error: run as root" >&2
  exit 1
fi

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

install -m 0755 "$SRC/scripts/deploy/disk_heartbeat.sh" /usr/local/bin/climate-disk-heartbeat
for unit in climate-disk-heartbeat.service climate-disk-heartbeat.timer \
  climate-weekly-reboot.service climate-weekly-reboot.timer; do
  install -m 0644 "$SRC/deploy/systemd/$unit" "/etc/systemd/system/$unit"
done

install -d -o root -g root -m 0755 /etc/climate
if [[ ! -e /etc/climate/heartbeat.env ]]; then
  install -m 0600 "$SRC/deploy/env/heartbeat.env.example" /etc/climate/heartbeat.env
  echo "Created /etc/climate/heartbeat.env: set DISK_HEARTBEAT_URL in it."
fi

# The same two settings `dpkg-reconfigure unattended-upgrades` writes.
cat >/etc/apt/apt.conf.d/20auto-upgrades <<'APT'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT

# journald only reads its config at start, so restart it when the cap changes
# (running services keep their log streams across the restart). The disk
# usage printed at the end shows whether the journal is within the cap.
JOURNALD_CONF=/etc/systemd/journald.conf.d/climate.conf
if ! cmp -s "$SRC/deploy/journald/climate.conf" "$JOURNALD_CONF"; then
  install -d -o root -g root -m 0755 "$(dirname "$JOURNALD_CONF")"
  install -m 0644 "$SRC/deploy/journald/climate.conf" "$JOURNALD_CONF"
  systemctl restart systemd-journald
fi

systemctl daemon-reload
systemctl enable --now climate-disk-heartbeat.timer
if [[ $ENABLE_REBOOT -eq 1 ]]; then
  systemctl enable --now climate-weekly-reboot.timer
fi

for timer in climate-disk-heartbeat.timer climate-weekly-reboot.timer; do
  echo "$timer: $(systemctl is-enabled "$timer" 2>/dev/null || true), $(systemctl is-active "$timer" 2>/dev/null || true)"
done
journalctl --disk-usage
