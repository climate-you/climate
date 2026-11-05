#!/usr/bin/env bash
# v3 Stream B: download every ERA5 input on ERA5's native grid, into
# $CACHE/cds_native (docs/plans/wip/v3-master-plan.md, "Stream B").
#
#   step 1  monthly means, t2m + tp, 1979–2026           4 requests, uncongested
#   step 2  daily t2m mean/max/min + tp, 2021–2026       ~276 globe-months
#   step 3  the same, 1979–2020                          2,016 globe-months
#
# Every request goes through the packager's --download-only --native-download
# path: whole-globe, no area/grid keys, each file kept exactly as CDS returns
# it (longitudes 0..359.75; readers roll them), and a geometry check that
# refuses to keep anything but the 721 x 1440 native grid. Nothing here writes
# to $BACKUP/cds: native files have their own root, and native mode refuses
# --overwrite-download.
#
# Resumable: finished files are reused, so re-running carries on where the
# last run stopped. Ctrl-C once lets the request in flight finish (a CDS
# payload that arrived but was not yet checked is checked on the next run).
# Only transport and server errors are retried, with a growing pause. A
# request CDS rejected or failed, an account problem, or a geometry rejection
# stops the run at once: ECMWF's protection measures (Oct 2026) warn that
# "repeated submission of invalid requests may result in your account being
# disabled", so those need a human, not a retry.
#
# Requests go strictly one after another: CDS runs one job per user at a time,
# and the same notice asks for sequential submission.
#
# Storage: downloads go to the SD card ($CACHE), so the laptop can move while
# the run lasts weeks. The whole native set (~150 GB) fits on it. `backup`
# copies finished files to the LaCie drive ($BACKUP) whenever it is plugged
# in; it never overwrites or deletes anything there, and the run keeps reading
# the SD card, so nothing is fetched twice.
#
# Usage:
#   caffeinate -i bash scripts/run_v3_native_downloads.sh          # steps 1 2 3
#   caffeinate -i bash scripts/run_v3_native_downloads.sh 2 3      # chosen steps
#   bash scripts/run_v3_native_downloads.sh status                 # progress
#   bash scripts/run_v3_native_downloads.sh backup                 # copy to LaCie
#
# END_MONTH is the last complete 2026 month to fetch (default 9). Raise it as
# CDS publishes new months (Stream B step 4) and re-run steps 1 and 2.

set -o pipefail
ROOT="/Users/benoit.leveau/Documents/Programming/Climate/source"
CACHE="${CACHE:-/Volumes/SDCard/Climate/cache}"
BACKUP="${BACKUP:-/Volumes/LaCie/Climate/cache}"
NATIVE="$CACHE/cds_native"
LOGDIR="${LOGDIR:-$ROOT/logs/v3-native}"
END_MONTH="${END_MONTH:-9}"
MIN_FREE_GB="${MIN_FREE_GB:-30}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-4}"
RETRY_PAUSE_S="${RETRY_PAUSE_S:-900}"  # x attempt number
PKG="${PKG:-conda run --no-capture-output -n climate python -u scripts/build/packager.py}"

# name  metric  start-year  end-year
STEP1=(
  "monthly_t2m      t2m_monthly_mean_c          1979 2026"
  "monthly_tp       tp_monthly_mean_mm_per_day  1979 2026"
)
STEP2=(
  "daily_t2m_mean   t2m_daily_mean_c            2021 2026"
  "daily_t2m_max    t2m_monthly_max_c           2021 2026"
  "daily_t2m_min    t2m_monthly_min_c           2021 2026"
  "daily_tp         tp_daily_total_mm           2021 2026"
)
STEP3=(
  "daily_t2m_mean   t2m_daily_mean_c            1979 2020"
  "daily_t2m_max    t2m_monthly_max_c           1979 2020"
  "daily_t2m_min    t2m_monthly_min_c           1979 2020"
  "daily_tp         tp_daily_total_mm           1979 2020"
)

cd "$ROOT" || exit 1
export PYTHONPATH="$ROOT"

status () {
  echo "native cache: $NATIVE   (END_MONTH=$END_MONTH)"
  if [ ! -d "$NATIVE" ]; then echo "  (not created yet)"; return 0; fi
  printf "  %-78s %6s %6s\n" "directory (files by start year)" "79-20" "21-26"
  for d in "$NATIVE"/*/; do
    [ -d "$d" ] || continue
    # file names end _<y0>-<y1>[_mMM-MM][_dDD-DD].nc
    ls "$d" | sed -nE 's/.*_([0-9]{4})-[0-9]{4}(_m[0-9-]+)?(_d[0-9-]+)?\.nc$/\1/p' \
      | awk -v name="$(basename "$d")" '
          { if ($1 <= 2020) old += 1; else new += 1 }
          END { printf "  %-78s %6d %6d\n", name, old, new }'
  done
  echo "  expected per daily product: 504 for 1979-2020, $((5 * 12 + END_MONTH)) for 2021-2026"
  echo "  expected per monthly product: 2 files (1979-2025, 2026 m01-$(printf %02d "$END_MONTH"))"
  local stray
  stray=$(find "$NATIVE" -name '*.cds' -o -name '*.tmp' -o -name '*.request.json' | wc -l | tr -d ' ')
  echo "  payloads / temp files / failed-request dumps: $stray"
  echo
  echo "request times (queue + transfer), last 20 daily:"
  grep -h "Downloaded: .*era5_daily_.*request took" "$LOGDIR"/run-*.log 2>/dev/null \
    | sed -E 's/^([0-9-]+ [0-9:]+) .*Downloaded: .*\/([^/]+)\.nc \(request took ([0-9]+) s\)/\1  \3 s  \2/' \
    | tail -n 20 \
    | awk '{print "  " $0; s += $3; n += 1} END {if (n) printf "  mean %.0f s (%.1f min) over %d request(s)\n", s/n, s/n/60, n}'
  return 0
}

# True when the volume holding $1 (/Volumes/<name>/...) is mounted. Checked
# before any mkdir: on an unmounted card, mkdir -p would quietly create the
# directory on the internal disk instead.
mounted () {
  local vol
  vol=$(echo "$1" | cut -d/ -f1-3)
  [ "$(df "$vol" 2>/dev/null | awk 'NR == 2 { print $NF }')" = "$vol" ]
}

backup () {
  local dst="$BACKUP/cds_native"
  if ! mounted "$BACKUP" || [ ! -d "$BACKUP" ]; then
    echo "ERROR: $BACKUP not found — is the LaCie drive mounted?" >&2
    return 1
  fi
  [ -d "$NATIVE" ] || { echo "nothing to copy: $NATIVE does not exist"; return 0; }
  # Finished .nc files only: payloads (.cds) and temp files are skipped, and
  # a .nc only exists once it has been fully written and checked.
  local d n=0 f
  for d in "$NATIVE"/*/; do
    [ -d "$d" ] || continue
    mkdir -p "$dst/$(basename "$d")" || return 1
    for f in "$d"*.nc; do
      [ -e "$f" ] || continue
      [ -e "$dst/$(basename "$d")/$(basename "$f")" ] && continue
      cp -p "$f" "$dst/$(basename "$d")/.$(basename "$f").part" \
        && mv "$dst/$(basename "$d")/.$(basename "$f").part" "$dst/$(basename "$d")/$(basename "$f")" \
        || { echo "ERROR: copying $f failed" >&2; return 1; }
      n=$((n + 1))
    done
  done
  echo "copied $n new file(s) to $dst ($(du -sh "$dst" | cut -f1) there now)"
}

case "${1:-}" in
  status) status; exit 0 ;;
  backup) backup; exit $? ;;
esac

if ! mounted "$CACHE"; then
  echo "ERROR: the volume for $CACHE is not mounted — is the SD card in?" >&2
  exit 1
fi
mkdir -p "$NATIVE" || exit 1

mkdir -p "$LOGDIR"
LOCK="$LOGDIR/.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  pid=$(cat "$LOCK/pid" 2>/dev/null)
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    echo "ERROR: another run is active (pid $pid). CDS runs one job per user." >&2
    exit 1
  fi
  echo "Removing stale lock from pid ${pid:-?}"
  rm -rf "$LOCK" && mkdir "$LOCK" || exit 1
fi
echo $$ > "$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT

LOG="$LOGDIR/run-$(date +%Y%m%d-%H%M%S).log"
STOP=0
trap 'STOP=1; echo "Interrupt: stopping after the request in flight."' INT

# Ctrl-C reaches the whole pipeline. The packager handles it by finishing the
# request in flight, so the logging side must survive it: if perl or tee died,
# the packager's next print would hit a broken pipe and abort that request.
stamp () { perl -MPOSIX -pe 'BEGIN { $| = 1; $SIG{INT} = "IGNORE" } print strftime("%Y-%m-%d %H:%M:%S ", localtime)'; }
say () { echo "$*" | stamp | tee -i -a "$LOG"; }

free_gb () { df -k "$CACHE" | awk 'NR == 2 { printf "%d", $4 / 1048576 }'; }

run_job () {
  local name="$1" metric="$2" y0="$3" y1="$4"
  local args=(--release dev --metric "$metric" --start-year "$y0" --end-year "$y1"
              --all --skip-maps --download-only --native-download
              --cache-dir "$CACHE")
  [ "$y1" = "2026" ] && args+=(--end-month "$END_MONTH")
  local attempt=1 rc start
  while :; do
    if [ "$(free_gb)" -lt "$MIN_FREE_GB" ]; then
      say "STOP: only $(free_gb) GB free on $CACHE (minimum $MIN_FREE_GB)."
      return 2
    fi
    say ">>> $name $y0-$y1 ($metric) attempt $attempt/$MAX_ATTEMPTS, $(free_gb) GB free"
    start=$(wc -l < "$LOG")
    $PKG "${args[@]}" 2>&1 | stamp | tee -i -a "$LOG"
    rc=${PIPESTATUS[0]}
    if [ "$rc" = "0" ]; then
      say "<<< $name $y0-$y1 done"
      return 0
    fi
    if tail -n +"$((start + 1))" "$LOG" | grep -q -e "non-native grid" -e "is not native"; then
      say "STOP: $name returned a non-native grid. Nothing was written; inspect the payload."
      return 3
    fi
    # Anything that means CDS saw the request and refused or failed it.
    if tail -n +"$((start + 1))" "$LOG" | grep -q -i -E \
        "updated to failed|client error|bad request|not valid|invalid|unauthori[sz]ed|forbidden|suspend|disabled|licen[cs]e"; then
      say "STOP: CDS rejected or failed a $name request (see the log above). Not retrying an invalid request."
      return 4
    fi
    [ "$STOP" = "1" ] && return 130
    if [ "$attempt" -ge "$MAX_ATTEMPTS" ]; then
      say "STOP: $name failed $attempt times (rc=$rc)."
      return 1
    fi
    say "<<< $name rc=$rc; retrying in $((RETRY_PAUSE_S * attempt)) s"
    sleep "$((RETRY_PAUSE_S * attempt))" || return 130
    [ "$STOP" = "1" ] && return 130
    attempt=$((attempt + 1))
  done
}

steps=("$@")
[ ${#steps[@]} -eq 0 ] && steps=(1 2 3)
say "run log: $LOG   steps: ${steps[*]}   END_MONTH=$END_MONTH"

for step in "${steps[@]}"; do
  case "$step" in
    1) jobs=("${STEP1[@]}") ;;
    2) jobs=("${STEP2[@]}") ;;
    3) jobs=("${STEP3[@]}") ;;
    *) say "unknown step: $step"; exit 1 ;;
  esac
  say "=== step $step ==="
  for job in "${jobs[@]}"; do
    # shellcheck disable=SC2086
    run_job $job || { rc=$?; say "run stopped (rc=$rc)"; status | tee -a "$LOG"; exit "$rc"; }
    [ "$STOP" = "1" ] && { say "run stopped by interrupt"; status | tee -a "$LOG"; exit 130; }
  done
done

say "all requested steps complete"
status | tee -a "$LOG"
