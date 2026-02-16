#!/usr/bin/env python3
"""
Simple HTTP benchmark for place resolver usage via the API.

This hits /api/v/{release}/panel with random lat/lon samples from locations.csv.
It measures end-to-end request time (not just place lookup).
"""

from __future__ import annotations

import argparse
import csv
import random
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import List, Tuple


def _reservoir_sample_points(csv_path: Path, n: int) -> List[Tuple[float, float]]:
    points: List[Tuple[float, float]] = []
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            lat = row.get("lat")
            lon = row.get("lon")
            if lat is None or lon is None:
                continue
            try:
                point = (float(lat), float(lon))
            except ValueError:
                continue
            if i < n:
                points.append(point)
            else:
                j = random.randint(0, i)
                if j < n:
                    points[j] = point
    return points


def _request(url: str, timeout_s: float) -> None:
    with urllib.request.urlopen(url, timeout=timeout_s) as resp:
        resp.read()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--base-url",
        default="http://127.0.0.1:8001",
        help='API base URL (default: "http://127.0.0.1:8001").',
    )
    ap.add_argument(
        "--release",
        default="dev",
        help='Release (default: "dev").',
    )
    ap.add_argument(
        "--csv",
        type=Path,
        default=Path("data/locations/locations.csv"),
        help='Locations CSV (default: "data/locations/locations.csv").',
    )
    ap.add_argument(
        "--n",
        type=int,
        default=200,
        help="Number of requests to issue.",
    )
    ap.add_argument(
        "--timeout-s",
        type=float,
        default=10.0,
        help="Request timeout seconds.",
    )
    args = ap.parse_args()

    points = _reservoir_sample_points(args.csv, args.n)
    if not points:
        raise SystemExit("No points sampled from locations.csv.")

    durations_ms: List[float] = []
    failures = 0

    for lat, lon in points:
        query = urllib.parse.urlencode({"lat": f"{lat:.5f}", "lon": f"{lon:.5f}"})
        url = f"{args.base_url}/api/v/{args.release}/panel?{query}"

        t0 = time.perf_counter()
        try:
            _request(url, args.timeout_s)
            durations_ms.append((time.perf_counter() - t0) * 1000.0)
        except Exception:
            failures += 1

    if durations_ms:
        durations_ms.sort()
        avg = sum(durations_ms) / len(durations_ms)
        median = durations_ms[len(durations_ms) // 2]
        p95 = durations_ms[int(len(durations_ms) * 0.95) - 1]
    else:
        avg = median = p95 = float("nan")

    print(f"Requests: {len(durations_ms)} ok, {failures} failed")
    print(f"Avg: {avg:.1f} ms")
    print(f"Median: {median:.1f} ms")
    print(f"P95: {p95:.1f} ms")


if __name__ == "__main__":
    main()
