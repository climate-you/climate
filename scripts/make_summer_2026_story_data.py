#!/usr/bin/env python3
"""Generate the data file behind the summer 2026 case study page.

The page at web/src/app/stories/summer-2026-heat-and-drought imports this
script's output directly, so every figure it quotes and every series its charts
draw is computed here from the release rather than typed into the markup. A
data refresh plus one re-run of this script moves the prose and the charts
together; they cannot drift apart.

Inputs (all local; the CDS cache is NOT needed):
  data/releases/<release>/series/...        packaged metrics and regional aggregates
  logs/**/episodes_global.json              heat episodes, from heatwave_analysis.py

Usage:
    PYTHONPATH=$PWD conda run -n climate python \
        scripts/make_summer_2026_story_data.py \
        --json web/src/content/stories/summer-2026-heat-and-drought/data.json

See docs/runbooks/case-study-data.md for the whole workflow.
"""
from __future__ import annotations

import argparse
import base64
import calendar
import datetime as dt
import glob
import io
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SER = ROOT / "data/releases/dev/series/global_0p25"
MAPS = ROOT / "data/releases/dev/maps/global_0p25"
DRY0, DRY1 = "2026-06-01", "2026-08-15"
WET0, WET1 = "2026-08-16", "2026-08-31"
BASE = (1991, 2020)
EUR = {"Portugal", "Spain", "France", "Germany", "Italy", "United Kingdom",
       "Greece", "Netherlands"}
CC = {"Portugal": "PT", "Spain": "ES", "France": "FR", "Germany": "DE",
      "United Kingdom": "GB", "Italy": "IT", "Greece": "GR", "Netherlands": "NL",
      "United States": "US", "China": "CN", "India": "IN", "Japan": "JP",
      "Canada": "CA", "Russia": "RU", "Turkey": "TR", "Mexico": "MX",
      "Pakistan": "PK"}
WARM = [("Europe", 0.503), ("North America", 0.387), ("Asia", 0.362),
        ("Global land", 0.333), ("Africa", 0.315), ("South America", 0.235),
        ("Globe incl. ocean", 0.211), ("Antarctica", 0.153), ("Oceania", 0.137)]


# --------------------------------------------------------------------------- data
def agg(metric: str) -> dict:
    return json.load(open(SER / metric / "aggregates/mean.json"))


def rain_windows() -> dict:
    """Observed and climatological accumulation per country, both windows."""
    D, M = agg("tp_daily_total_mm"), agg("tp_monthly_mean_mm_per_day")
    dax, max_ = D["time_axis"], M["time_axis"]
    out = {}
    for name, cc in CC.items():
        key = f"country:{cc}"
        if key not in D["regions"]:
            continue
        dv = D["regions"][key]["values"]
        mv = M["regions"][key]["values"]
        clim: dict[int, list] = {}
        for t, x in zip(max_, mv):
            if x is None:
                continue
            y, m = int(str(t)[:4]), int(str(t)[5:7])
            if BASE[0] <= y <= BASE[1]:
                clim.setdefault(m, []).append(x)
        clim = {m: sum(v) / len(v) for m, v in clim.items()}
        row = {}
        for tag, (a, b) in (("dry", (DRY0, DRY1)), ("wet", (WET0, WET1))):
            obs = sum(x for t, x in zip(dax, dv) if a <= str(t) <= b and x is not None)
            days: dict[int, int] = {}
            for t, x in zip(dax, dv):
                if a <= str(t) <= b and x is not None:
                    m = int(str(t)[5:7]); days[m] = days.get(m, 0) + 1
            exp = sum(clim[m] * n for m, n in days.items())
            row[tag] = {"obs": obs, "exp": exp, "pct": 100 * obs / exp,
                        "days": sum(days.values())}
        row["ratio"] = row["wet"]["obs"] / row["dry"]["obs"]
        out[name] = row
    return out


def episodes() -> dict:
    """The most recent episode list, wherever the run that produced it wrote it.

    This globbed a single dated directory ("logs/aug28-*"), so every later run
    was written and then ignored: the page quoted heat-episode counts from the
    28 August data while every other figure had moved on to 31 August. Take the
    newest file by modification time and say which one was used.
    """
    files = glob.glob(str(ROOT / "logs/**/episodes_global.json"), recursive=True)
    if not files:
        raise SystemExit("no episodes_global.json — run experiments/heatwave_analysis.py")
    newest = max(files, key=lambda p: Path(p).stat().st_mtime)
    print(f"  episodes from {Path(newest).relative_to(ROOT)}")
    return json.load(open(newest))


def joint_history(country="France", months=(6, 7, 8)) -> list:
    """Every year's JJA temperature anomaly and rainfall share.

    Full June-August, now that August 2026 is complete. June-July was used while
    August was partial; the claim holds on both for France, and JJA needs no
    explaining to a reader where "why June-July?" does.
    """
    T, P = agg("t2m_monthly_mean_c"), agg("tp_monthly_mean_mm_per_day")
    key = f"country:{CC[country]}"

    def by_year(a, ax):
        v = a["regions"][key]["values"]; out = {}
        for t, x in zip(ax, v):
            if x is None:
                continue
            y, m = int(str(t)[:4]), int(str(t)[5:7])
            if m in months:
                out.setdefault(y, {})[m] = x
        return {y: d for y, d in out.items() if len(d) == len(months)}

    ts, ps = by_year(T, T["time_axis"]), by_year(P, P["time_axis"])
    yrs = sorted(set(ts) & set(ps))
    b = [y for y in yrs if BASE[0] <= y <= BASE[1]]
    tb = np.mean([np.mean(list(ts[y].values())) for y in b])
    pb = np.mean([sum(ps[y][m] * calendar.monthrange(y, m)[1] for m in months) for y in b])
    return [(y, float(np.mean(list(ts[y].values())) - tb),
             float(sum(ps[y][m] * calendar.monthrange(y, m)[1] for m in months) / pb * 100))
            for y in yrs]


def cumulative_daily(countries) -> dict:
    """Cumulative rainfall 1 Jun -> 31 Aug 2026, with the climatological curve.

    Absolute millimetres alone are misleading: France gets more rain than Spain
    in any year, so its 2026 line still climbs and looks wet. Plotting the
    1991-2020 normal accumulation beside it turns the chart into the gap between
    them, which is the thing the story is about.
    """
    D, M = agg("tp_daily_total_mm"), agg("tp_monthly_mean_mm_per_day")
    dax, max_ = D["time_axis"], M["time_axis"]
    out = {}
    for n in countries:
        key = f"country:{CC[n]}"
        dv = D["regions"][key]["values"]
        mv = M["regions"][key]["values"]
        clim: dict[int, list] = {}
        for t, x in zip(max_, mv):
            if x is None:
                continue
            y, m = int(str(t)[:4]), int(str(t)[5:7])
            if BASE[0] <= y <= BASE[1]:
                clim.setdefault(m, []).append(x)
        clim = {m: sum(v) / len(v) for m, v in clim.items()}
        run = norm = 0.0
        obs_pts, norm_pts = [], []
        for t, x in zip(dax, dv):
            if not ("2026-06-01" <= str(t) <= WET1) or x is None:
                continue
            run += x
            norm += clim[int(str(t)[5:7])]
            obs_pts.append((str(t), round(run, 1)))
            norm_pts.append((str(t), round(norm, 1)))
        out[n] = {"obs": obs_pts, "norm": norm_pts}
    return out




# --------------------------------------------------------------------------- charts





















# --------------------------------------------------------------------------- page


def monthly_grid() -> dict:
    """The period-by-country % of normal behind c_monthly, as plain data."""
    D = agg("tp_daily_total_mm"); M = agg("tp_monthly_mean_mm_per_day")
    dax, max_ = D["time_axis"], M["time_axis"]
    periods = [("June", "2026-06-01", "2026-06-30"), ("July", "2026-07-01", "2026-07-31"),
               ("1–15 Aug", "2026-08-01", "2026-08-15"), ("16–31 Aug", "2026-08-16", "2026-08-31")]
    names = ["Portugal", "Spain", "France", "Italy", "Germany", "United Kingdom", "Greece"]
    grid = {}
    for n in names:
        dv = D["regions"][f"country:{CC[n]}"]["values"]
        mv = M["regions"][f"country:{CC[n]}"]["values"]
        clim = {}
        for t, x in zip(max_, mv):
            if x is None: continue
            y, m = int(str(t)[:4]), int(str(t)[5:7])
            if BASE[0] <= y <= BASE[1]: clim.setdefault(m, []).append(x)
        clim = {m: sum(v) / len(v) for m, v in clim.items()}
        row = []
        for _, a, b in periods:
            obs = sum(x for t, x in zip(dax, dv) if a <= str(t) <= b and x is not None)
            nd = sum(1 for t, x in zip(dax, dv) if a <= str(t) <= b and x is not None)
            row.append(round(100 * obs / (clim[int(a[5:7])] * nd), 1))
        grid[n] = row
    return {"periods": [p[0] for p in periods], "names": names, "grid": grid}


def spaghetti_data(countries) -> dict:
    """Daily maximum by day-of-year: every baseline year plus 2026, per country.

    Stored as one day-of-year axis and a value array per year so the page's
    bundle stays small; day-of-year is taken from the calendar date, so leap
    years land a day later, which is invisible at chart scale.
    """
    f = ROOT / "logs/analysis/daily_max_europe_m3-8_2026.csv"
    if not f.exists():
        return {}
    df = pd.read_csv(f, index_col=0, parse_dates=True)
    out = {}
    for c in countries:
        if c not in df.columns:
            continue
        s = df[c].dropna()
        years = {}
        for y in list(range(BASE[0], BASE[1] + 1)) + [2026]:
            v = s[s.index.year == y]
            if v.empty:
                continue
            doys = [int(i.strftime("%j")) for i in v.index]
            # Days are consecutive within the March-August window, so only the
            # first day-of-year is stored and the rest are implied; repeating it
            # per point roughly doubled the file.
            assert doys == list(range(doys[0], doys[0] + len(doys))), c
            years[str(y)] = {"d0": doys[0], "v": [round(float(x), 1) for x in v]}
        out[c] = years
    return out


def peaks_2026(countries) -> dict:
    """Hottest 2026 day per country on the area-weighted daily maximum."""
    f = ROOT / "logs/analysis/daily_max_global_m5-8_2026.csv"
    if not f.exists():
        return {}
    df = pd.read_csv(f, index_col=0, parse_dates=True)
    out = {}
    for c in countries:
        if c not in df.columns:
            continue
        s = df[c][df.index.year == 2026].dropna()
        out[c] = {"date": str(s.idxmax().date()), "value": round(float(s.max()), 1),
                  "aug13": round(float(s.get(pd.Timestamp("2026-08-13"), float("nan"))), 1)}
    return out


def days_in_window(events: dict, a: str, b: str) -> dict:
    """Episode days falling inside [a, b], per country.

    The scatter plots heat against rainfall, so both axes have to cover the
    same dates; the unrestricted count runs May-August while the rainfall
    window is 1 Jun - 15 Aug.
    """
    out = {}
    for name, evs in events.items():
        n = 0
        for e in evs:
            lo = max(e["a"], a)
            hi = min(e["b"], b)
            if lo <= hi:
                n += (dt.date(*map(int, hi.split("-")))
                      - dt.date(*map(int, lo.split("-")))).days + 1
        out[name] = n
    return out


def europe_decades() -> dict:
    """Europe's mean temperature in the first and last ten years of the record.

    Continental annual means, so this is not comparable with the globe's
    per-location figure, which is measured against pre-industrial rather than
    against the start of the satellite record.
    """
    a = agg("t2m_yearly_mean_c")
    yr = {int(str(t)[:4]): x for t, x in zip(a["time_axis"],
                                             a["regions"]["continent:europe"]["values"])
          if x is not None}
    first = [y for y in sorted(yr) if y <= sorted(yr)[0] + 9]
    last = [y for y in sorted(yr) if y <= 2025][-10:]
    fm = sum(yr[y] for y in first) / len(first)
    lm = sum(yr[y] for y in last) / len(last)
    # The site's globe reports warming as the latest five years against a
    # 1979-2000 reference. Quoting a 1979-1988 baseline instead reads ~0.35 C
    # hotter, purely because 1989-2000 was already warmer, which looks like a
    # contradiction next to the globe. Both are exported; the page quotes the
    # one that matches the tool.
    site_base = [y for y in sorted(yr) if 1979 <= y <= 2000]
    recent5 = [y for y in sorted(yr) if y <= 2025][-5:]
    sb = sum(yr[y] for y in site_base) / len(site_base)
    r5 = sum(yr[y] for y in recent5) / len(recent5)
    return {"first": [first[0], first[-1]], "last": [last[0], last[-1]],
            "delta": round(lm - fm, 2),
            "siteBase": [site_base[0], site_base[-1]],
            "siteRecent": [recent5[0], recent5[-1]],
            "siteDelta": round(r5 - sb, 2)}


def export_json(path: Path) -> None:
    """Everything the published page needs, so its figures come from this code.

    The Next.js page imports this file; nothing in the page is typed in, which
    is the same discipline as the draft. Re-run after any data refresh.
    """
    R = rain_windows()
    E = episodes()
    # Every European country the analysis covers, so the page can offer a
    # selector rather than hard-coding France and Spain.
    story_countries = ["France", "Spain", "Portugal", "Italy", "Germany",
                       "United Kingdom", "Greece", "Netherlands"]
    joint = {c: joint_history(c) for c in story_countries}
    cum = cumulative_daily(story_countries)

    def rank(pts):
        cur = [q for q in pts if q[0] == 2026][0]
        return {"hotter": sum(1 for q in pts if q[1] > cur[1]),
                "drier": sum(1 for q in pts if q[2] < cur[2]),
                "n": len(pts), "anomaly": round(cur[1], 2), "pct": round(cur[2], 1)}

    r3 = lambda x: round(float(x), 3)
    data = {
        "generated": dt.date.today().isoformat(),
        "dataThrough": WET1,
        "dry": [DRY0, DRY1], "wet": [WET0, WET1], "base": list(BASE),
        "europe": sorted(EUR),
        "rain": {n: {"dry": {k: r3(v) for k, v in r["dry"].items()},
                     "wet": {k: r3(v) for k, v in r["wet"].items()},
                     "ratio": r3(r["ratio"])} for n, r in R.items()},
        "days": {r["region"]: r["days"] for r in E["summary"]},
        "daysInDryWindow": days_in_window(E["events"], DRY0, DRY1),
        "episodes": {n: [{"a": e["a"], "b": e["b"], "d": e["d"], "peak": e["peak"]} for e in evs]
                     for n, evs in E["events"].items()},
        "joint": {c: [[y, round(t, 3), round(p, 1)] for y, t, p in pts]
                  for c, pts in joint.items()},
        "ranks": {c: rank(pts) for c, pts in joint.items()},
        "cum": {n: {"obs": [[t, v] for t, v in d["obs"]], "norm": [[t, v] for t, v in d["norm"]]}
                for n, d in cum.items()},
        "monthly": monthly_grid(),
        "warm": [[n, v] for n, v in WARM],
        "europeDecades": europe_decades(),
        "spaghetti": spaghetti_data(story_countries),
        "peaks": peaks_2026(story_countries),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False))
    print(f"wrote {path}  ({path.stat().st_size // 1024} KB)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--json",
        type=Path,
        default=ROOT
        / "web/src/content/stories/summer-2026-heat-and-drought/data.json",
        help="where to write the page's data file",
    )
    args = ap.parse_args()
    export_json(args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
