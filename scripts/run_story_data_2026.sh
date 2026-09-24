#!/usr/bin/env bash
# Story-critical data, ordered ahead of the site backfill.
#
# Run AFTER stopping the 05-daily_backfill job. Ordering is the point: the
# daily-statistics queue costs ~40 min per globe-month regardless of when you
# ask, so sequence decides what is blocked, not throughput. tp daily 2026 is
# what the drought half of the story needs; the 2021-2025 backfill only
# restores the site's seasons graph and can trail behind.
#
# Steps:
#   A  fix the southern NaN band in t2m_monthly_mean_c   (~10 min, uncongested)
#   B  tp_daily_total_mm for 2026 + the deficit map      (8 requests, ~6.5 h)
#   C  resume the 2021-2025 daily backfill               (17 requests, ~14 h)
#
# Usage:
#   caffeinate -i bash scripts/run_story_data_2026.sh
#   caffeinate -i bash scripts/run_story_data_2026.sh --no-backfill

set -o pipefail
ROOT="/Users/benoit.leveau/Documents/Programming/Climate/source"
CACHE="/Volumes/LaCie/Climate/cache"
CDS="$CACHE/cds"
BACKUP="$CDS/backup-aug26"
LOGDIR="$ROOT/logs/story-$(date +%Y%m%d-%H%M)"
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
  echo; echo "=============================================================="
  echo ">>> $name   $(date '+%F %T')  (UTC $(date -u '+%H:%M'))"
  echo "    log: $log"
  echo "=============================================================="
  "$@" 2>&1 | tee "$log"
  local rc=${PIPESTATUS[0]}
  NAMES+=("$name"); CODES+=("$rc")
  echo "<<< $name rc=$rc  $(date '+%F %T')"
}

# --- A: southern NaN band in t2m_monthly_mean_c -------------------------------
# The cached 1979-2025 monthly-t2m files for the r008-011 band came back on
# NATIVE latitudes (-38.250..-90.000) while the other bands are on cell centres
# (.125 offsets). t2m_monthly_mean_c is NaN across rows 512-719 for every month
# in that block; the 2026 block, downloaded 2026-08-21, is fine.
#
# Note this is NOT fully understood: t2m_yearly_mean_c reads the same files via
# annual_mean_from_monthly and has no NaN, so the identity/monthly write path
# may be implicated too. The verification at the end of this step says whether
# the re-download actually fixed it.
echo; echo ">>> A0: setting aside the r008-011 monthly-t2m cache"
n=0
for p in "$CDS"/cds_monthly_*2m_temperature_global_0p25_r008-011_*; do
  [ -d "$p" ] || continue
  b=$(basename "$p"); mkdir -p "$BACKUP/$b"
  for f in "$p"/*_1979-2025.nc; do
    [ -e "$f" ] || continue
    mv "$f" "$BACKUP/$b/" && n=$((n+1))
  done
done
echo "    moved $n file(s) to $BACKUP"

step "A-monthly_south" $PKG \
  --release dev --metric t2m_monthly_mean_c --cache-dir "$CACHE" \
  --tile-r0 8 --tile-r1 11 --tile-c0 0 --tile-c1 22 \
  --start-year 1979 --end-year 2026 \
  --map t2m_june_2026_anomaly_mercator_texture

echo; echo ">>> A1: verifying the southern band"
conda run --no-capture-output -n climate python -u - <<'PY' 2>&1 | tee "$LOGDIR/A-verify.log"
import numpy as np, sys
sys.path.insert(0, "/Users/benoit.leveau/Documents/Programming/Climate/source")
from pathlib import Path
from climate.registry.metrics import load_metrics
from climate.packager.maps import _load_metric_axis, reduce_metric_mean_over_indices
from climate.tiles.layout import grid_from_id
mm = load_metrics(); mm = mm.get("metrics", mm) if "metrics" in mm else mm
root = Path("/Users/benoit.leveau/Documents/Programming/Climate/source/data/releases/dev/series")
spec = mm["t2m_monthly_mean_c"]; grid = grid_from_id(str(spec["grid_id"]), tile_size=64)
ax = _load_metric_axis(root, grid, "t2m_monthly_mean_c", "monthly")
ok = True
for month in ("2015-06", "2026-06"):
    idx = [i for i, v in enumerate(ax) if str(v) == month]
    a, _ = reduce_metric_mean_over_indices(series_root=root, metric_id="t2m_monthly_mean_c",
                                           metric_spec=spec, indices=idx)
    bad = int((np.isnan(np.asarray(a, float)).mean(axis=1) > 0.5).sum())
    print(f"   {month}: {bad} NaN rows" + ("  <-- STILL BROKEN" if bad else "  ok"))
    ok = ok and bad == 0
print("   VERDICT: southern band FIXED" if ok else
      "   VERDICT: NOT fixed by re-download -> the monthly identity write path is implicated,"
      "\n            not the cached data. Do not trust the June temperature map.")
PY

# --- B: the last story-critical ingest ----------------------------------------
# 8 globe-months on the congested dataset (~40 min each). Builds
# tp_daily_total_mm, after which tp_summer_2026_pct_of_normal derives for free.
step "B-tp_daily_2026" $PKG \
  --release dev --metric tp_daily_total_mm --cache-dir "$CACHE" \
  --all --start-year 2026 --end-year 2026 \
  --map tp_summer_2026_pct_of_normal_mercator_texture \
  --map tp_june_2026_anomaly_mercator_texture

# --- C: resume the site backfill ----------------------------------------------
# Resumes at 2024-08; 2021 through 2024-07 are already cached.
if [ "$RUN_BACKFILL" = "1" ]; then
  step "C-daily_backfill" $PKG \
    --release dev --metric t2m_daily_mean_c --cache-dir "$CACHE" \
    --all --start-year 2021 --end-year 2026 --skip-maps \
    --pipeline --workers 4
fi

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
echo "  Check A-verify.log first — if the southern band is not fixed, the June"
echo "  temperature map and anything derived from t2m_monthly_mean_c south of"
echo "  -38 are wrong, and that is a code issue rather than a data one."
echo
echo "  Still to do after this:"
echo "    - precompute_regional_aggregates.py (local, once the backfill lands)"
echo "    - July/August anomaly pairs, or a JJA-wide anomaly (needs a 'mean'"
echo "      output mode on window_accumulation_anomaly)"
echo "    - set june_2026_* and summer_2026_* layers back to enable:false"
exit $fail
