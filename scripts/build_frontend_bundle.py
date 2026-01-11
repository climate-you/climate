from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any
import textwrap

import xarray as xr


from climate.analytics import compute_story_facts
from climate.models import StoryContext
from climate.export.web_write import write_json, write_text
from climate.export.web_paths import story_slug_dir, panel_paths
from climate.export.captions import normalize_caption
from climate.export.web_write import write_plotly_svg

from climate.panels.intro import intro_caption  # we will build intro "data" ourselves
from climate.panels.zoomout import (
    build_last_year_data, build_last_year_figure, last_year_caption,
    build_five_year_data, build_five_year_figure, five_year_caption,
    build_fifty_year_data, build_fifty_year_figure, fifty_year_caption,
    build_twenty_five_years_data, build_twenty_five_years_figure, twenty_five_years_caption,
)
from climate.panels.seasons import (
    build_seasons_then_now_data,
    build_seasons_then_now_figure,
    build_seasons_then_now_separate_figures,
    seasons_then_now_caption,
    seasons_then_now_separate_caption,
)
from climate.panels.world import (
    build_you_vs_world_data,
    build_you_vs_world_figures,
    you_vs_world_caption,
)

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--locations-csv", default="locations/locations.csv")
    ap.add_argument("--clim-dir", default="data/story_climatology")
    ap.add_argument("--out-story", default="web/public/data/story")
    ap.add_argument("--out-index", default="web/public/data/cities_index.json")
    ap.add_argument("--slugs", default=None, help="Comma-separated web slugs (e.g. gb_london,jp_tokyo)")
    ap.add_argument("--today", default=None, help="Override today's date (YYYY-MM-DD). Default = today.")
    return ap.parse_args()


def web_slug_from_locations_slug(loc_slug: str) -> str:
    # 1:1 between loc_slug and web_slug
    return loc_slug


def read_locations(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    return rows


def build_cities_index(loc_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in loc_rows:
        if (r.get("kind") or "").strip() != "city":
            continue
        loc_slug = r["slug"].strip()
        web_slug = web_slug_from_locations_slug(loc_slug)

        out.append(
            {
                "slug": web_slug,
                "label": r.get("label", "").strip().strip('"'),
                "city_name": r.get("city_name", "").strip(),
                "country_name": r.get("country_name", "").strip(),
                "country_code": r.get("country_code", "").strip(),
                "lat": float(r["lat"]),
                "lon": float(r["lon"]),
                "timezone": r.get("timezone", "").strip(),
                "population": int(float(r["population"])) if r.get("population") else None,
                "geonameid": int(r["geonameid"]) if r.get("geonameid") else None,
                "source_slug": loc_slug,
            }
        )
    return out


def strip_intro_now_paragraph(md: str) -> str:
    """
    intro_caption currently prepends a paragraph about current temp availability.
    In the web app, we already show 'It's currently ...' from the live proxy,
    so we drop that first paragraph here and keep the longer-term narrative.
    """
    parts = [p.strip() for p in md.strip().split("\n\n") if p.strip()]
    if not parts:
        return md.strip()

    first = parts[0].lower()
    if (
        first.startswith("it is currently")
        or first.startswith("because we’ve reached")
        or ("current temperature" in first and "unavailable" in first)
    ):
        return "\n\n".join(parts[1:]).strip()

    # If caption format changes later, fail gracefully: return full md
    return md.strip()


def main() -> None:
    args = parse_args()
    locations_csv = Path(args.locations_csv)
    clim_dir = Path(args.clim_dir)
    out_story_root = Path(args.out_story)
    out_index_path = Path(args.out_index)

    today = date.fromisoformat(args.today) if args.today else date.today()

    loc_rows = read_locations(locations_csv)
    cities_index = build_cities_index(loc_rows)

    # Write index for the web app
    write_json(out_index_path, cities_index)

    # Optional slug filter
    want_slugs = None
    if args.slugs:
        want_slugs = {s.strip() for s in args.slugs.split(",") if s.strip()}

    # Build per-city bundle
    for city in cities_index:
        slug = city["slug"]
        if want_slugs is not None and slug not in want_slugs:
            continue

        clim_path = clim_dir / f"clim_{slug}.nc"
        if not clim_path.exists():
            print(f"[skip] missing nc for {slug}: {clim_path}")
            continue

        ds = xr.open_dataset(clim_path)

        # facts based on latitude (your streamlit uses this)
        facts = compute_story_facts(ds, lat=float(city["lat"]))

        # Write facts.json
        slug_dir = story_slug_dir(out_story_root, slug)
        write_json(slug_dir / "facts.json", asdict(facts))

        # Intro caption per unit (C/F), offline version (no live temp)
        for unit in ("C", "F"):
            ctx = StoryContext(
                today=today,
                slug=slug,
                location_label=city["label"],
                city_name=city["city_name"],
                location_lat=float(city["lat"]),
                location_lon=float(city["lon"]),
                unit=unit,
                ds=ds,
            )

            # Build the minimal data dict intro_caption expects, without live temp
            intro_data = {
                "temp_now_c": None,
                "temp_now_time": None,
                "global_delta": 1.0,  # keep hardcoded for now
            }

            md = intro_caption(ctx, facts, intro_data)
            md = strip_intro_now_paragraph(md)
            p = panel_paths(slug_dir / "panels", "intro", unit)
            write_text(p.caption_md, normalize_caption(md))


            # Compute unit-neutral data once per panel (uses ctx.ds; independent of ctx.unit)
            ctx_data = StoryContext(
                today=today,
                slug=slug,
                location_label=city["label"],
                city_name=city["city_name"],
                location_lat=float(city["lat"]),
                location_lon=float(city["lon"]),
                unit="C",  # arbitrary; data builders are in Celsius internally
                ds=ds,
            )

            panel_specs = [
                ("last_year", build_last_year_data, build_last_year_figure, last_year_caption),
                ("five_year", build_five_year_data, build_five_year_figure, five_year_caption),
                ("fifty_year", build_fifty_year_data, build_fifty_year_figure, fifty_year_caption),
                ("twenty_five_years", build_twenty_five_years_data, build_twenty_five_years_figure, twenty_five_years_caption),
            ]
            for (panel_name, build_data_fn, build_fig_fn, caption_fn) in panel_specs:
                data = build_data_fn(ctx_data)

                for unit in ("C", "F"):
                    ctx_u = StoryContext(
                        today=today,
                        slug=slug,
                        location_label=city["label"],
                        city_name=city["city_name"],
                        location_lat=float(city["lat"]),
                        location_lon=float(city["lon"]),
                        unit=unit,
                        ds=ds,
                    )

                    fig, _tiny = build_fig_fn(ctx_u, facts, data)
                    cap = caption_fn(ctx_u, facts, data)

                    p = panel_paths(slug_dir / "panels", panel_name, unit)
                    write_plotly_svg(p.svg, fig)
                    write_text(p.caption_md, normalize_caption(cap))
            
            # ---------------------------------------------------------------------
            # Seasons then vs now (2 slides in web):
            #  - Slide 1: seasons_shift (single figure)
            #  - Slide 2: seasons_range_earlier + seasons_range_recent (two figures) + seasons_range caption
            # ---------------------------------------------------------------------
            seasons_data = build_seasons_then_now_data(ctx_data)
            if seasons_data:
                for unit in ("C", "F"):
                    ctx_u = StoryContext(
                        today=today,
                        slug=slug,
                        location_label=city["label"],
                        city_name=city["city_name"],
                        location_lat=float(city["lat"]),
                        location_lon=float(city["lon"]),
                        unit=unit,
                        ds=ds,
                    )

                    # Slide 1: single figure
                    fig_shift, _tiny = build_seasons_then_now_figure(ctx_u, facts, seasons_data)
                    p = panel_paths(slug_dir / "panels", "seasons_shift", unit)
                    write_plotly_svg(p.svg, fig_shift)
                    write_text(p.caption_md, normalize_caption(seasons_then_now_caption(ctx_u, facts, seasons_data)))

                    # Slide 2: two figures side-by-side + shared caption
                    fig_past, fig_recent = build_seasons_then_now_separate_figures(ctx_u, facts, seasons_data)

                    p_past = panel_paths(slug_dir / "panels", "seasons_range_earlier", unit)
                    p_recent = panel_paths(slug_dir / "panels", "seasons_range_recent", unit)
                    write_plotly_svg(p_past.svg, fig_past)
                    write_plotly_svg(p_recent.svg, fig_recent)

                    p_cap = panel_paths(slug_dir / "panels", "seasons_range", unit)
                    write_text(
                        p_cap.caption_md,
                        normalize_caption(seasons_then_now_separate_caption(ctx_u, facts, seasons_data)),
                    )
            else:
                print(f"[info] monthly climatologies unavailable for {slug}; skipping seasons panels")

            # -----------------------------------------------------------
            # YOU VS THE WORLD (local vs global anomalies) — 2 figures side-by-side in the web slide
            # Writes:
            #   - you_vs_world_local.<UNIT>.svg
            #   - you_vs_world_global.<UNIT>.svg
            #   - you_vs_world.<UNIT>.caption.md
            #
            # Note: build_you_vs_world_data() applies °F conversion based on ctx.unit,
            # so we must compute it per unit (cannot reuse unit-neutral data).
            # -----------------------------------------------------------
            for unit in ("C", "F"):
                ctx_u = StoryContext(
                    today=today,
                    slug=slug,
                    location_label=city["label"],
                    city_name=city["city_name"],
                    location_lat=float(city["lat"]),
                    location_lon=float(city["lon"]),
                    unit=unit,
                    ds=ds,
                )

                data_w = build_you_vs_world_data(ctx_u)
                fig_local, fig_global, tiny = build_you_vs_world_figures(ctx_u, facts, data_w)
                cap = you_vs_world_caption(ctx_u, facts, data_w)

                # Append the tiny streamlit caption as a final italic line (optional but nice for sharing)
                if tiny:
                    cap = cap.rstrip() + "\n\n" + f"_{tiny}_"

                p_local = panel_paths(slug_dir / "panels", "you_vs_world_local", unit)
                p_global = panel_paths(slug_dir / "panels", "you_vs_world_global", unit)
                p_cap = panel_paths(slug_dir / "panels", "you_vs_world", unit)

                write_plotly_svg(p_local.svg, fig_local)
                write_plotly_svg(p_global.svg, fig_global)
                write_text(p_cap.caption_md, normalize_caption(cap))

                    
        # meta (optional, useful for debugging)
        write_json(slug_dir / "meta.json", {
            "slug": slug,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "climatology_file": str(clim_path),
            "today": today.isoformat(),
        })

        print(f"[ok] {slug} -> {slug_dir}")

    print(f"[done] wrote {out_index_path}")


if __name__ == "__main__":
    main()
