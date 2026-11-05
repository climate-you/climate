#!/usr/bin/env bash
# Report free disk space on / to a heartbeat monitor (healthchecks.io or any
# service that takes the same <url> / <url>/fail pings).
#
# Run every 15 minutes by climate-disk-heartbeat.timer. Pings the check's URL
# while / has at least DISK_MIN_FREE_GB free and its /fail URL once it has
# less, so the monitor alerts on low disk. A ping that never arrives alerts
# too, which doubles as "the VM is not running". The ping body carries the
# numbers, so they show in the check's event log.
#
# Settings come from /etc/climate/heartbeat.env (see
# deploy/env/heartbeat.env.example).
set -euo pipefail

DISK_HEARTBEAT_URL="${DISK_HEARTBEAT_URL:-}"
DISK_MIN_FREE_GB="${DISK_MIN_FREE_GB:-5}"

if [[ -z "$DISK_HEARTBEAT_URL" ]]; then
  echo "DISK_HEARTBEAT_URL is not set in /etc/climate/heartbeat.env; nothing to ping." >&2
  exit 0
fi

avail_kb="$(df --output=avail -k / | tail -n 1 | tr -d ' ')"
read -r size avail < <(df -h --output=size,avail / | tail -n 1)
body="${avail} free of ${size} on / (alert below ${DISK_MIN_FREE_GB}G)"

status="ok"
url="$DISK_HEARTBEAT_URL"
if (( avail_kb < DISK_MIN_FREE_GB * 1024 * 1024 )); then
  status="fail"
  url="$DISK_HEARTBEAT_URL/fail"
fi

# The URL is the check's only credential, so it stays out of the log.
curl --fail --silent --show-error --max-time 10 --retry 5 \
  --data-raw "$body" "$url" >/dev/null
echo "$status: $body"
