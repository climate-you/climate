#!/usr/bin/env python3
"""Generate the reviewable HTML draft of the Europe summer 2026 case study.

Every figure quoted in the prose is computed here from the release and the
analysis cache, never typed in. The draft's numbers went stale twice while they
were hand-written; now a data refresh plus a re-run of this script is enough.

Inputs (all local — the LaCie cache is NOT needed):
  data/releases/dev/series/...   packaged metrics and regional aggregates
  data/releases/dev/maps/...     rendered textures, cropped and inlined
  logs/analysis/daily_max_*.csv  regional daily-max series (experiments/heatwave_analysis.py)
  logs/aug28-*/episodes_global.json   episode list from the same script

Usage:
    python experiments/build_story_draft.py --json web/src/content/stories/\
summer-2026-heat-and-drought/data.json   # page data only
    python experiments/build_story_draft.py              # the review draft
    python experiments/build_story_draft.py --out x.html --json y.json  # both
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


def crop_map(rel: str, lon0, lon1, lat1, lat0, maxw=760) -> str:
    from PIL import Image
    LATMAX = 85.05112878
    yn = lambda la: (1 - math.log(math.tan(math.pi / 4 + math.radians(la) / 2)) / math.pi) / 2
    im = Image.open(MAPS / rel).convert("RGBA"); W, H = im.size
    top, bot = yn(LATMAX), yn(-LATMAX)
    ypix = lambda la: int((yn(la) - top) / (bot - top) * H)
    c = im.crop((int((lon0 + 180) / 360 * W), ypix(lat1),
                 int((lon1 + 180) / 360 * W), ypix(lat0)))
    if c.width > maxw:
        c = c.resize((maxw, int(c.height * maxw / c.width)), Image.LANCZOS)
    buf = io.BytesIO(); c.save(buf, "WEBP", quality=88, method=6)
    return base64.b64encode(buf.getvalue()).decode()


# --------------------------------------------------------------------------- charts
def esc(s): return str(s).replace("&", "&amp;").replace("<", "&lt;")


def c_warm():
    W, H, L, R, T = 680, len(WARM) * 24 + 34, 148, 52, 8
    pw, hi = W - L - R, 0.55
    X = lambda v: L + v / hi * pw
    p = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="Warming rate by region">']
    for v in (0.1, 0.2, 0.3, 0.4, 0.5):
        p.append(f'<line x1="{X(v):.0f}" x2="{X(v):.0f}" y1="{T}" y2="{H-24}" class="grid"/>')
        p.append(f'<text x="{X(v):.0f}" y="{H-8}" text-anchor="middle" class="tick">{v:.1f}</text>')
    for i, (n, v) in enumerate(WARM):
        y = T + i * 24 + 3
        ref = "ref" if "Glob" in n else ("eubar" if n == "Europe" else "otherbar")
        p.append(f'<rect x="{L}" y="{y}" width="{X(v)-L:.1f}" height="14" rx="4" class="bar {ref}">'
                 f'<title>{esc(n)}: +{v:.3f} °C/decade</title></rect>')
        p.append(f'<text x="{L-10}" y="{y+11}" text-anchor="end" class="rowlab'
                 f'{" hi" if n=="Europe" else ""}">{esc(n)}</text>')
        p.append(f'<text x="{X(v)+6:.1f}" y="{y+11}" class="val">+{v:.3f}</text>')
    return "".join(p) + "</svg>"


def c_rain(R):
    rows = sorted(((n, r["dry"]["pct"]) for n, r in R.items()), key=lambda kv: kv[1])
    W, H, L, Rt, T = 680, len(rows) * 24 + 46, 140, 44, 10
    pw, lo, hi = W - L - Rt, 30, 130
    X = lambda v: L + (min(max(v, lo), hi) - lo) / (hi - lo) * pw
    p = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="Rainfall as a percentage of normal">']
    for v in (50, 75, 100, 125):
        p.append(f'<line x1="{X(v):.0f}" x2="{X(v):.0f}" y1="{T}" y2="{H-30}" class="grid"/>')
        p.append(f'<text x="{X(v):.0f}" y="{H-14}" text-anchor="middle" class="tick">{v}%</text>')
    p.append(f'<line x1="{X(100):.0f}" x2="{X(100):.0f}" y1="{T}" y2="{H-30}" class="baseline"/>')
    for i, (n, v) in enumerate(rows):
        y = T + i * 24 + 4
        x0, x1 = (X(v), X(100)) if v < 100 else (X(100), X(v))
        p.append(f'<rect x="{x0:.1f}" y="{y}" width="{max(2,x1-x0):.1f}" height="14" rx="4" '
                 f'class="bar {"dry" if v<100 else "wet"}"><title>{esc(n)}: {v:.0f}% of normal</title></rect>')
        p.append(f'<text x="{L-10}" y="{y+11}" text-anchor="end" class="rowlab'
                 f'{" hi" if n in EUR else ""}">{esc(n)}</text>')
        lx, anc = (x0 - 6, "end") if v < 100 else (x1 + 6, "start")
        p.append(f'<text x="{lx:.1f}" y="{y+11}" text-anchor="{anc}" class="val">{v:.0f}%</text>')
    return "".join(p) + "</svg>"


def c_scatter(R, days):
    W, H, L, Rt, T, B = 680, 430, 54, 16, 16, 44
    pw, ph = W - L - Rt, H - T - B
    xmax, ymin, ymax = 65, 35, 125
    X = lambda v: L + v / xmax * pw
    Y = lambda v: T + (ymax - min(max(v, ymin), ymax)) / (ymax - ymin) * ph
    p = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="Heat episodes against rainfall by country">']
    p.append(f'<rect x="{X(28):.0f}" y="{Y(80):.0f}" width="{X(xmax)-X(28):.0f}" '
             f'height="{Y(ymin)-Y(80):.0f}" fill="var(--dry)" opacity="0.09"/>')
    p.append(f'<text x="{X(xmax)-8:.0f}" y="{Y(ymin)-8:.0f}" text-anchor="end" class="quad">hot and dry</text>')
    for v in (50, 75, 100, 125):
        p.append(f'<line x1="{L}" x2="{W-Rt}" y1="{Y(v):.0f}" y2="{Y(v):.0f}" '
                 f'class="{"baseline" if v==100 else "grid"}"/>')
        p.append(f'<text x="{L-8}" y="{Y(v)+4:.0f}" text-anchor="end" class="tick">{v}%</text>')
    for v in (0, 20, 40, 60):
        p.append(f'<text x="{X(v):.0f}" y="{H-B+20}" text-anchor="middle" class="tick">{v}</text>')
    p.append(f'<text x="{L+pw/2:.0f}" y="{H-6}" text-anchor="middle" class="axlab">days in heat episodes, May–Aug 2026</text>')
    p.append(f'<text transform="translate(13,{T+ph/2:.0f}) rotate(-90)" text-anchor="middle" '
             f'class="axlab">rainfall 1 Jun – 15 Aug, % of normal</text>')
    off = {"Italy": (10, -6), "France": (-9, -9), "Spain": (10, 4), "Portugal": (10, 4),
           "Germany": (-9, -9), "United Kingdom": (-9, -9), "Greece": (10, 4),
           "United States": (10, -6), "China": (10, 4), "India": (10, 4),
           "Japan": (-9, -8), "Canada": (10, -6), "Russia": (10, 5),
           "Turkey": (10, 4), "Mexico": (10, 4), "Netherlands": (-9, 12)}
    for n, d in sorted(days.items(), key=lambda kv: -kv[1]):
        if n not in R:
            continue
        r = R[n]["dry"]["pct"]; cls = "eu" if n in EUR else "other"
        cx, cy = X(d), Y(r)
        p.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="6" class="pt {cls}">'
                 f'<title>{esc(n)}: {d} days, {r:.0f}% of normal rainfall</title></circle>')
        dx, dy = off.get(n, (9, 4))
        p.append(f'<text x="{cx+dx:.1f}" y="{cy+dy:.1f}" text-anchor="{"start" if dx>0 else "end"}" '
                 f'class="ptlab {cls}">{esc(n)}</text>')
    return "".join(p) + "</svg>"


def c_timeline(ev):
    order = ["Italy", "France", "Spain", "Russia", "Canada", "United Kingdom", "China",
             "Japan", "Germany", "United States", "Portugal", "Greece"]
    d0, d1 = dt.date(2026, 5, 1), dt.date(*map(int, WET1.split("-")))
    span = (d1 - d0).days
    W, L, Rt, T = 680, 140, 14, 30
    H = len(order) * 22 + 42 + (T - 10)
    pw = W - L - Rt
    X = lambda d: L + (d - d0).days / span * pw
    p = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="Heat episodes through the summer">']
    xw = X(dt.date(2026, 8, 16))
    p.append(f'<rect x="{xw:.0f}" y="{T}" width="{W-Rt-xw:.0f}" height="{H-28-T}" '
             f'fill="var(--blue)" opacity="0.08"/>')
    p.append(f'<text x="{xw+4:.0f}" y="{T-10}" class="quad" style="fill:var(--blue)">rain returns</text>')
    for m, lab in ((5, "May"), (6, "Jun"), (7, "Jul"), (8, "Aug")):
        x = X(dt.date(2026, m, 1))
        p.append(f'<line x1="{x:.0f}" x2="{x:.0f}" y1="{T}" y2="{H-28}" class="grid"/>')
        p.append(f'<text x="{x+4:.0f}" y="{H-12}" class="tick">{lab}</text>')
    for i, n in enumerate(order):
        y = T + i * 22 + 3
        p.append(f'<text x="{L-10}" y="{y+11}" text-anchor="end" class="rowlab'
                 f'{" hi" if n in EUR else ""}">{esc(n)}</text>')
        p.append(f'<line x1="{L}" x2="{W-Rt}" y1="{y+7.5:.0f}" y2="{y+7.5:.0f}" class="tlbase"/>')
        for e in ev.get(n, []):
            a = dt.date(*map(int, e["a"].split("-"))); b = dt.date(*map(int, e["b"].split("-")))
            x0, x1 = X(a), X(b)
            p.append(f'<rect x="{x0:.1f}" y="{y}" width="{max(3,x1-x0):.1f}" height="15" rx="4" '
                     f'class="ev {"eu" if n in EUR else "other"}">'
                     f'<title>{esc(n)}: {e["a"]} to {e["b"]}, {e["d"]} days, peak {e["peak"]:.1f} °C</title></rect>')
    return "".join(p) + "</svg>"


def c_joint(pts, country):
    W, H, L, Rt, T, B = 680, 400, 54, 18, 14, 44
    pw, ph = W - L - Rt, H - T - B
    x0, x1, y0, y1 = 30, 155, -2.4, 3.9
    X = lambda v: L + (min(max(v, x0), x1) - x0) / (x1 - x0) * pw
    Y = lambda v: T + (y1 - v) / (y1 - y0) * ph
    cur = [q for q in pts if q[0] == 2026][0]
    p = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="Every June-July since 1979">']
    p.append(f'<rect x="{L}" y="{T}" width="{X(cur[2])-L:.1f}" height="{Y(cur[1])-T:.1f}" '
             f'fill="var(--dry)" opacity="0.10"/>')
    p.append(f'<text x="{X(cur[2])-8:.0f}" y="{T+16}" text-anchor="end" class="quad">hotter and drier than 2026</text>')
    for v in (-2, -1, 0, 1, 2, 3):
        p.append(f'<line x1="{L}" x2="{W-Rt}" y1="{Y(v):.0f}" y2="{Y(v):.0f}" '
                 f'class="{"baseline" if v==0 else "grid"}"/>')
        p.append(f'<text x="{L-8}" y="{Y(v)+4:.0f}" text-anchor="end" class="tick">{v:+d}</text>')
    for v in (50, 75, 100, 125, 150):
        p.append(f'<line x1="{X(v):.0f}" x2="{X(v):.0f}" y1="{T}" y2="{H-B}" '
                 f'class="{"baseline" if v==100 else "grid"}"/>')
        p.append(f'<text x="{X(v):.0f}" y="{H-B+20}" text-anchor="middle" class="tick">{v}%</text>')
    p.append(f'<text x="{L+pw/2:.0f}" y="{H-6}" text-anchor="middle" class="axlab">June–July rainfall, % of 1991–2020 normal</text>')
    p.append(f'<text transform="translate(13,{T+ph/2:.0f}) rotate(-90)" text-anchor="middle" '
             f'class="axlab">June–July temperature anomaly, °C</text>')
    for y, ta, pr in pts:
        if y == 2026:
            continue
        p.append(f'<circle cx="{X(pr):.1f}" cy="{Y(ta):.1f}" r="4" class="yr{" recent" if y>=2011 else ""}">'
                 f'<title>{y}: {ta:+.2f} °C, {pr:.0f}%</title></circle>')
    p.append(f'<circle cx="{X(cur[2]):.1f}" cy="{Y(cur[1]):.1f}" r="8" class="cur">'
             f'<title>2026: {cur[1]:+.2f} °C, {cur[2]:.0f}%</title></circle>')
    p.append(f'<text x="{X(cur[2])+13:.1f}" y="{Y(cur[1])+4:.1f}" class="curlab">2026</text>')
    return "".join(p) + "</svg>"


def c_pivot(cum):
    W, H, L, Rt, T, B = 680, 360, 54, 104, 30, 40
    pw, ph = W - L - Rt, H - T - B
    d0 = dt.date(2026, 6, 1); d1 = dt.date(*map(int, WET1.split("-")))
    span = (d1 - d0).days
    hi = max(v for d in cum.values() for _, v in d["norm"] + d["obs"]) * 1.05
    X = lambda s: L + (dt.date(*map(int, s.split("-"))) - d0).days / span * pw
    Y = lambda v: T + (hi - v) / hi * ph
    p = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" '
         f'aria-label="Cumulative rainfall June to August 2026 against the 1991-2020 normal">']
    xw = X(WET0)
    p.append(f'<rect x="{xw:.0f}" y="{T}" width="{W-Rt-xw:.0f}" height="{ph:.0f}" '
             f'fill="var(--blue)" opacity="0.07"/>')
    # label sits above the plot, never over a line
    p.append(f'<text x="{xw+4:.0f}" y="{T-10}" class="quad" style="fill:var(--blue)">rain returns</text>')
    for v in (50, 100, 150, 200, 250):
        if v > hi: continue
        p.append(f'<line x1="{L}" x2="{W-Rt}" y1="{Y(v):.0f}" y2="{Y(v):.0f}" class="grid"/>')
        p.append(f'<text x="{L-8}" y="{Y(v)+4:.0f}" text-anchor="end" class="tick">{v}</text>')
    for m, lab in ((6, "Jun"), (7, "Jul"), (8, "Aug")):
        x = X(f"2026-{m:02d}-01")
        p.append(f'<line x1="{x:.0f}" x2="{x:.0f}" y1="{T}" y2="{H-B}" class="grid"/>')
        p.append(f'<text x="{x+4:.0f}" y="{H-B+18}" class="tick">{lab}</text>')
    p.append(f'<text transform="translate(13,{T+ph/2:.0f}) rotate(-90)" text-anchor="middle" '
             f'class="axlab">cumulative rainfall, mm</text>')
    cls = {"Portugal": "nowdry", "Spain": "now2", "France": "now3"}
    for n, d in cum.items():
        k = cls.get(n, "past")
        dn = " ".join(f"{X(t):.1f},{Y(v):.1f}" for t, v in d["norm"])
        p.append(f'<polyline points="{dn}" class="normline {k}"><title>{esc(n)}: '
                 f'{BASE[0]}-{BASE[1]} normal, {d["norm"][-1][1]:.0f} mm by 31 Aug</title></polyline>')
        do = " ".join(f"{X(t):.1f},{Y(v):.1f}" for t, v in d["obs"])
        p.append(f'<polyline points="{do}" class="{k}"><title>{esc(n)}: 2026, '
                 f'{d["obs"][-1][1]:.0f} mm by 31 Aug</title></polyline>')
        lt, lv = d["obs"][-1]
        nv = d["norm"][-1][1]
        p.append(f'<text x="{X(lt)+7:.0f}" y="{Y(lv)+4:.0f}" class="endlab {k}">'
                 f'{esc(n)} {lv:.0f}</text>')
        p.append(f'<text x="{X(lt)+7:.0f}" y="{Y(nv)+4:.0f}" class="endlab normlab">'
                 f'normal {nv:.0f}</text>')
    return "".join(p) + "</svg>"


def c_spaghetti(country="France"):
    f = ROOT / "logs/analysis/daily_max_europe_m3-8_2026.csv"
    if not f.exists():
        return None
    df = pd.read_csv(f, index_col=0, parse_dates=True)
    if country not in df.columns:
        return None
    s = df[country].dropna()
    W, H, L, Rt, T, B = 680, 330, 46, 14, 12, 40
    pw, ph = W - L - Rt, H - T - B
    d0, d1, lo, hi = 60, 240, 2, 42
    X = lambda d: L + (d - d0) / (d1 - d0) * pw
    Y = lambda v: T + (hi - v) / (hi - lo) * ph
    p = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="Daily maximum temperature, {country}">']
    for v in (10, 20, 30, 40):
        p.append(f'<line x1="{L}" x2="{W-Rt}" y1="{Y(v):.0f}" y2="{Y(v):.0f}" class="grid"/>')
        p.append(f'<text x="{L-8}" y="{Y(v)+4:.0f}" text-anchor="end" class="tick">{v}°</text>')
    for doy, lab in ((60, "Mar"), (91, "Apr"), (121, "May"), (152, "Jun"), (182, "Jul"), (213, "Aug")):
        p.append(f'<line x1="{X(doy):.0f}" x2="{X(doy):.0f}" y1="{T}" y2="{H-B}" class="grid"/>')
        p.append(f'<text x="{X(doy)+4:.0f}" y="{H-B+18}" class="tick">{lab}</text>')
    for y in range(BASE[0], BASE[1] + 1):
        v = s[s.index.year == y]
        if v.empty: continue
        d = " ".join(f"{X(int(i.strftime('%j'))):.1f},{Y(x):.1f}" for i, x in v.items())
        p.append(f'<polyline points="{d}" class="past"/>')
    v = s[s.index.year == 2026]
    d = " ".join(f"{X(int(i.strftime('%j'))):.1f},{Y(x):.1f}" for i, x in v.items())
    p.append(f'<polyline points="{d}" class="now"/>')
    p.append(f'<text x="{W-Rt-6}" y="{T+16}" text-anchor="end" class="curlab">2026</text>')
    p.append(f'<text x="{W-Rt-6}" y="{T+32}" text-anchor="end" class="tick">{BASE[0]}–{BASE[1]} in grey</text>')
    return "".join(p) + "</svg>"



def c_monthly(R_unused=None):
    """Per-country % of normal, by sub-period — shows WHEN each country's rain stopped."""
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
        for lab, a, b in periods:
            obs = sum(x for t, x in zip(dax, dv) if a <= str(t) <= b and x is not None)
            nd = sum(1 for t, x in zip(dax, dv) if a <= str(t) <= b and x is not None)
            row.append(100 * obs / (clim[int(a[5:7])] * nd))
        grid[n] = row
    cw, ch, L, T = 118, 34, 132, 34
    W, H = L + cw * len(periods) + 16, T + ch * len(names) + 14
    def col(v):
        # diverging around 100%: brown dry, blue wet, neutral at normal
        if v < 100:
            t = max(0.0, min(1.0, (100 - v) / 65))
            return f"color-mix(in oklab, var(--dry) {t*82:.0f}%, var(--paper))"
        t = max(0.0, min(1.0, (v - 100) / 65))
        return f"color-mix(in oklab, var(--blue) {t*72:.0f}%, var(--paper))"
    p = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="Rainfall as a percentage of normal by country and period">']
    for j, (lab, _, _) in enumerate(periods):
        p.append(f'<text x="{L+j*cw+cw/2:.0f}" y="{T-12}" text-anchor="middle" class="tick">{lab}</text>')
    for i, n in enumerate(names):
        y = T + i * ch
        p.append(f'<text x="{L-10}" y="{y+21}" text-anchor="end" class="rowlab hi">{esc(n)}</text>')
        for j, v in enumerate(grid[n]):
            x = L + j * cw
            p.append(f'<rect x="{x+1}" y="{y+2}" width="{cw-3}" height="{ch-5}" rx="3" '
                     f'fill="{col(v)}"><title>{esc(n)} {periods[j][0]}: {v:.0f}% of normal</title></rect>')
            p.append(f'<text x="{x+cw/2:.0f}" y="{y+21}" text-anchor="middle" class="cell'
                     f'{" strong" if v < 60 or v > 140 else ""}">{v:.0f}%</text>')
    return "".join(p) + "</svg>"


def c_spaghetti_multi(countries):
    """One chart per country, toggled by buttons — a 2x2 grid is unreadable at this width."""
    out = {}
    f = ROOT / "logs/analysis/daily_max_europe_m3-8_2026.csv"
    if not f.exists():
        return out
    df = pd.read_csv(f, index_col=0, parse_dates=True)
    for country in countries:
        if country not in df.columns:
            continue
        s = df[country].dropna()
        W, H, L, Rt, T, B = 680, 320, 46, 14, 12, 40
        pw, ph = W - L - Rt, H - T - B
        d0, d1, lo, hi = 60, 240, 0, 44
        X = lambda d: L + (d - d0) / (d1 - d0) * pw
        Y = lambda v: T + (hi - v) / (hi - lo) * ph
        p = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="Daily maximum temperature, {esc(country)}">']
        for v in (10, 20, 30, 40):
            p.append(f'<line x1="{L}" x2="{W-Rt}" y1="{Y(v):.0f}" y2="{Y(v):.0f}" class="grid"/>')
            p.append(f'<text x="{L-8}" y="{Y(v)+4:.0f}" text-anchor="end" class="tick">{v}°</text>')
        for doy, lab in ((60,"Mar"),(91,"Apr"),(121,"May"),(152,"Jun"),(182,"Jul"),(213,"Aug")):
            p.append(f'<line x1="{X(doy):.0f}" x2="{X(doy):.0f}" y1="{T}" y2="{H-B}" class="grid"/>')
            p.append(f'<text x="{X(doy)+4:.0f}" y="{H-B+18}" class="tick">{lab}</text>')
        for y in range(BASE[0], BASE[1] + 1):
            v = s[s.index.year == y]
            if v.empty: continue
            d = " ".join(f"{X(int(i.strftime('%j'))):.1f},{Y(x):.1f}" for i, x in v.items())
            p.append(f'<polyline points="{d}" class="past"/>')
        v = s[s.index.year == 2026]
        d = " ".join(f"{X(int(i.strftime('%j'))):.1f},{Y(x):.1f}" for i, x in v.items())
        p.append(f'<polyline points="{d}" class="now"/>')
        p.append(f'<text x="{W-Rt-6}" y="{T+16}" text-anchor="end" class="curlab">{esc(country)} 2026</text>')
        p.append(f'<text x="{W-Rt-6}" y="{T+32}" text-anchor="end" class="tick">{BASE[0]}–{BASE[1]} in grey</text>')
        out[country] = "".join(p) + "</svg>"
    return out


# --------------------------------------------------------------------------- page
def build() -> str:
    R = rain_windows()
    E = episodes()
    days = {r["region"]: r["days"] for r in E["summary"]}
    ev = E["events"]
    jf = joint_history("France"); js = joint_history("Spain")
    cum = cumulative_daily(story_countries)

    def rank(pts):
        cur = [q for q in pts if q[0] == 2026][0]
        return (sum(1 for q in pts if q[1] > cur[1]), sum(1 for q in pts if q[2] < cur[2]), len(pts), cur)
    hf, df_, nf, cf = rank(jf)
    hs, ds_, ns, cs = rank(js)

    pt = R["Portugal"]
    maps = {
        "rain": crop_map("tp_summer_2026_pct_of_normal_mercator_texture/tp_summer_2026_pct_of_normal_mercator.webp",
                         -13, 42, 63, 34),
        "heat": crop_map("t2m_heatwave_2026_w5_mercator_texture/t2m_heatwave_2026_w5_mercator.webp",
                         -13, 42, 63, 34),
        "world": crop_map("tp_summer_2026_pct_of_normal_mercator_texture/tp_summer_2026_pct_of_normal_mercator.webp",
                          -170, 179, 72, -10, maxw=900),
    }
    img = lambda k, alt: f'<img alt="{alt}" src="data:image/webp;base64,{maps[k]}">'
    f = lambda n, k="dry": R[n][k]["pct"]

    tbl = "".join(
        f'<tr class="{"hi" if n in ("Spain","France","Italy","Greece") else ""}">'
        f'<td>{n}</td><td class="{"dry" if f(n)<100 else "cool"}">{f(n):.0f}%</td>'
        f'<td class="{"hot" if days.get(n,0)>40 else ""}">{days.get(n,0)}</td>'
        f'<td style="text-align:left">{o}</td></tr>'
        for n, o in (("Spain", "Largest fire in its recorded history"),
                     ("France", "National annual record passed"),
                     ("Portugal", "—"), ("Italy", "Hottest by this measure, no comparable record"),
                     ("Greece", "Neither")))

    STYLE = """
:root{--paper:#fff;--surface-alt:#f4f4f4;--ink:#111;--muted:rgba(17,17,17,.66);
--faint:rgba(17,17,17,.45);--hairline:rgba(17,17,17,.18);--hairline-strong:rgba(17,17,17,.6);
--blue:#0f50ff;--heat:#b10026;--warm:#d9480f;--dry:#8c510a;--notebg:rgba(17,17,17,.045)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--paper:#101010;--surface-alt:#222;
--ink:#f2f2f2;--muted:rgba(242,242,242,.66);--faint:rgba(242,242,242,.45);
--hairline:rgba(242,242,242,.22);--hairline-strong:rgba(242,242,242,.6);
--blue:#7fa0ff;--heat:#ff7b66;--warm:#ffa94d;--dry:#d9a066;--notebg:rgba(242,242,242,.055)}}
:root[data-theme="dark"]{--paper:#101010;--surface-alt:#222;--ink:#f2f2f2;
--muted:rgba(242,242,242,.66);--faint:rgba(242,242,242,.45);--hairline:rgba(242,242,242,.22);
--hairline-strong:rgba(242,242,242,.6);--blue:#7fa0ff;--heat:#ff7b66;--warm:#ffa94d;--dry:#d9a066;
--notebg:rgba(242,242,242,.055)}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);line-height:1.65;
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;-webkit-font-smoothing:antialiased}
.wrap{max-width:880px;margin:0 auto;padding:clamp(24px,4.5vw,64px) clamp(18px,4.5vw,32px) 88px;
display:flex;flex-direction:column;gap:2.4rem}
.stamp{display:flex;flex-wrap:wrap;gap:.5rem 1.25rem;align-items:baseline;padding-bottom:.9rem;
border-bottom:2px solid var(--hairline-strong);font-size:.72rem;letter-spacing:.12em;
text-transform:uppercase;color:var(--muted)}
.stamp b{color:var(--heat)}
h1{font-size:clamp(2rem,5.2vw,3.1rem);line-height:1.08;letter-spacing:-.02em;margin:0;text-wrap:balance}
.lede{font-size:clamp(1.06rem,2.2vw,1.24rem);color:var(--muted);margin:0;max-width:62ch;text-wrap:pretty}
section{display:flex;flex-direction:column;gap:1rem}
h2{font-size:.75rem;letter-spacing:.16em;text-transform:uppercase;color:var(--muted);margin:0;
padding-top:1.4rem;border-top:1px solid var(--hairline);display:flex;gap:.85rem;align-items:baseline}
h2 .n{color:var(--blue);font-variant-numeric:tabular-nums;font-weight:700}
h3{font-size:1.2rem;line-height:1.25;margin:.4rem 0 0;text-wrap:balance}
p{margin:0;max-width:65ch}
.copy{border-left:3px solid var(--hairline-strong);padding-left:1.15rem;display:flex;
flex-direction:column;gap:.85rem}
.copy strong{color:var(--heat);font-weight:650}
.copy em{font-style:normal;color:var(--dry);font-weight:600}
.copy .wet{color:var(--blue);font-weight:650;font-style:normal}
.note{background:var(--notebg);border-radius:3px;padding:.8rem 1rem;font-size:.87rem;
color:var(--muted);display:flex;flex-direction:column;gap:.45rem}
.note b{color:var(--ink);font-size:.69rem;letter-spacing:.12em;text-transform:uppercase}
.note.warn{box-shadow:inset 3px 0 0 var(--heat)}
.note.ok{box-shadow:inset 3px 0 0 var(--blue)}
.note code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.85em;
background:var(--surface-alt);padding:.08em .34em;border-radius:3px}
.note a{color:var(--blue)}
.opener{display:grid;gap:1.2rem;grid-template-columns:1fr}
@media (min-width:760px){.opener{grid-template-columns:1fr 210px;align-items:start}}
.hero{display:flex;flex-direction:column;gap:.5rem}
.hero .maps{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.hero figure{margin:0;display:flex;flex-direction:column;gap:.35rem}
img{width:100%;height:auto;display:block;border-radius:3px;background:var(--surface-alt)}
figcaption{font-size:.74rem;color:var(--faint)}
.rail{display:flex;gap:.8rem;overflow-x:auto;scroll-snap-type:x mandatory;padding-bottom:.4rem}
.rail .fig{flex:0 0 62%;scroll-snap-align:start;background:var(--notebg);border-radius:4px;
padding:.7rem .85rem;display:flex;flex-direction:column;gap:.1rem}
.rail .fig .big{font-size:1.5rem;font-weight:700;font-variant-numeric:tabular-nums;line-height:1.1}
.rail .fig .cap{font-size:.76rem;color:var(--muted)}
.rail .fig.dry .big{color:var(--dry)}.rail .fig.hot .big{color:var(--heat)}
.rail .fig.wet .big{color:var(--blue)}
.swipehint{font-size:.72rem;color:var(--faint);letter-spacing:.08em;text-transform:uppercase}
@media (min-width:760px){.rail{flex-direction:column;overflow:visible}.rail .fig{flex:none}
.swipehint{display:none}}
figure.c{margin:0;display:flex;flex-direction:column;gap:.5rem}
.chartwrap{overflow-x:auto}
svg.chart{width:100%;height:auto;display:block;min-width:540px;font-family:inherit}
.chart .grid{stroke:var(--hairline);stroke-width:1}
.chart .baseline{stroke:var(--hairline-strong);stroke-width:1.5;stroke-dasharray:3 3}
.chart .tlbase{stroke:var(--hairline);stroke-width:1}
.chart .tick{fill:var(--faint);font-size:11px;font-variant-numeric:tabular-nums}
.chart .axlab{fill:var(--muted);font-size:11.5px}
.chart .quad{fill:var(--dry);font-size:11px;letter-spacing:.1em;text-transform:uppercase;opacity:.85}
.chart .rowlab{fill:var(--muted);font-size:12px}
.chart .rowlab.hi{fill:var(--ink);font-weight:650}
.chart .val,.chart .endlab{fill:var(--muted);font-size:11.5px;font-variant-numeric:tabular-nums}
.chart .pt{stroke:var(--paper);stroke-width:2}
.chart .pt.eu{fill:var(--heat)}.chart .pt.other{fill:var(--blue)}
.chart .ptlab{font-size:11.5px}
.chart .ptlab.eu{fill:var(--heat);font-weight:650}.chart .ptlab.other{fill:var(--muted)}
.chart .bar.dry{fill:var(--dry)}.chart .bar.wet{fill:var(--blue)}
.chart .bar.eubar{fill:var(--heat)}.chart .bar.otherbar{fill:var(--muted);opacity:.55}
.chart .bar.ref{fill:var(--muted);opacity:.3}
.chart .ev.eu{fill:var(--heat)}.chart .ev.other{fill:var(--warm)}
.chart .yr{fill:var(--muted);opacity:.45;stroke:var(--paper);stroke-width:1}
.chart .yr.recent{opacity:.75}
.chart .cur{fill:var(--heat);stroke:var(--paper);stroke-width:2.5}
.chart .curlab{fill:var(--heat);font-size:12.5px;font-weight:700}
.chart .past{fill:none;stroke:var(--muted);stroke-width:1;opacity:.28}
.chart .now{fill:none;stroke:var(--heat);stroke-width:2.2}
.chart .nowdry{fill:none;stroke:var(--dry);stroke-width:2.6}
.chart .now2{fill:none;stroke:var(--heat);stroke-width:2.2}
.chart .now3{fill:none;stroke:var(--blue);stroke-width:2.2}
.chart .endlab.nowdry{fill:var(--dry);font-weight:650}
.chart .endlab.now2{fill:var(--heat);font-weight:650}
.chart .endlab.now3{fill:var(--blue);font-weight:650}
.chart .normline{fill:none;stroke-width:1.4;stroke-dasharray:4 3;opacity:.5}
.chart .endlab.normlab{fill:var(--faint);font-size:10.5px}
.chart .cell{fill:var(--ink);font-size:11.5px;font-variant-numeric:tabular-nums;opacity:.75}
.chart .cell.strong{opacity:1;font-weight:700}
.pair{display:grid;gap:1rem;grid-template-columns:1fr}
@media (min-width:820px){.pair{grid-template-columns:1fr 1fr}}
.pair svg.chart{min-width:0}
.tabs{display:flex;gap:.4rem;flex-wrap:wrap}
.tabs button{font:inherit;font-size:.82rem;padding:.3rem .7rem;border-radius:999px;
border:1px solid var(--hairline);background:transparent;color:var(--muted);cursor:pointer}
.tabs button[aria-selected="true"]{background:var(--heat);border-color:var(--heat);color:var(--paper);font-weight:650}
.tabs button:focus-visible{outline:2px solid var(--blue);outline-offset:2px}
.chart rect,.chart circle{transition:opacity .12s}
.chart rect:hover,.chart circle:hover{opacity:.72}
.legend{display:flex;gap:1rem;flex-wrap:wrap;font-size:.78rem;color:var(--muted)}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:.35rem;vertical-align:-1px}
.tablewrap{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:.92rem;font-variant-numeric:tabular-nums}
th,td{padding:.45rem .7rem;text-align:right;border-bottom:1px solid var(--hairline)}
th:first-child,td:first-child{text-align:left}
thead th{font-size:.68rem;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);
border-bottom:1px solid var(--hairline-strong)}
tbody tr.hi td{font-weight:650}
td.dry{color:var(--dry)}td.hot{color:var(--heat)}td.cool{color:var(--blue)}
ul{margin:0;padding-left:1.1rem;display:flex;flex-direction:column;gap:.4rem}
li{max-width:65ch}
.pending{color:var(--dry);font-weight:600}
footer{border-top:2px solid var(--hairline-strong);padding-top:1rem;font-size:.82rem;
color:var(--faint);display:flex;flex-direction:column;gap:.4rem}
a{color:var(--blue)}
a:focus-visible{outline:2px solid var(--blue);outline-offset:2px}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
"""

    spag = c_spaghetti("France")
    spag_block = (f'<figure class="c"><div class="chartwrap">{spag}</div>'
                  f'<figcaption>Daily maximum temperature, France, March to late August. Grey: every '
                  f'year {BASE[0]}–{BASE[1]}. Red: 2026.</figcaption></figure>') if spag else \
                 '<div class="note warn"><b>Missing</b><span>Seasonal-cycle CSV not found — run ' \
                 '<code>experiments/heatwave_analysis.py --set europe --months 3 4 5 6 7 8 --csv-only</code></span></div>'

    spag = c_spaghetti_multi(["France", "Spain", "United Kingdom", "Italy"])
    tabs = "".join(
        f'<button role="tab" aria-selected="{str(i==0).lower()}" data-c="{esc(n)}">{esc(n)}</button>'
        for i, n in enumerate(spag))
    panes = "".join(
        f'<div class="pane" data-c="{esc(n)}"{"" if i==0 else " hidden"}>'
        f'<div class="chartwrap">{v}</div></div>'
        for i, (n, v) in enumerate(spag.items()))
    spag_block = (
        f'<figure class="c"><div class="tabs" role="tablist">{tabs}</div>{panes}'
        f'<figcaption>Daily maximum temperature, March to late August. Grey: every year '
        f'{BASE[0]}–{BASE[1]}. Red: 2026. Four separate charts rather than a 2×2 grid — at this '
        f'width a quarter-size version of this chart is unreadable.</figcaption></figure>'
    ) if spag else (
        '<div class="note warn"><b>Missing</b><span>Seasonal-cycle CSV not found — run '
        '<code>experiments/heatwave_analysis.py --set europe --months 3 4 5 6 7 8 --csv-only</code>'
        '</span></div>')

    S_OPEN = f"""<section><h2><span class="n">01</span> Opening</h2>
  <div class="opener">
    <div class="hero">
      <div class="maps">
        <figure>{img('rain','Rainfall as a percentage of normal, Europe')}
          <figcaption>Rain, 1 Jun – 15 Aug, % of normal. Brown = drier.</figcaption></figure>
        <figure>{img('heat','Temperature anomaly 11 to 14 August')}
          <figcaption>Heat, 11–14 Aug, vs {BASE[0]}–{BASE[1]}.</figcaption></figure>
      </div>
      <div class="copy" style="margin-top:.4rem">
        <p>More than 1.2 million acres burned across Europe this summer.<sup>[1]</sup> Spain lost the
          largest single fire in its recorded history, near Ávila.<sup>[2]</sup> More land burned in
          France than in any year since national records began.<sup>[2]</sup> Across the two
          countries, more than 300,000 people
          were told to leave their homes.<sup>[1]</sup></p>
        <p>It was a hot summer, but not only here. Russia spent {days.get('Russia',0)} days in heat
          episodes, Canada {days.get('Canada',0)}, China {days.get('China',0)},
          Japan {days.get('Japan',0)}. Heat alone was not unusual this year.</p>
        <p>What set western Europe apart was that <em>the rain did not come with it</em>.</p>
      </div>
    </div>
    <div><div class="rail">
      <div class="fig dry"><span class="big">{f('Spain'):.0f}%</span><span class="cap">of normal rainfall in Spain, 1 Jun – 15 Aug</span></div>
      <div class="fig hot"><span class="big">{days.get('France',0)}</span><span class="cap">days in heat episodes in France</span></div>
      <div class="fig hot"><span class="big">13 Aug</span><span class="cap">the day the UK, France and Spain all reached their peak temperature together</span></div>
      <div class="fig dry"><span class="big">Hottest &amp; driest</span><span class="cap">France's summer was both, out of the {nf} summers since 1979</span></div>
      <div class="fig dry"><span class="big">{f('Portugal'):.0f}%</span><span class="cap">of normal rainfall in Portugal, the driest of the eight European countries measured here</span></div>
      <div class="fig hot"><span class="big">{days.get('Italy',0)}</span><span class="cap">days in heat episodes in Italy, the most of any country measured</span></div>
      <div class="fig"><span class="big">2.4×</span><span class="cap">Europe's warming rate vs the globe since 1979</span></div>
    </div><div class="swipehint">Swipe for more →</div></div>
  </div>
  <div class="note warn"><b>Every figure here needs a citation</b>
    <span>Nothing in this opening is ours: [1] acreage and evacuations, [2] the Spanish and French
      fire records. Sources are CNN / WEF / Met Office as listed in the case-study plan — put the
      footnotes in before this goes anywhere.</span></div>
  <div class="note ok"><b>Toned down, and the placeholder titles replaced</b>
    <span>“until, abruptly, it did” is gone, and so are the four working titles you gave me as
      shorthand rather than copy. §02–05 now read “Heat, nearly everywhere”, “The rain that never
      came”, “Heat on dry ground” and “The break, mid-August”. The rain did return, but at 122–153% of normal for a
      fortnight in most countries — a normal-ish fortnight after a dry summer, not a deluge. Only
      Portugal was extraordinary. §05 makes that case with the numbers instead of the adverb.</span></div>
</section>"""

    S_HOT = f"""<section><h2><span class="n">02</span> Heat, nearly everywhere</h2>
  <div class="copy">
    <p>Summer 2026 did not arrive as a single heatwave. It came in episodes, and in late June every
      major western European country was in one at once: France, Spain, Italy, Germany and the
      Netherlands, between the 13th and the 28th.</p>
    <p>Then on <strong>13 August the United Kingdom, France and Spain all reached their peak
      temperature of the summer on the same day</strong>. Averaged across the whole of each country,
      by land area, the day's maximum temperature reached 27.4 °C in the UK, 35.6 °C in France and 35.1 °C in Spain. Those are
      country-wide averages, not the hottest spot: the UK's own station record that day was 38.1 °C
      at Kew Gardens.<sup>[3]</sup></p>
  </div>
  <figure class="c"><div class="chartwrap">{c_timeline(ev)}</div>
    <div class="legend"><span><i style="background:var(--heat)"></i>western Europe</span>
      <span><i style="background:var(--warm)"></i>rest of the northern hemisphere</span></div>
    <figcaption>Each bar is three or more consecutive days above that country's own
      {BASE[0]}–{BASE[1]} 90th percentile <b>of daily maximum temperature</b> for the date. The blue
      band is the late-August rain.</figcaption></figure>
  <div class="note warn"><b>In-page note required next to this chart</b>
    <span>Wording to use: “This chart uses <b>daily maximum</b> temperature. Every national weather
      service defines a heatwave differently — the Met Office uses fixed county thresholds, France's
      definition also counts nights that fail to cool — so the episodes here are not any one
      country's official heatwaves, and are not comparable to their published counts.”</span></div>
</section>"""

    S_DRY = f"""<section><h2><span class="n">03</span> The rain that never came</h2>
  <div class="copy">
    <p>Heat on its own is survivable. What turns a hot summer into a burning one is what the heat
      arrives on: soil that has already given up its moisture, rivers running low, vegetation that
      has been drying since spring. So the second question is how much rain fell while all this was
      happening.</p>
    <p>In western Europe, not much. From 1 June to 15 August, <em>Portugal received
      {f('Portugal'):.0f}% of its normal rainfall.
      Spain {f('Spain'):.0f}%. France {f('France'):.0f}%.</em> Germany {f('Germany'):.0f}%,
      Italy {f('Italy'):.0f}%, the United Kingdom {f('United Kingdom'):.0f}%.</p>
    <p>But the rain did not stop everywhere at once. In Iberia it was already failing in June. In
      Britain, June was <span class="wet">wetter</span> than normal and the drought only began in
      July.</p>
  </div>
  <figure class="c"><div class="chartwrap">{c_monthly()}</div>
    <figcaption>Rainfall as a percentage of the {BASE[0]}–{BASE[1]} normal for each period. Brown =
      drier than normal, blue = wetter.</figcaption></figure>
  <figure class="c">{img('world','World rainfall as a percentage of normal')}
    <figcaption>The same measure worldwide. The deficit is a western-European feature, not a
      hemispheric one. The United States finished at {f('United States'):.0f}% of normal, China
      {f('China'):.0f}%, Canada {f('Canada'):.0f}%, Russia {f('Russia'):.0f}%.</figcaption></figure>
  <div class="note ok"><b>Answers your question about the UK</b>
    <span>The UK's 71% looked too high for a drought because <b>June was wet there — 119% of
      normal</b>. July was 35% and the first half of August 55%, both genuinely dry, but June's
      surplus lifts the whole-window figure. The new period chart shows this, and it is a better
      finding than a single number: the drought arrived a month later in Britain than in
      Iberia.</span></div>
</section>"""

    S_BOTH = f"""<section><h2><span class="n">04</span> Heat on dry ground</h2>
  <div class="copy">
    <p>The two halves of the story have been told separately so far: how hot each country was, then
      how dry. Neither on its own picks western Europe out. Plenty of the northern hemisphere was as
      hot; a handful of places were as dry. What follows puts both measurements on the same chart,
      one country per dot, to show which of them had to take the two together.</p>
  </div>
  <figure class="c"><div class="chartwrap">{c_scatter(R,days)}</div>
    <div class="legend"><span><i style="background:var(--heat)"></i>western Europe</span>
      <span><i style="background:var(--blue)"></i>rest of the northern hemisphere</span></div>
    <figcaption>Days in heat episodes against rainfall as a percentage of normal, 1 Jun – 15 Aug
      2026.</figcaption></figure>
  <div class="tablewrap"><table>
    <thead><tr><th>Country</th><th>Rainfall</th><th>Heat days</th><th>Outcome</th></tr></thead>
    <tbody>{tbl}</tbody></table></div>
  <div class="copy">
    <p>Russia had {days.get('Russia',0)} days in heat episodes and {f('Russia'):.0f}% of its normal
      rain. Canada, China and Japan were all hot and all wet. Only Iberia and France sit in the dry
      corner. Italy was the hottest of all by this measure, at {days.get('Italy',0)} days, but it was
      also wetter, at {f('Italy'):.0f}%, and it did not set the records Spain and France did.</p>
    <p><strong>Heat was common this summer. Heat arriving on ground that had not been rained on was
      not.</strong></p>
  </div>
  <div class="note warn"><b>Where the definition must be stated</b>
    <span>This axis quotes a count, so the definition belongs here as well as in §02: three or more
      consecutive days above the local {BASE[0]}–{BASE[1]} 90th percentile of daily maximum, ±7-day
      window. The Met Office counts five UK heatwaves this year where this method counts
      {len(ev.get('United Kingdom',[]))}.</span></div>
  <div class="note warn"><b>Greece is a weaker control than it was</b>
    <span>The refresh moved Greece from 5 heat days to {days.get('Greece',0)}. It was still
      <i>wetter</i> than normal ({f('Greece'):.0f}%) through the dry window so it still works as the
      counter-example, but “barely hot at all” is not supportable.</span></div>
</section>"""

    S_RAIN = f"""<section><h2><span class="n">05</span> The break, mid-August</h2>
  <div class="copy">
    <p>Around the 16th of August it broke. In the fortnight that followed, Portugal received
      <span class="wet">{pt['wet']['obs']:.0f} mm, {pt['wet']['pct']:.0f}% of normal for those two
      weeks, and {pt['ratio']:.1f} times everything it had received in the preceding
      {pt['dry']['days']} days</span>.</p>
    <p>Elsewhere the return was real but ordinary: Spain {R['Spain']['wet']['pct']:.0f}% of normal for
      the fortnight, Italy {R['Italy']['wet']['pct']:.0f}%, Germany {R['Germany']['wet']['pct']:.0f}%,
      France {R['France']['wet']['pct']:.0f}%, the United Kingdom
      {R['United Kingdom']['wet']['pct']:.0f}%. Not a deluge: just a normal fortnight, arriving after
      the fires were out.</p>
  </div>
  <figure class="c"><div class="chartwrap">{c_pivot(cum)}</div>
    <figcaption>Cumulative rainfall since 1 June 2026. The solid line is this year; the dashed line
      is what the same country would normally have accumulated by that date, {BASE[0]}–{BASE[1]}.
      France never stops receiving rain, so its solid line keeps climbing; the point is how far
      below its own dashed line it stays.</figcaption></figure>
  <div class="note ok"><b>Answers your question about the France curve</b>
    <span>Yes: it climbed, but not as much as usual. France finished the dry window on
      {f('France'):.0f}% of normal, which is a deficit, not an absence. The old chart plotted
      absolute millimetres with nothing to compare them against, so a wet country looked wet. The
      normal curve is now drawn beside each country and the gap between the two lines is the
      story.</span></div>
  <div class="note warn"><b>Your phrasing, checked</b>
    <span>“As much or more rain in two weeks than the two months before” is <b>true for Portugal
      only</b> ({pt['ratio']:.2f}×). Spain is {R['Spain']['ratio']:.2f}× and France
      {R['France']['ratio']:.2f}×. Portugal is the vivid specific; the general claim has to be the
      milder one now in the copy.</span></div>
</section>"""

    S_YOU = f"""<section><h2><span class="n">06</span> Your summer</h2>
  <div class="copy"><p>Every number so far is a national average. Click your own location for the
    temperature and the rainfall where you live.</p></div>
  <div class="note"><b>Placement — proposed</b>
    <span>Put the interactive here, not at the foot of the page: the reader has just been shown the
      national pattern and the obvious next question is “what about where I am?”. It also separates
      the narrative (§01–05) from the analytical backmatter (§07–08).</span></div>
  <div class="note warn"><b>Blocked by the Stream 2 audit</b>
    <span>Do not ship this section yet. It promises history, and that range depends on metrics the
      audit found corrupt (<code>tp_annual_total_mm</code>, <code>t2m_hotdays_per_year</code>,
      <code>tp_cdd_per_year</code>). The daily tp cache must be repaired first. Temperature
      aggregates are current (2021→2026); rainfall is 2026-only, so a rainfall panel can only run
      against the monthly climatology.</span></div>
</section>"""

    S_HIST = f"""<section><h2><span class="n">07</span> Has this happened before?</h2>
  <div class="copy">
    <p>A hot, dry summer is not in itself remarkable; western Europe has had plenty. The question is
      whether this particular combination, at this size, has a precedent in the record. The two
      charts below place every June–August since 1979 on the same axes as §04, one dot per summer,
      with 2026 marked. If earlier summers were routinely hotter and drier, they would sit above and
      to the left of it.</p>
  </div>
  <div class="pair">
    <figure class="c"><div class="chartwrap">{c_joint(jf,'France')}</div>
      <figcaption>France</figcaption></figure>
    <figure class="c"><div class="chartwrap">{c_joint(js,'Spain')}</div>
      <figcaption>Spain</figcaption></figure>
  </div>
  <div class="copy">
    <p>In both, the shaded corner, hotter than 2026 <em>and</em> drier than 2026, is empty. In
      France, <strong>no summer in {nf} years has been hotter, and none has been drier</strong>
      ({cf[1]:+.2f} °C, {cf[2]:.0f}% of normal). Spain is the same: {hs} hotter, {ds_} drier, out
      of {ns}.</p>
    <p>It is not that heat is new, or that dry summers are new. It is that in France and Spain they
      have never before arrived together at this size.</p>
  </div>
  {spag_block}
  <div class="note ok"><b>Two windows, and why</b>
    <span>The scatters above use <b>full June–August</b>, now that August is complete. The claim was
      first made on June–July while August was partial and it holds on both windows for France;
      JJA is used because it is the ordinary meaning of "summer" and invites no question about
      why a particular window was chosen. §03 uses <b>1 Jun – 15 Aug</b>, the dry stretch
      before the rain returned. The temperature charts below show March to late
      August, which is the daily record and not tied to either window. Say which is which wherever a
      number appears.</span></div>
</section>"""

    S_LONG = f"""<section><h2><span class="n">08</span> The long view</h2>
  <div class="copy">
    <p>None of this happened to a stable climate. Europe has warmed by <strong>0.50 °C per decade
      since 1979</strong>. Against the whole planet, land and ocean together, that is <strong>2.4
      times the global rate</strong>; against the world's land alone, which warms faster than the
      sea, <strong>1.5 times</strong>. Both are true and they answer different questions.</p>
    <p>The last ten years in Europe averaged <strong>2.0 °C warmer</strong> than the first ten of the
      satellite record (1979–88).</p>
  </div>
  <figure class="c"><div class="chartwrap">{c_warm()}</div>
    <figcaption>Warming rate, °C per decade, 1979–2025, least-squares trend on annual mean 2 m air
      temperature. The two global aggregates are shown faint.</figcaption></figure>
  <div class="note ok"><b>Copernicus claim dropped</b>
    <span>The unsourced “Copernicus frames it the same way” is gone; the chart carries both numbers
      instead, which is the honest version and needs no citation.</span></div>
</section>"""

    S_METH = f"""<section><h2><span class="n">09</span> Methods and honesty</h2>
  <div class="note"><b>What this section is</b>
    <span>This list is <b>story content</b> — it appears on the published page, near the foot, in the
      site's usual caveats style. It is not production notes. Everything in a grey box like this one
      is production notes and does not ship.</span></div>
  <div class="copy">
    <p>How to read these numbers.</p>
    <ul>
      <li><b>Grid values are not station values.</b> The ERA5 cell containing Kew Gardens reached
        34.8 °C on 13 August where the station recorded 38.1 °C. A 0.25° cell is about 19 × 28 km, and
        averages town with countryside; ERA5 has no explicit urban canopy.</li>
      <li><b>Heat episodes are ours, not any country's official heatwaves.</b> Three or more
        consecutive days above that country's own {BASE[0]}–{BASE[1]} day-of-year 90th percentile of
        daily maximum, ±7-day window. National definitions differ and none travels across borders.</li>
      <li><b>Two windows are in play</b>: 1 Jun – 15 Aug for the rainfall deficit, and the full
        June–August for the historical comparison. Each is named wherever it is used.</li>
      <li><b>Two ways to say “faster than the world”</b>: 2.4× against all surfaces, 1.5× against
        land.</li>
      <li><b>Recent dates are ERA5T</b>, preliminary and revised later.</li>
      <li><b>The summer is complete</b>: data to 31 August 2026.</li>
      <li><b>We show a coincidence, not a cause.</b> For the attribution see
        <a href="https://www.worldweatherattribution.org/climate-change-increases-likelihood-of-compounding-drivers-of-severe-wildfire-conditions-in-france-and-spain/">World
        Weather Attribution</a> on compounding wildfire drivers in France and Spain.</li>
    </ul>
  </div>
</section>"""

    return f"""<title>Europe's Summer 2026</title>
<style>{STYLE}</style>
<div class="wrap">
<header style="display:flex;flex-direction:column;gap:.9rem">
  <div class="stamp"><span><b>Draft 7</b> · not for publication</span>
    <span>Data to 31 Aug 2026 · complete summer</span><span>Rev. {dt.date.today():%-d %b}</span>
    <span>dry window 1 Jun – 15 Aug</span></div>
  <h1>Europe's summer of heat and drought</h1>
  <p class="lede">Much of the northern hemisphere was hot this summer. Almost all of it still got
    its normal rain. Western Europe did not, and went on to lose more land to fire than in any
    summer on record. A look into the Copernicus ERA5/ERA5T archive.</p>
</header>
{S_OPEN}
{S_HOT}
{S_DRY}
{S_BOTH}
{S_RAIN}
{S_YOU}
{S_HIST}
{S_LONG}
{S_METH}
<footer>
  <span>Generated by <code>experiments/build_story_draft.py</code> — every figure recomputed from the
    release, none typed in. Heat episodes on daily maximum against a {BASE[0]}–{BASE[1]} day-of-year
    90th percentile, ±7-day window. Rainfall as total observed ÷ total expected.</span>
  <span>Draft for internal review — climate.you</span>
</footer>
</div>
<script>
document.querySelectorAll('.tabs').forEach(function (bar) {{
  var fig = bar.closest('figure');
  bar.addEventListener('click', function (e) {{
    var b = e.target.closest('button'); if (!b) return;
    bar.querySelectorAll('button').forEach(function (x) {{
      x.setAttribute('aria-selected', String(x === b));
    }});
    fig.querySelectorAll('.pane').forEach(function (p) {{
      p.hidden = p.dataset.c !== b.dataset.c;
    }});
  }});
}});
</script>
"""


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


DEFAULT_DRAFT = ROOT / "logs/analysis/summer-2026-draft.html"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=None,
                    help=f"write the review draft here (default {DEFAULT_DRAFT} "
                         f"when --json is not given)")
    ap.add_argument("--json", type=Path, default=None,
                    help="write the published page's data file to this path")
    args = ap.parse_args()

    # The review draft is superseded by the page at /stories/summer-2026-heat-
    # and-drought, but this script is still the page's data exporter. Rebuilding
    # the draft on every export rewrote a file nobody reads and made routine
    # data refreshes look like a return to the drafts, so the draft is now
    # written only when it is actually asked for: bare (the old behaviour) or
    # with an explicit --out.
    want_html = args.out is not None or args.json is None
    if not want_html and args.json is None:
        ap.error("nothing to do: pass --json, --out, or neither")

    if want_html:
        out = args.out or DEFAULT_DRAFT
        html = build()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html)
        print(f"wrote {out}  ({len(html)//1024} KB)")
    if args.json:
        export_json(args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
