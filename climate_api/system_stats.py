from __future__ import annotations

import resource
import sys


def current_rss_bytes() -> int:
    """Current process RSS: VmRSS from /proc/self/status on Linux, ru_maxrss on macOS."""
    if sys.platform != "darwin":
        try:
            with open("/proc/self/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1]) * 1024  # KB → bytes
        except Exception:
            pass
    # macOS: ru_maxrss is bytes and tracks the current working set
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss


def system_memory() -> dict[str, int] | None:
    """Total/available system RAM from /proc/meminfo (Linux only).

    Returns keys ``total`` and ``available`` in bytes.
    ``available`` (MemAvailable) accounts for reclaimable page cache, so
    ``total - available`` gives a realistic "in-use" figure.
    Returns None on non-Linux platforms or if /proc/meminfo is unreadable.
    """
    try:
        mem: dict[str, int] = {}
        with open("/proc/meminfo") as f:
            for line in f:
                key, val = line.split(":", 1)
                mem[key.strip()] = int(val.split()[0]) * 1024  # KB → bytes
        return {
            "total": mem["MemTotal"],
            "available": mem["MemAvailable"],
        }
    except Exception:
        return None
