#!/usr/bin/env python3
"""
Benchmark a few API endpoints and report latency stats.
"""

from __future__ import annotations

import argparse
import csv
import random
import time
import urllib.parse
import urllib.request
import json
from pathlib import Path
from typing import List, Tuple


def _request(url: str, timeout_s: float) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as resp:
            return int(resp.status), resp.read()
    except urllib.error.HTTPError as e:
        return int(e.code), e.read()


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


def _sample_geonameids(index_csv: Path, n: int) -> List[int]:
    ids: List[int] = []
    with open(index_csv, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            gid = row.get("geonameid")
            if not gid:
                continue
            try:
                val = int(gid)
            except ValueError:
                continue
            if i < n:
                ids.append(val)
            else:
                j = random.randint(0, i)
                if j < n:
                    ids[j] = val
    return ids


def _stats(durations_ms: List[float]) -> tuple[float, float, float]:
    if not durations_ms:
        return float("nan"), float("nan"), float("nan")
    durations_ms.sort()
    avg = sum(durations_ms) / len(durations_ms)
    median = durations_ms[len(durations_ms) // 2]
    p95 = durations_ms[int(len(durations_ms) * 0.95) - 1]
    return avg, median, p95


def _bench_urls(urls: List[str], timeout_s: float) -> tuple[int, int, float, float, float]:
    durations_ms: List[float] = []
    failures = 0
    for url in urls:
        t0 = time.perf_counter()
        try:
            _request(url, timeout_s)
            durations_ms.append((time.perf_counter() - t0) * 1000.0)
        except Exception:
            failures += 1
    avg, median, p95 = _stats(durations_ms)
    return len(durations_ms), failures, avg, median, p95


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
        "--locations-csv",
        type=Path,
        default=Path("data/locations/locations.csv"),
        help='Locations CSV (default: "data/locations/locations.csv").',
    )
    ap.add_argument(
        "--index-csv",
        type=Path,
        default=Path("data/locations/locations.index.csv"),
        help='Locations index CSV (default: "data/locations/locations.index.csv").',
    )
    ap.add_argument("--n", type=int, default=200, help="Requests per endpoint.")
    ap.add_argument("--timeout-s", type=float, default=10.0, help="Request timeout.")
    ap.add_argument(
        "--smoke",
        action="store_true",
        help="Run a smoke check on response codes and schema.",
    )
    ap.add_argument(
        "--max-p95-panel-ms",
        type=float,
        default=None,
        help="Fail if panel p95 exceeds this threshold.",
    )
    ap.add_argument(
        "--max-p95-autocomplete-ms",
        type=float,
        default=None,
        help="Fail if autocomplete p95 exceeds this threshold.",
    )
    ap.add_argument(
        "--max-p95-resolve-ms",
        type=float,
        default=None,
        help="Fail if resolve p95 exceeds this threshold.",
    )
    ap.add_argument(
        "--autocomplete-query",
        action="append",
        default=[],
        help="Autocomplete query string (repeatable). Defaults to a small set.",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )
    ap.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Write JSON output to a file (implies --json).",
    )
    ap.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress human-readable output (useful with --json).",
    )
    args = ap.parse_args()

    points = _reservoir_sample_points(args.locations_csv, args.n)
    if not points:
        raise SystemExit("No points sampled from locations.csv.")

    geonameids = _sample_geonameids(args.index_csv, min(args.n, 200))
    if not geonameids:
        raise SystemExit("No geonameids sampled from locations index.")

    auto_queries = args.autocomplete_query or ["par", "san", "new", "lon", "tok"]

    panel_urls = []
    for lat, lon in points:
        query = urllib.parse.urlencode({"lat": f"{lat:.5f}", "lon": f"{lon:.5f}"})
        panel_urls.append(f"{args.base_url}/api/v/{args.release}/panel?{query}")

    auto_urls = []
    for q in auto_queries:
        query = urllib.parse.urlencode({"q": q})
        auto_urls.append(
            f"{args.base_url}/api/v/{args.release}/locations/autocomplete?{query}"
        )

    resolve_urls = []
    for gid in geonameids:
        query = urllib.parse.urlencode({"geonameid": gid})
        resolve_urls.append(
            f"{args.base_url}/api/v/{args.release}/locations/resolve?{query}"
        )

    if args.json_out is not None:
        args.json = True

    results = {
        "panel": {},
        "autocomplete": {},
        "resolve": {},
        "smoke": None,
        "regression_failed": False,
    }

    def _print(msg: str) -> None:
        if not args.quiet and not args.json:
            print(msg)

    _print("Panel endpoint:")
    ok, fail, avg, median, panel_p95 = _bench_urls(panel_urls, args.timeout_s)
    _print(f"  Requests: {ok} ok, {fail} failed")
    _print(f"  Avg: {avg:.1f} ms  Median: {median:.1f} ms  P95: {panel_p95:.1f} ms")
    results["panel"] = {
        "ok": ok,
        "failed": fail,
        "avg_ms": avg,
        "median_ms": median,
        "p95_ms": panel_p95,
    }

    _print("Autocomplete endpoint:")
    ok, fail, avg, median, auto_p95 = _bench_urls(auto_urls, args.timeout_s)
    _print(f"  Requests: {ok} ok, {fail} failed")
    _print(f"  Avg: {avg:.1f} ms  Median: {median:.1f} ms  P95: {auto_p95:.1f} ms")
    results["autocomplete"] = {
        "ok": ok,
        "failed": fail,
        "avg_ms": avg,
        "median_ms": median,
        "p95_ms": auto_p95,
    }

    _print("Resolve endpoint:")
    ok, fail, avg, median, resolve_p95 = _bench_urls(resolve_urls, args.timeout_s)
    _print(f"  Requests: {ok} ok, {fail} failed")
    _print(f"  Avg: {avg:.1f} ms  Median: {median:.1f} ms  P95: {resolve_p95:.1f} ms")
    results["resolve"] = {
        "ok": ok,
        "failed": fail,
        "avg_ms": avg,
        "median_ms": median,
        "p95_ms": resolve_p95,
    }

    if args.smoke:
        _print("Smoke checks:")

        def _require(cond: bool, msg: str) -> None:
            if not cond:
                raise SystemExit(f"Smoke check failed: {msg}")

        # Panel smoke: one request, 200, required keys
        status, body = _request(panel_urls[0], args.timeout_s)
        _require(status == 200, f"panel status {status}")
        data = json.loads(body.decode("utf-8"))
        for key in ("release", "unit", "location", "panels", "series"):
            _require(key in data, f"panel missing key: {key}")
        _require("place" in data["location"], "panel.location missing place")
        _require("geonameid" in data["location"]["place"], "place missing geonameid")

        # Autocomplete smoke
        status, body = _request(auto_urls[0], args.timeout_s)
        _require(status == 200, f"autocomplete status {status}")
        data = json.loads(body.decode("utf-8"))
        _require("results" in data, "autocomplete missing results")
        if data["results"]:
            item = data["results"][0]
            for key in ("geonameid", "label", "lat", "lon", "country_code"):
                _require(key in item, f"autocomplete item missing {key}")

        # Resolve smoke
        status, body = _request(resolve_urls[0], args.timeout_s)
        _require(status == 200, f"resolve status {status}")
        data = json.loads(body.decode("utf-8"))
        _require("result" in data, "resolve missing result")
        _require(data["result"] is not None, "resolve result is null")

        _print("  ok")
        results["smoke"] = True
    else:
        results["smoke"] = None

    regress_fail = False
    if args.max_p95_panel_ms is not None and panel_p95 > args.max_p95_panel_ms:
        _print(
            f"Panel p95 regression: {panel_p95:.1f} ms > {args.max_p95_panel_ms:.1f} ms"
        )
        regress_fail = True
    if (
        args.max_p95_autocomplete_ms is not None
        and auto_p95 > args.max_p95_autocomplete_ms
    ):
        _print(
            f"Autocomplete p95 regression: {auto_p95:.1f} ms > {args.max_p95_autocomplete_ms:.1f} ms"
        )
        regress_fail = True
    if args.max_p95_resolve_ms is not None and resolve_p95 > args.max_p95_resolve_ms:
        _print(
            f"Resolve p95 regression: {resolve_p95:.1f} ms > {args.max_p95_resolve_ms:.1f} ms"
        )
        regress_fail = True

    if regress_fail:
        results["regression_failed"] = True

    if args.json:
        payload = json.dumps(results, indent=2)
        if args.json_out is not None:
            args.json_out.parent.mkdir(parents=True, exist_ok=True)
            args.json_out.write_text(payload + "\n", encoding="utf-8")
        else:
            print(payload)

    if regress_fail:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
