#!/usr/bin/env python3
"""Time how long CDS keeps a request queued, by dataset and request size.

FINDING (measured 2026-08-21): queue time is governed by WHICH DATASET you ask
for, not by how big the request is. A 5-year monthly-means request (60 fields,
81 MB) completed in 55 s while a single-month daily-statistics request (31
fields, 77 MB) took 992 s and 1106 s on either side of it — larger request,
18x faster. Both monthly requests queued for an identical 33 s.

The cause is visible in the CDS queue status: "Requests for ERA5 daily
statistics datasets is limited to 60 concurrent requests. Running: 60 —
Queued: 2422." That cap is global across all users and specific to the derived
daily-statistics dataset. reanalysis-era5-single-levels-monthly-means is a
separate, uncongested dataset.

So tuning request size to stay in a "fast lane" does not work — there is no
fast lane within a congested dataset. What this script is now for is measuring
a dataset before committing an ingest to it. In particular `hourly_1day` /
`hourly_1month` test whether hourly ERA5 (a third dataset) escapes the
daily-statistics cap; daily mean and daily max are both exactly reproducible
from hourly, so it is a viable if bulky alternative at ~24x the transfer.

RUN THIS WITH NO OTHER CDS JOB IN FLIGHT. CDS appears to run only one job per
user at a time, so if an ingest is running every test request simply queues
behind it and the measurement reflects the ingest's remaining work rather than
the test request's size — all cases then look identically slow and the result
means nothing. Stop the ingest first; it resumes from cache with nothing lost.

Cases run strictly one at a time (wait_until_complete), never concurrently, so
no case can be advantaged by being submitted first. To catch drift in CDS load
across the run, the daily control is repeated at the end: if the two control
timings differ a lot, background load moved and the middle results should be
treated as indicative only.

Usage:
    python experiments/check_cds_job_size.py                # control, 1yr, 5yr, control
    python experiments/check_cds_job_size.py --big          # ... also 47 years
    python experiments/check_cds_job_size.py --only monthly_1y
    python experiments/check_cds_job_size.py --compare     # daily vs hourly, off-peak
"""
from __future__ import annotations

import argparse
import tempfile
import time
from pathlib import Path

DAILY = "derived-era5-single-levels-daily-statistics"
MONTHLY = "reanalysis-era5-single-levels-monthly-means"
HOURLY = "reanalysis-era5-single-levels"

# Whole-globe, cell-centre aligned — exactly what the packager sends.
AREA = [89.875, -179.875, -89.875, 179.875]
GRID = [0.25, 0.25]
ALL_MONTHS = [f"{m:02d}" for m in range(1, 13)]


def _monthly(years: list[int]) -> tuple[str, dict, int]:
    return (
        MONTHLY,
        {
            "product_type": "monthly_averaged_reanalysis",
            "variable": ["total_precipitation"],
            "year": [str(y) for y in years],
            "month": ALL_MONTHS,
            "time": ["00:00"],
            "data_format": "netcdf",
            "area": AREA,
            "grid": GRID,
        },
        len(years) * 12,
    )


def _daily_control() -> tuple[str, dict, int]:
    return (
        DAILY,
        {
            "product_type": "reanalysis",
            "variable": ["2m_temperature"],
            "year": "2019",
            "month": "03",
            "day": [f"{d:02d}" for d in range(1, 32)],
            "daily_statistic": "daily_mean",
            "time_zone": "utc+00:00",
            "frequency": "1_hourly",
            "area": AREA,
            "grid": GRID,
        },
        31,
    )


def _hourly(days: list[str]) -> tuple[str, dict, int]:
    """Hourly ERA5 is a DIFFERENT dataset, so it may not share the daily-statistics
    concurrency cap. Daily mean/max are exactly reproducible from it, so this is a
    possible escape route from that queue — at ~24x the transfer."""
    return (
        HOURLY,
        {
            "product_type": "reanalysis",
            "variable": ["2m_temperature"],
            "year": "2019",
            "month": "03",
            "day": days,
            "time": [f"{h:02d}:00" for h in range(24)],
            "data_format": "netcdf",
            "area": AREA,
            "grid": GRID,
        },
        len(days) * 24,
    )


CASES: dict[str, tuple] = {
    "daily_control_1month": _daily_control(),
    "hourly_1day": _hourly(["15"]),
    "hourly_1month": _hourly([f"{d:02d}" for d in range(1, 32)]),
    "monthly_1y": _monthly([2019]),
    "monthly_5y": _monthly(list(range(2015, 2020))),
    "monthly_47y": _monthly(list(range(1979, 2026))),
}
DEFAULT_ORDER = ["daily_control_1month", "monthly_1y", "monthly_5y"]


# Measured 2026-08-21 at 08:00-13:00 UTC (European office hours, US coming
# online) — the congested end of the diurnal cycle. Tonight's run compares
# against these.
PEAK_BASELINE = {
    "daily_control_1month": 1049.0,  # mean of 992s and 1106s
    "hourly_1month": 308.0,
    "hourly_1day": 55.0,
    "monthly_1y": 78.0,
    "monthly_5y": 55.0,
}


def run_case(name: str) -> dict | None:
    import cdsapi

    dataset, request, nfields = CASES[name]
    marks: list[tuple[float, str]] = []

    def on_info(msg: str) -> None:
        marks.append((time.time(), str(msg)))

    # sleep_max matches climate/datasets/sources/cds.py so this measures what an
    # actual ingest would experience, not cdsapi's 120s default polling backoff.
    client = cdsapi.Client(
        quiet=True, wait_until_complete=True, sleep_max=20,
        info_callback=on_info, warning_callback=on_info, error_callback=on_info,
    )
    utc = time.strftime("%H:%M UTC", time.gmtime())
    print(f"\n### {name}  ({nfields} fields, whole globe)  submitted {utc}")
    t0 = time.time()
    size_mb = None
    try:
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "out.nc"
            client.retrieve(dataset, request, str(target))
            if target.exists():
                size_mb = target.stat().st_size / 1048576
    except Exception as exc:  # noqa: BLE001 — rejection is a valid outcome
        print(f"   REJECTED/FAILED after {time.time() - t0:.0f}s: "
              f"{type(exc).__name__}: {str(exc).splitlines()[0][:120]}")
        return None

    def first_at(substr: str) -> float | None:
        for t, m in marks:
            if substr in m.lower():
                return t
        return None

    t_acc = first_at("accepted")
    t_run = first_at("running")
    t_end = time.time()
    total = t_end - t0
    queued = (t_run - (t_acc or t0)) if t_run else None
    running = (t_end - t_run) if t_run else None
    print(f"   total       {total:7.0f}s"
          + (f"   ({size_mb:.0f} MB)" if size_mb else ""))
    if queued is not None:
        print(f"   queued      {queued:7.0f}s   (accepted -> running)")
        print(f"   generating  {running:7.0f}s   (running -> downloaded)")
    else:
        print("   (no 'running' transition seen; status messages below)")
        for t, m in marks[:8]:
            print(f"     +{t - t0:5.0f}s  {m[:90]}")
    base = PEAK_BASELINE.get(name)
    if base:
        print(f"   vs peak     {base:7.0f}s   -> {base / total:.1f}x "
              f"{'faster' if total < base else 'slower'} than the daytime run")
    return {"name": name, "total": total, "mb": size_mb, "utc": utc,
            "fields": nfields, "queued": queued}


def _warn_if_ingest_running() -> None:
    """A concurrent ingest invalidates the measurement — say so loudly."""
    import subprocess

    try:
        out = subprocess.run(
            ["pgrep", "-fl", "packager.py"], capture_output=True, text=True
        ).stdout.strip()
    except Exception:  # noqa: BLE001 — best-effort check only
        return
    if out:
        print("!" * 74)
        print("WARNING: a packager process appears to be running:")
        for line in out.splitlines()[:3]:
            print(f"  {line[:100]}")
        print("CDS runs one job per user at a time, so every request below will")
        print("queue behind it and the timings will measure that job, not size.")
        print("Stop the ingest and re-run, or the result is meaningless.")
        print("!" * 74)
        try:
            input("Press Enter to continue anyway, or Ctrl-C to abort... ")
        except (EOFError, KeyboardInterrupt):
            raise SystemExit(1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--big", action="store_true",
                    help="also submit the 47-year request (may queue a long time)")
    ap.add_argument("--only", choices=sorted(CASES),
                    help="run a single case")
    ap.add_argument("--compare", action="store_true",
                    help="daily-stats vs hourly for the same globe-month, "
                         "bracketed by a repeat of the daily case (3 requests, "
                         "~1.2 GB) — the run to do in the quiet window")
    ap.add_argument("--no-check", action="store_true",
                    help="skip the concurrent-ingest check")
    args = ap.parse_args()

    if not args.no_check:
        _warn_if_ingest_running()

    if args.only:
        order = [args.only]
    elif args.compare:
        # Daily-stats vs hourly for the same globe-month, bracketed by a repeat
        # of the daily case so any drift during the run is visible.
        order = ["daily_control_1month", "hourly_1month", "daily_control_1month"]
    else:
        # Bracket with the control so drift in background CDS load is visible.
        order = list(DEFAULT_ORDER)
        if args.big:
            order.append("monthly_47y")
        order.append("daily_control_1month")

    print("Timing CDS queue behaviour by dataset (one job at a time).")
    print("Queue time tracks the DATASET, not request size: derived daily "
          "statistics is capped at 60 concurrent requests globally, while "
          "monthly-means and hourly are not.")
    print("Congestion is also diurnal (quiet roughly 22:00-06:00 UTC), so "
          "results are only comparable to runs made at a similar hour.")
    results = [r for r in (run_case(n) for n in order) if r]

    if len(results) > 1:
        print("\n" + "=" * 72)
        print(f"{'case':22s} {'submitted':11s} {'total':>8s} {'MB':>7s} {'vs peak':>9s}")
        for r in results:
            base = PEAK_BASELINE.get(r["name"])
            rel = f"{base / r['total']:.1f}x" if base else "-"
            mb = f"{r['mb']:.0f}" if r["mb"] else "-"
            print(f"{r['name']:22s} {r['utc']:11s} {r['total']:7.0f}s {mb:>7s} {rel:>9s}")

        daily = [r["total"] for r in results if r["name"] == "daily_control_1month"]
        hourly = [r["total"] for r in results if r["name"] == "hourly_1month"]
        if len(daily) >= 2:
            spread = max(daily) / min(daily)
            print(f"\ncontrol spread {spread:.2f}x — "
                  + ("stable, results comparable" if spread < 1.5
                     else "LOAD MOVED mid-run, treat as indicative only"))
        if daily and hourly:
            d, h = sum(daily) / len(daily), hourly[0]
            print(f"\ndaily-stats {d:.0f}s vs hourly {h:.0f}s for the same globe-month "
                  f"({h / 60:.0f} min, ~1 GB).")
            if d <= h:
                print("VERDICT: daily-statistics is no slower off-peak. Do NOT build the")
                print("hourly route — schedule daily ingests for the quiet window instead.")
            else:
                n = 504
                print(f"VERDICT: hourly is {d / h:.1f}x faster even off-peak. For the v3 "
                      f"re-download ({n} globe-months) that is "
                      f"{n * d / 3600:.0f}h vs {n * h / 3600:.0f}h at ~{n} GB transfer.")
                print("Worth pricing the pipeline change; stream and discard the hourly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
