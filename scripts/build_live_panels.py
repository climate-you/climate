from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import json

import xarray as xr  # only for StoryContext typing; ds not used for these panels

from climate.models import StoryContext, StoryFacts  # :contentReference[oaicite:1]{index=1}
from climate.export.web_paths import live_slug_dir, panel_paths
from climate.export.web_write import write_plotly_svg, write_text, write_json
from climate.export.captions import normalize_caption

# Live panels live in zoomout.py in your prototype :contentReference[oaicite:2]{index=2}
from climate.panels.zoomout import (
    build_last_week_data,
    build_last_week_figure,
    last_week_caption,
    build_last_month_data,
    build_last_month_figure,
    last_month_caption,
)

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cities-index", default="web/public/data/cities_index.json")
    ap.add_argument("--out", default="web/public/data/live")
    ap.add_argument("--asof", default=None, help="YYYY-MM-DD; interpreted as 'data through end of that day'. Default=yesterday.")
    ap.add_argument("--slugs", default=None, help="Comma-separated slugs")
    ap.add_argument("--slugs-file", default=None, help="Text file with one slug per line")
    return ap.parse_args()

def load_cities_index(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))

def choose_slugs(args: argparse.Namespace, cities: list[dict[str, Any]]) -> list[str]:
    if args.slugs:
        return [s.strip() for s in args.slugs.split(",") if s.strip()]
    if args.slugs_file:
        p = Path(args.slugs_file)
        return [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.strip().startswith("#")]
    # default: all cities in index
    return [c["slug"] for c in cities]

def dummy_facts(lat: float, ctx_today: date) -> StoryFacts:
    hemi = "north" if lat >= 0 else "south"
    return StoryFacts(
        data_start_year=ctx_today.year,
        data_end_year=ctx_today.year,
        total_warming_50y=None,
        recent_warming_10y=None,
        last_year_anomaly=None,
        hemisphere=hemi,
    )

def main() -> None:
    args = parse_args()
    cities_index_path = Path(args.cities_index)
    out_root = Path(args.out)

    if args.asof:
        asof = date.fromisoformat(args.asof)
    else:
        asof = date.today() - timedelta(days=1)

    # IMPORTANT: your live builders use ctx.today - 1 day as the end date :contentReference[oaicite:3]{index=3}
    # So we set ctx.today = asof + 1, making end date exactly `asof`.
    ctx_today = asof + timedelta(days=1)

    cities = load_cities_index(cities_index_path)
    slugs = choose_slugs(args, cities)
    by_slug = {c["slug"]: c for c in cities}

    latest_path = out_root / "latest.json"
    latest = {}
    if latest_path.exists():
        latest = json.loads(latest_path.read_text(encoding="utf-8"))

    for slug in slugs:
        city = by_slug.get(slug)
        if not city:
            print(f"[skip] unknown slug {slug}")
            continue

        lat = float(city["lat"])
        lon = float(city["lon"])
        label = str(city.get("label") or slug)
        city_name = str(city.get("city_name") or label)

        # Build once (unit doesn't matter for the fetched data)
        ctxC = StoryContext(
            today=ctx_today,
            slug=slug,
            location_label=label,
            city_name=city_name,
            location_lat=lat,
            location_lon=lon,
            unit="C",
            ds=xr.Dataset(),  # not used by live panels
        )
        facts = dummy_facts(lat, ctx_today)

        out_dir = live_slug_dir(out_root, asof, slug)

        # Fetch + compute data once
        w_data = build_last_week_data(ctxC)
        m_data = build_last_month_data(ctxC)

        if w_data is None or m_data is None:
            write_json(out_dir / "build_error.json", {"slug": slug, "asof": asof.isoformat(), "error": "Open-Meteo returned None"})
            continue

        # Render per unit from the same data
        for unit in ("C", "F"):
            ctx = StoryContext(
                today=ctx_today,
                slug=slug,
                location_label=label,
                city_name=city_name,
                location_lat=lat,
                location_lon=lon,
                unit=unit,
                ds=xr.Dataset(),
            )

            # last week
            fig_w, _tiny = build_last_week_figure(ctx, facts, w_data)
            cap_w = last_week_caption(ctx, facts, w_data)
            p = panel_paths(out_dir, "last_week", unit)
            write_plotly_svg(p.svg, fig_w)
            write_text(p.caption_md, normalize_caption(cap_w))

            # last month
            fig_m, _tiny = build_last_month_figure(ctx, facts, m_data)
            cap_m = last_month_caption(ctx, facts, m_data)
            p = panel_paths(out_dir, "last_month", unit)
            write_plotly_svg(p.svg, fig_m)
            write_text(p.caption_md, normalize_caption(cap_m))

        # shared metadata
        write_json(out_dir / "meta.json", {
            "slug": slug,
            "label": label,
            "asof": asof.isoformat(),
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "source": "Open-Meteo",
            "panels": ["last_week", "last_month"],
        })

        latest[slug] = asof.isoformat()
        print(f"[ok] {slug} {asof.isoformat()} -> {out_dir}")
    
    print(f"[writing] {len(latest)} entries -> {latest_path}")
    write_json(latest_path, latest)

if __name__ == "__main__":
    main()
