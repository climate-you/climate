#!/usr/bin/env python3
"""Regional heat-episode analysis from the ERA5 daily-maximum globe cache.

Builds area-weighted daily-maximum series per country straight from the cached
whole-globe files, using the project's own mask weighting so the numbers match
what the site's aggregates would produce, then reports episodes where a country
exceeds its own 1991-2020 day-of-year percentile.

Definition (Perkins & Alexander style, comparable across countries): an episode
is MIN_RUN or more consecutive days on which the area-weighted regional daily
maximum exceeds the PCTL-th percentile for that day of the year over the
baseline, computed over a +/-WINDOW day window so each threshold rests on
~450 samples rather than 30.

Two things learned the hard way, both encoded here:

- **Restrict to the warm season.** A floorless percentile flags "unusually warm
  for early March" as an episode: extending to March-April yields UK "heatwaves"
  peaking at 12.6 C. May-August is the defensible window; March-April is
  available via --months for the seasonal-cycle charts only, not for counting.
- **Never cache an empty result.** An unmounted external drive globs empty
  rather than raising, and a cached empty frame poisons every later run.

Geometry note: daily-maximum globe files were verified bit-identical between
pre- and post-30-July-2026 CDS downloads (2015-07 and 1993-07, zero difference
across 32.1M values), so baseline and target sit on one consistent grid.

Usage:
    python experiments/heatwave_analysis.py                      # europe, May-Aug
    python experiments/heatwave_analysis.py --set global
    python experiments/heatwave_analysis.py --set europe --months 3 4 5 6 7 8
    python experiments/heatwave_analysis.py --set global --csv-only
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from climate.tiles.layout import GridSpec  # noqa: E402
from climate.geo.continents import CONTINENT_TO_CC  # noqa: E402
from precompute_regional_aggregates import (  # noqa: E402
    _build_fractional_weights,
    _area_weights,
)

GLOBE = Path(
    "/Volumes/LaCie/Climate/cache/cds/"
    "era5_daily_2m_temperature_daily_maximum_global_0p25_r000-011_c000-022"
)
CACHE_DIR = ROOT / "logs" / "analysis"

EUROPE = {
    "GB": "United Kingdom",
    "FR": "France",
    "ES": "Spain",
    "PT": "Portugal",
    "IT": "Italy",
    "DE": "Germany",
    "GR": "Greece",
    "NL": "Netherlands",
}
# Northern hemisphere only: the story is a boreal summer, so southern countries
# are in winter and a May-Aug count there means nothing.
GLOBAL = dict(
    EUROPE,
    **{
        "US": "United States",
        "CA": "Canada",
        "MX": "Mexico",
        "CN": "China",
        "IN": "India",
        "JP": "Japan",
        "KR": "South Korea",
        "RU": "Russia",
        "TR": "Turkey",
        "IR": "Iran",
        "EG": "Egypt",
        "PK": "Pakistan",
    },
)
SETS = {"europe": EUROPE, "global": GLOBAL}


def month_files(year: int, month: int) -> list[Path]:
    pat = re.compile(rf"_{year}-{year}_m{month:02d}-{month:02d}(_d\d+-\d+)?\.nc$")
    return sorted(p for p in GLOBE.glob("*.nc") if pat.search(p.name))


def build_weights(regions: dict[str, str]) -> dict[str, np.ndarray]:
    grid = GridSpec.global_0p25()
    with np.load(ROOT / "data/locations/country_mask.npz") as f:
        mask, deg = np.asarray(f["data"]), float(f["deg"])
    frac = _build_fractional_weights(mask, deg, grid)
    codes = json.load(open(ROOT / "data/locations/country_codes.json"))
    code_to_uid = {v: int(k) for k, v in codes.items()}
    aw = _area_weights(grid)[:, None]
    out: dict[str, np.ndarray] = {}
    for cc, name in regions.items():
        uid = code_to_uid.get(cc)
        if uid is not None and uid in frac:
            out[name] = frac[uid] * aw
        else:
            print(f"  [warn] no mask for {cc}")
    eu = np.zeros((grid.nlat, grid.nlon), dtype=np.float32)
    for cc in CONTINENT_TO_CC.get("europe", []):
        uid = code_to_uid.get(cc)
        if uid in frac:
            eu += frac[uid]
    out["Europe (land)"] = np.clip(eu, 0, 1) * aw
    return out


def series_for(files: list[Path], weights: dict) -> dict[str, pd.Series]:
    acc: dict[str, dict] = defaultdict(dict)
    for n, f in enumerate(files, 1):
        ds = xr.open_dataset(f)
        da = ds[list(ds.data_vars)[0]]
        vals = np.asarray(da.values, dtype=np.float32) - 273.15
        times = pd.to_datetime(da[da.dims[0]].values)
        for name, w in weights.items():
            s = (vals * w[None, :, :]).sum(axis=(1, 2)) / w.sum()
            for t, v in zip(times, s):
                acc[name][t] = float(v)
        ds.close()
        if n % 25 == 0:
            print(f"   ...{n}/{len(files)} files", flush=True)
    return {k: pd.Series(v).sort_index() for k, v in acc.items()}


def load_or_build(regions, months, target, baseline, cache: Path) -> dict:
    if cache.exists():
        print(f"Loading cached series: {cache}", flush=True)
        df = pd.read_csv(cache, index_col=0, parse_dates=True)
        return {c: df[c].dropna() for c in df.columns}
    print("Building region weights...", flush=True)
    weights = build_weights(regions)
    files = [p for m in months for p in month_files(target, m)]
    files += [p for y in baseline for m in months for p in month_files(y, m)]
    print(f"Reading {len(files)} globe files (one-off; cached afterwards)", flush=True)
    if not files:
        raise SystemExit(f"No globe files under {GLOBE} — is the drive mounted?")
    ser = series_for(files, weights)
    if not ser:
        raise SystemExit("No series produced; refusing to write an empty cache.")
    cache.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(ser).to_csv(cache)
    print(f"Cached -> {cache}", flush=True)
    return ser


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--set", dest="setname", choices=sorted(SETS), default="europe")
    ap.add_argument("--months", type=int, nargs="+", default=[5, 6, 7, 8])
    ap.add_argument("--target-year", type=int, default=2026)
    ap.add_argument("--baseline", type=int, nargs=2, default=[1991, 2020])
    ap.add_argument("--pctl", type=float, default=90)
    ap.add_argument("--window", type=int, default=7)
    ap.add_argument("--min-run", type=int, default=3)
    ap.add_argument(
        "--detect-from-month",
        type=int,
        default=5,
        help="ignore episodes before this month; a floorless "
        "percentile flags March warm spells as heatwaves",
    )
    ap.add_argument("--cache", type=Path, default=None)
    ap.add_argument("--csv-only", action="store_true", help="build the cache and stop")
    ap.add_argument("--json-out", type=Path, default=None)
    args = ap.parse_args()

    regions = SETS[args.setname]
    b0, b1 = args.baseline
    tag = f"{args.setname}_m{min(args.months)}-{max(args.months)}_{args.target_year}"
    cache = args.cache or CACHE_DIR / f"daily_max_{tag}.csv"

    allser = load_or_build(
        regions, args.months, args.target_year, range(b0, b1 + 1), cache
    )
    if args.csv_only:
        return 0

    target = {k: v[v.index.year == args.target_year] for k, v in allser.items()}
    base = {
        k: v[(v.index.year >= b0) & (v.index.year <= b1)] for k, v in allser.items()
    }

    print("\n" + "=" * 78)
    print(
        f"Episodes: daily max > {args.pctl:g}th pctl of {b0}-{b1} "
        f"(+/-{args.window}d), {args.min_run}+ consecutive days"
    )
    print("=" * 78)

    summary, events = [], {}
    for name in list(regions.values()) + ["Europe (land)"]:
        if name not in target:
            continue
        t, b = target[name], base[name]
        bdoy, bval = b.index.dayofyear.values, b.values
        thr = pd.Series(
            [
                np.percentile(
                    bval[np.abs(bdoy - d.dayofyear) <= args.window], args.pctl
                )
                for d in t.index
            ],
            index=t.index,
        )
        exc = t - thr
        hot = (exc > 0).values
        runs, start = [], None
        for i, f in enumerate(hot):
            if f and start is None:
                start = i
            elif not f and start is not None:
                runs.append((start, i - 1))
                start = None
        if start is not None:
            runs.append((start, len(hot) - 1))
        ev = [
            (a, bb)
            for a, bb in runs
            if bb - a + 1 >= args.min_run
            and t.index[bb].month >= args.detect_from_month
        ]
        print(
            f"\n### {name}   ({len(ev)} episodes, "
            f"{sum(bb - a + 1 for a, bb in ev)} days)"
        )
        events[name] = []
        for k, (a, bb) in enumerate(ev, 1):
            tseg, seg = t.iloc[a : bb + 1], exc.iloc[a : bb + 1]
            tail = "  [truncated by data end]" if bb == len(hot) - 1 else ""
            print(
                f"   {k}. {t.index[a].date()} -> {t.index[bb].date()} "
                f"({bb - a + 1:2d}d)  peak {tseg.max():5.1f} C on "
                f"{tseg.idxmax().date()}  +{seg.max():.1f} C{tail}"
            )
            events[name].append(
                {
                    "a": str(t.index[a].date()),
                    "b": str(t.index[bb].date()),
                    "d": int(bb - a + 1),
                    "peak": round(float(tseg.max()), 2),
                    "excess": round(float(seg.max()), 2),
                    "truncated": bb == len(hot) - 1,
                }
            )
        print(f"   hottest day: {t.idxmax().date()} at {t.max():.1f} C")
        summary.append((name, len(ev), sum(bb - a + 1 for a, bb in ev)))

    print("\n" + "=" * 78)
    print(f"{'region':18s} {'episodes':>9s} {'days':>6s}")
    for name, n, d in summary:
        print(f"{name:18s} {n:9d} {d:6d}")

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        json.dump(
            {
                "events": events,
                "summary": [
                    {"region": n, "episodes": e, "days": d} for n, e, d in summary
                ],
            },
            open(args.json_out, "w"),
            indent=1,
        )
        print(f"\nwrote {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
