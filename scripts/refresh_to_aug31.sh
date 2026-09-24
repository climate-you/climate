#!/usr/bin/env bash
# Complete August: extend the daily metrics to the 31st and bring the monthly
# metrics forward to include August, now that it is a finished month.
#
# Registry was bumped before this script was written:
#   - the four daily datasets and the three daily metrics to end_day 31
#   - era5_monthly_t2m / era5_monthly_tp and their metrics to end_month 8
#   - t2m_monthly_max_c / min_c deliberately LEFT at July: era5_daily_t2m_min
#     has no 2026 download at all, so extending them would trigger a fresh
#     min/max ingest this story does not need.
#
# Requests: 3 on the congested daily-statistics dataset (~40 min each) plus 36
# on the uncongested monthly-means dataset (~2 min each) — the 2026 monthly
# block is keyed by its month range, so m01-07 files no longer match and each
# tile batch refetches as m01-08.
#
# Usage: caffeinate -i bash scripts/refresh_to_aug31.sh

set -o pipefail
ROOT="/Users/benoit.leveau/Documents/Programming/Climate/source"
CACHE="/Volumes/LaCie/Climate/cache"
LOGDIR="$ROOT/logs/aug31-$(date +%Y%m%d-%H%M)"
PKG="conda run --no-capture-output -n climate python -u scripts/build/packager.py"

cd "$ROOT" || exit 1
mkdir -p "$LOGDIR"
export PYTHONPATH="$ROOT"

if [ ! -d "$CACHE/cds" ]; then
  echo "ERROR: $CACHE/cds not found — is the LaCie drive mounted?" >&2
  exit 1
fi

declare -a NAMES=() CODES=()
step () {
  local name="$1"; shift
  echo; echo "=============================================================="
  echo ">>> $name   $(date '+%F %T')  (UTC $(date -u '+%H:%M'))"
  echo "=============================================================="
  "$@" 2>&1 | tee "$LOGDIR/${name}.log"
  local rc=${PIPESTATUS[0]}
  NAMES+=("$name"); CODES+=("$rc")
  echo "<<< $name rc=$rc"
}

# --- monthly first: uncongested, and the derived metrics depend on it ---------
step "1-monthly_t2m" $PKG \
  --release dev --metric t2m_monthly_mean_c --cache-dir "$CACHE" \
  --all --start-year 1979 --end-year 2026 --skip-maps

step "2-monthly_tp" $PKG \
  --release dev --metric tp_monthly_mean_mm_per_day --cache-dir "$CACHE" \
  --all --start-year 1979 --end-year 2026 --skip-maps

# --- the three daily metrics: one August globe-month each ---------------------
step "3-t2m_daily_max" $PKG \
  --release dev --metric t2m_daily_max_c --cache-dir "$CACHE" \
  --all --start-year 2021 --end-year 2026 --skip-maps --pipeline --workers 4

step "4-t2m_daily_mean" $PKG \
  --release dev --metric t2m_daily_mean_c --cache-dir "$CACHE" \
  --all --start-year 2021 --end-year 2026 --skip-maps --pipeline --workers 4

# tp last: this also rebuilds tp_summer_2026_pct_of_normal and every heat-window
# anomaly, and re-renders their maps.
step "5-tp_daily" $PKG \
  --release dev --metric tp_daily_total_mm --cache-dir "$CACHE" \
  --all --start-year 2026 --end-year 2026 \
  --map tp_summer_2026_pct_of_normal_mercator_texture \
  --map t2m_heatwave_2026_w5_mercator_texture \
  --map tp_june_2026_anomaly_mercator_texture \
  --map t2m_june_2026_anomaly_mercator_texture

# --- aggregates, scoped to the clean metrics ---------------------------------
# A bare re-run would walk tp_annual_total_mm, t2m_hotdays_per_year and
# tp_cdd_per_year, which the Stream 2 audit found corrupt.
step "6-aggregates" conda run --no-capture-output -n climate python -u \
  scripts/precompute_regional_aggregates.py --release dev \
  --metrics t2m_daily_mean_c t2m_daily_max_c tp_daily_total_mm \
            t2m_monthly_mean_c tp_monthly_mean_mm_per_day

# --- rebuild the analysis series ---------------------------------------------
echo; echo ">>> 7-analysis  $(date '+%F %T')"
rm -f "$ROOT"/logs/analysis/daily_max_*.csv
step "7a-episodes_global" conda run --no-capture-output -n climate python -u \
  experiments/heatwave_analysis.py --set global \
  --json-out "$LOGDIR/episodes_global.json"
step "7b-seasonal_cycle" conda run --no-capture-output -n climate python -u \
  experiments/heatwave_analysis.py --set europe --months 3 4 5 6 7 8 --csv-only

echo; echo "=============================================================="
echo "SUMMARY   $(date '+%F %T')"
echo "=============================================================="
fail=0
for i in "${!NAMES[@]}"; do
  rc="${CODES[$i]}"
  [ "$rc" = "0" ] && s="ok" || { s="FAILED (rc=$rc)"; fail=1; }
  printf "  %-22s %s\n" "${NAMES[$i]}" "$s"
done
echo
echo "  logs: $LOGDIR"
echo
echo "  Then, by hand:"
echo "    - the wet window in experiments/build_story_draft.py is 16-28 Aug;"
echo "      move WET1 to 2026-08-31 so the pivot covers the whole fortnight"
echo "    - with August complete, the historical comparison can move from"
echo "      June-July to a full JJA. Worth checking whether 2026 is still the"
echo "      hottest AND driest on record once late-August rain is included —"
echo "      it may not be, and that changes the story's strongest claim"
echo "    - regenerate the draft: python experiments/build_story_draft.py"
exit $fail
