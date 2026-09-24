#!/usr/bin/env bash
# Overnight refresh for the summer-2026 story.
#
# Order matters: the monthly work is on the uncongested monthly-means dataset
# and finishes in minutes, so it goes first and unblocks the derived metrics.
# The daily backfill is on the derived daily-statistics dataset, which is capped
# at 60 concurrent requests globally, so it goes last and runs into the quiet
# window (roughly 22:00-06:00 UTC) where throughput is much better.
#
# Deliberately NOT using `set -e`: a transient CDS failure in an early step
# should not stop the backfill, which is the long pole. Exit codes are collected
# and reported at the end instead.
#
# Usage:
#   bash scripts/run_refresh_2026.sh            # steps 2-4 then the backfill
#   bash scripts/run_refresh_2026.sh --no-backfill
#
# Consider wrapping in `caffeinate -i` so the machine cannot sleep mid-ingest:
#   caffeinate -i bash scripts/run_refresh_2026.sh

set -o pipefail

ROOT="/Users/benoit.leveau/Documents/Programming/Climate/source"
CACHE="/Volumes/LaCie/Climate/cache"
LOGDIR="$ROOT/logs/refresh-$(date +%Y%m%d-%H%M)"
PKG="conda run --no-capture-output -n climate python -u scripts/build/packager.py"

cd "$ROOT" || exit 1
mkdir -p "$LOGDIR"
export PYTHONPATH="$ROOT"

RUN_BACKFILL=1
[ "${1:-}" = "--no-backfill" ] && RUN_BACKFILL=0

declare -a NAMES=() CODES=()

step () {
  local name="$1"; shift
  local log="$LOGDIR/${name}.log"
  echo
  echo "=============================================================="
  echo ">>> $name   $(date '+%F %T')  (UTC $(date -u '+%H:%M'))"
  echo "    log: $log"
  echo "=============================================================="
  "$@" 2>&1 | tee "$log"
  local rc=${PIPESTATUS[0]}
  NAMES+=("$name"); CODES+=("$rc")
  echo "<<< $name finished rc=$rc  $(date '+%F %T')"
  return $rc
}

# --- step 2: monthly t2m from the official monthly product --------------------
# 1979-2025 comes from cache; only the 2026 block downloads (18 requests).
# Clears the 564/570 tile split left by the smoke test and unblocks
# t2m_june_2026_anomaly, which has been skipping.
step "02-t2m_monthly" $PKG \
  --release dev --metric t2m_monthly_mean_c --cache-dir "$CACHE" \
  --all --start-year 1979 --end-year 2026 --skip-maps

# --- step 3: yearly t2m, now derived from monthly -----------------------------
# Zero downloads. Definitionally identical to the old daily-derived version
# (annual_mean_from_daily already averaged 12 monthly means), but on the
# corrected geometry. Re-verify the continental warming table after this.
step "03-t2m_yearly" $PKG \
  --release dev --metric t2m_yearly_mean_c --cache-dir "$CACHE" \
  --all --start-year 1979 --end-year 2025 --skip-maps

# --- step 4: the swipe pair ---------------------------------------------------
# Zero downloads. Temperature and rainfall anomaly for the same month, same
# projection - the first thing worth actually looking at.
step "04-maps" $PKG \
  --release dev --metric tp_june_2026_anomaly_vs_1991_2020_mm --cache-dir "$CACHE" \
  --all \
  --map tp_june_2026_anomaly_mercator_texture \
  --map t2m_june_2026_anomaly_mercator_texture

# --- step 5: the daily backfill (the long one) --------------------------------
# 2021 and 2022-01/02 are already cached, so this resumes at 2022-03 and has
# ~46 globe-months left. Restores t2m_daily_mean_c from its current 2026-only
# state to the full 2021-2026 axis, and rebuilds the four heatwave metrics at
# the end against the now-clean monthly climatology.
if [ "$RUN_BACKFILL" = "1" ]; then
  step "05-daily_backfill" $PKG \
    --release dev --metric t2m_daily_mean_c --cache-dir "$CACHE" \
    --all --start-year 2021 --end-year 2026 --skip-maps \
    --pipeline --workers 4
fi

# --- summary ------------------------------------------------------------------
echo
echo "=============================================================="
echo "SUMMARY   $(date '+%F %T')"
echo "=============================================================="
fail=0
for i in "${!NAMES[@]}"; do
  rc="${CODES[$i]}"
  [ "$rc" = "0" ] && status="ok" || { status="FAILED (rc=$rc)"; fail=1; }
  printf "  %-22s %s\n" "${NAMES[$i]}" "$status"
done
echo
echo "  logs: $LOGDIR"
echo
echo "  Not run by this script, and still needed for the story:"
echo "    - tp_daily_total_mm for 2026 (8 requests on the congested daily dataset)"
echo "    - tp_summer_2026_pct_of_normal (derives free once the above lands)"
echo "    - precompute_regional_aggregates.py (local; run after the backfill so"
echo "      the daily series is complete rather than 2026-only)"
exit $fail
