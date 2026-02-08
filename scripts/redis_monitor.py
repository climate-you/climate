#!/usr/bin/env python
from __future__ import annotations

import argparse
import time
from typing import Any

try:
    import redis
except ModuleNotFoundError as exc:
    raise SystemExit("redis python package required: pip install redis") from exc


def _fmt_int(v: Any) -> int:
    try:
        return int(v)
    except Exception:
        return 0


def _fmt_float(v: Any) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0


def main() -> int:
    ap = argparse.ArgumentParser(description="Monitor Redis stats for climate_api cache")
    ap.add_argument("--url", default="redis://localhost:6379/0")
    ap.add_argument("--pattern", default="climate_api:*")
    ap.add_argument("--interval", type=float, default=2.0)
    args = ap.parse_args()

    client = redis.Redis.from_url(args.url, decode_responses=True)

    last_hits = None
    last_misses = None
    last_time = None
    last_print_signature = None

    try:
        while True:
            info = client.info()
            hits = _fmt_int(info.get("keyspace_hits"))
            misses = _fmt_int(info.get("keyspace_misses"))
            used_mem = _fmt_int(info.get("used_memory"))
            used_human = info.get("used_memory_human", "")
            uptime = _fmt_int(info.get("uptime_in_seconds"))

            keys = _fmt_int(client.dbsize())
            climate_keys = _fmt_int(len(client.keys(args.pattern)))

            if last_hits is None:
                hit_rate = 0.0
            else:
                dt = max(1e-6, time.time() - (last_time or time.time()))
                hit_rate = (hits - last_hits) / dt

            if last_misses is None:
                miss_rate = 0.0
            else:
                dt = max(1e-6, time.time() - (last_time or time.time()))
                miss_rate = (misses - last_misses) / dt

            signature = (
                f"keys={keys} climate_keys={climate_keys} "
                f"hits={hits} misses={misses} "
                f"hit_rate={hit_rate:.1f}/s miss_rate={miss_rate:.1f}/s"
            )
            if signature != last_print_signature:
                print(
                    f"{signature} "
                    f"mem={used_human} ({used_mem} bytes) uptime={uptime}s"
                )
                last_print_signature = signature

            last_hits = hits
            last_misses = misses
            last_time = time.time()
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
