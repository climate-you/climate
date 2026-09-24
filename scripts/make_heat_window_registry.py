#!/usr/bin/env python3
"""Generate the registry entries for a run of evenly spaced heat-anomaly windows.

The summer-2026 case study steps a slider across 1 June - 15 August. Each tick
is one derived metric, one texture map and one hidden layer, and writing ~45
entries by hand is both tedious and easy to get subtly wrong, so they are
generated from one description of the window run.

This is deliberately the blunt version: one registry entry per frame. A single
entry describing a frame sequence would be tidier, but it needs a new asset
shape in the packager and the release descriptor, which is a larger change than
this story should carry. The generated ids share the `t2m_heatslider_*` prefix
so they are easy to find and remove later.

Entries are inserted, never reformatted: the file is read as text and new
objects are spliced in before the closing brace, so an unrelated diff never
appears alongside them. Re-running replaces the generated block.

Usage:
    python scripts/make_heat_window_registry.py            # write the entries
    python scripts/make_heat_window_registry.py --dry-run  # just report
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PREFIX = "t2m_heatslider_sum26"
WINDOW_START = dt.date(2026, 6, 1)
WINDOW_END = dt.date(2026, 8, 31)
STEP_DAYS = 5
CLIM_START, CLIM_END = 1991, 2020
# Same ramp and range as the other heat maps on the site, so a reader stepping
# the slider is comparing like with like.
COLORS = [
    "#ffffcc", "#ffeda0", "#fed976", "#feb24c",
    "#fd8d3c", "#fc4e2a", "#e31a1c", "#b10026",
]
VMIN, VMAX = 0.0, 12.0

MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def windows() -> list[tuple[str, dt.date, dt.date]]:
    """Five-day windows that never straddle a month boundary.

    A window spanning two months would have to blend two climatologies, and its
    label would read awkwardly against its neighbours. Each calendar month is
    chunked on its own instead, and a short remainder joins the last chunk of
    that month, so July ends on a six-day window rather than a one-day stub.
    """
    spans: list[tuple[dt.date, dt.date]] = []
    month_start = WINDOW_START
    while month_start <= WINDOW_END:
        if month_start.month == 12:
            next_month = dt.date(month_start.year + 1, 1, 1)
        else:
            next_month = dt.date(month_start.year, month_start.month + 1, 1)
        month_end = min(next_month - dt.timedelta(days=1), WINDOW_END)

        chunks: list[tuple[dt.date, dt.date]] = []
        start = month_start
        while start <= month_end:
            end = min(start + dt.timedelta(days=STEP_DAYS - 1), month_end)
            chunks.append((start, end))
            start = end + dt.timedelta(days=1)
        if len(chunks) > 1 and (chunks[-1][1] - chunks[-1][0]).days + 1 < 3:
            last = chunks.pop()
            chunks[-1] = (chunks[-1][0], last[1])
        spans.extend(chunks)
        month_start = next_month
    return [(f"{PREFIX}_{i:02d}", a, b) for i, (a, b) in enumerate(spans)]


def label(a: dt.date, b: dt.date) -> str:
    if a.month == b.month:
        return f"{a.day}–{b.day} {MONTHS[a.month]}"
    return f"{a.day} {MONTHS[a.month]} – {b.day} {MONTHS[b.month]}"


def metric_entry(mid: str, a: dt.date, b: dt.date) -> str:
    months = sorted({a.month, b.month})
    return f'''  "{mid}_anomaly_c": {{
    "id": "{mid}_anomaly_c",
    "title": "Air temperature anomaly, {label(a, b)} 2026 vs {CLIM_START}-{CLIM_END}",
    "unit": "C",
    "dtype": "float32",
    "missing": "nan",
    "domain": "global",
    "time_axis": "yearly",
    "llm_hidden": true,
    "source": {{
      "type": "derived",
      "inputs": ["t2m_daily_mean_c", "t2m_monthly_mean_c"],
      "steps": [
        {{
          "fn": "daily_window_anomaly",
          "params": {{
            "window_start": "{a.isoformat()}",
            "window_end": "{b.isoformat()}",
            "clim_months": {json.dumps(months)},
            "clim_start_year": {CLIM_START},
            "clim_end_year": {CLIM_END},
            "label_year": 2026
          }}
        }}
      ]
    }},
    "storage": {{ "tiled": true, "compression": {{ "codec": "zstd", "level": 10 }} }}
  }}'''


def map_entry(mid: str, a: dt.date, b: dt.date) -> str:
    colors = ",\n        ".join(f'"{c}"' for c in COLORS)
    return f'''  "{mid}_mercator_texture": {{
    "id": "{mid}_mercator_texture",
    "title": "Air temperature anomaly, {label(a, b)} 2026 (Mercator)",
    "type": "texture",
    "file_format": "webp",
    "projection": "mercator",
    "mercator_lat_max": 85.05112878,
    "web_write": true,
    "source_metric": "{mid}_anomaly_c",
    "reducer": {{ "op": "year", "year": 2026 }},
    "palette": {{
      "colors": [
        {colors}
      ],
      "nan_color": "#000000",
      "nan_alpha": 0.0
    }},
    "scale": {{
      "mode": "linear",
      "vmin": {VMIN},
      "vmax": {VMAX}
    }},
    "output": {{
      "filename": "{mid}_mercator.webp",
      "width": 1440,
      "height": 2150
    }}
  }}'''


def layer_entry(mid: str, a: dt.date, b: dt.date) -> str:
    return f'''  "{mid}": {{
    "id": "{mid}",
    "enable": false,
    "label": "{label(a, b)}",
    "unit": "temperature",
    "description": "Mean air temperature over {label(a, b)} 2026 against the {CLIM_START}\\u2013{CLIM_END} average for the same dates.",
    "map_id": "{mid}_mercator_texture",
    "opacity": 0.8,
    "resampling": "nearest"
  }}'''


def splice(path: Path, blocks: list[str], dry_run: bool) -> None:
    """Replace the generated block, or append one before the closing brace.

    Every key in these files has to be a valid id, so the block cannot be
    fenced with a marker key. It is always appended last and always starts with
    window 00, so that id locates it for replacement on a re-run.
    """
    text = io.open(path, encoding="utf-8").read()
    body = ",\n".join(blocks)
    first_id = re.search(r'^  "(' + PREFIX + r'_00[a-z_]*)":', body, re.M)
    assert first_id, "generated block does not start with window 00"
    anchor = f'  "{first_id.group(1)}": {{'

    start = text.find(anchor)
    if start != -1:
        # Drop everything from the old block to just before the closing brace.
        head = text[:start].rstrip().rstrip(",")
    else:
        head = text.rstrip().rstrip("\n")
        i = head.rfind("}")
        head = head[:i].rstrip()
    assert head.endswith("}"), head[-60:]
    text = head + ",\n" + body + "\n}\n"
    json.loads(text)  # parse check before writing
    if dry_run:
        print(f"  would write {path.relative_to(REPO_ROOT)} "
              f"({len(body.splitlines())} lines)")
        return
    io.open(path, "w", encoding="utf-8").write(text)
    print(f"  wrote {path.relative_to(REPO_ROOT)} ({len(body.splitlines())} lines)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    wins = windows()
    print(f"{len(wins)} windows of up to {STEP_DAYS} days, "
          f"{WINDOW_START} to {WINDOW_END}:")
    for mid, a, b in wins:
        print(f"  {mid}  {label(a, b)}")
    print()

    splice(REPO_ROOT / "registry/metrics.json",
           [metric_entry(m, a, b) for m, a, b in wins], args.dry_run)
    splice(REPO_ROOT / "registry/maps.json",
           [map_entry(m, a, b) for m, a, b in wins], args.dry_run)
    splice(REPO_ROOT / "registry/layers.json",
           [layer_entry(m, a, b) for m, a, b in wins], args.dry_run)

    print()
    print("Then render (local only, no downloads):")
    maps = " ".join(f"--map {m}_mercator_texture" for m, _, _ in wins)
    print(f"  python scripts/build/packager.py --release dev --all --resume \\\n"
          f"      --start-year 2026 --end-year 2026 {maps}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
