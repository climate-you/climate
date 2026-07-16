#!/usr/bin/env python3
"""Find the latest available day in the ERA5 post-processed daily-statistics
dataset (the source behind t2m_daily_mean_c), so end_day can be set correctly.

Probes CDS with a tiny 1-cell request for candidate days, newest first, and
reports the most recent day that returns data. Each probe is minimal (one
variable, one day, a 1x1 degree box) so it is cheap.

Usage:
    python experiments/check_era5_latest.py            # scans the last ~10 days
    python experiments/check_era5_latest.py --from 2026-07-15 --days 12

Note: CDS limits concurrent requests per user. If a full ingestion is already
running, this probe may queue behind it — run it when the queue is free, or
just let it wait.
"""
from __future__ import annotations

import argparse
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

DATASET = "derived-era5-single-levels-daily-statistics"


def _probe(client, day: date) -> bool:
    req = {
        "product_type": "reanalysis",
        "variable": ["2m_temperature"],
        "year": f"{day.year:04d}",
        "month": f"{day.month:02d}",
        "day": f"{day.day:02d}",
        "daily_statistic": "daily_mean",
        "time_zone": "utc+00:00",
        "frequency": "1_hourly",
        "area": [1, 0, 0, 1],  # tiny 1x1 degree box
        "grid": [1.0, 1.0],
    }
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "probe.nc"
        try:
            client.retrieve(DATASET, req, str(target))
            return target.exists() and target.stat().st_size > 0
        except Exception as exc:  # noqa: BLE001 — any failure == not available
            msg = str(exc).splitlines()[0][:120]
            print(f"  {day.isoformat()}: not available ({msg})")
            return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--from",
        dest="start",
        default=None,
        help="Newest day to try (YYYY-MM-DD); default: today.",
    )
    ap.add_argument("--days", type=int, default=10, help="How many days back to scan.")
    args = ap.parse_args()

    import cdsapi

    client = cdsapi.Client(quiet=True, wait_until_complete=True)
    start = (
        datetime.strptime(args.start, "%Y-%m-%d").date()
        if args.start
        else date.today()
    )
    print(f"Probing {DATASET}\nfrom {start.isoformat()} backwards ({args.days} days):")
    for i in range(args.days):
        day = start - timedelta(days=i)
        if _probe(client, day):
            print(f"\nLatest available day: {day.isoformat()}")
            print(f"  -> set end_month={day.month}, end_day={day.day}")
            return 0
    print("\nNo available day found in the scanned range.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
