from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any
import textwrap

import xarray as xr
import matplotlib.pyplot as plt


from climate.analytics import compute_story_facts
from climate.models import StoryContext
from climate.export.web_write import write_json, write_text
from climate.export.web_paths import story_slug_dir, panel_paths
from climate.export.captions import normalize_caption, caption_md_to_json
from climate.export.web_write import write_plotly_svg, write_matplotlib_svg

from climate.panels.intro import intro_caption  # we will build intro "data" ourselves
from climate.panels.zoomout import (
    build_last_year_data,
    build_last_year_figure,
    last_year_caption,
    build_five_year_data,
    build_five_year_figure,
    five_year_caption,
    build_fifty_year_data,
    build_fifty_year_figure,
    fifty_year_caption,
    build_twenty_five_years_data,
    build_twenty_five_years_figure,
    twenty_five_years_caption,
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
from climate.panels.ocean import (
    build_sst_anom_data,
    build_sst_anom_figure,
    sst_anom_caption,
    build_sst_hotdays_data,
    build_sst_hotdays_figure,
    sst_hotdays_caption,
    build_dhw_data,
    build_dhw_figure,
    build_dhw_figure_with_trend,
    build_dhw_heatmap_figure,
    dhw_caption,
    build_ocean_context_map_figure,
)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--locations-csv", default="locations/locations.csv")
    ap.add_argument("--clim-dir", default="data/story_climatology")
    ap.add_argument("--out-story", default="web/public/data/story")
    ap.add_argument("--out-index", default="web/public/data/cities_index.json")
    ap.add_argument(
        "--slugs",
        default=None,
        help="Comma-separated web slugs (e.g. gb_london,jp_tokyo)",
    )
    ap.add_argument(
        "--today",
        default=None,
        help="Override today's date (YYYY-MM-DD). Default = today.",
    )
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
                "population": (
                    int(float(r["population"])) if r.get("population") else None
                ),
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


def write_panel_caption(
    slug_dir: Path,
    panel: str,
    unit: str,
    md: str,
    *,
    title: str = "",
    header: str = "",
    source: str = "",
    url: str = "",
) -> None:
    """
    Backwards-compatible caption export:
    - Always write legacy caption.md (used by current web app)
    - Also write caption.json (future structured captions)
    """
    p = panel_paths(slug_dir / "panels", panel, unit)
    md_norm = normalize_caption(md)
    write_text(p.caption_md, md_norm)
    write_json(
        p.caption_json,
        caption_md_to_json(md_norm, title=title, header=header, source=source, url=url),
    )


def build_story_manifest_v1(slug: str, *, has_ocean: bool) -> dict:
    """
    Static story manifest (v1). This describes slide order and how many figures each slide has.

    Note: live panels (last_week/last_month) are exported separately by build_live_panels.py,
    so they are not included here yet.

    Ocean Stress slides are included only when ocean cache exists for the slug.
    """
    slides = [
        {
            "id": "intro",
            "layout": "none",
            "figures": [],
            "caption_panel": "intro",
            "left": {"kind": "globe"},
        },
        {
            "id": "last_year",
            "layout": "single",
            "figures": [{"panel": "last_year", "kind": "svg", "animate": True}],
            "caption_panel": "last_year",
            "left": {"kind": "globe"},
        },
        {
            "id": "five_year",
            "layout": "single",
            "figures": [{"panel": "five_year", "kind": "svg", "animate": True}],
            "caption_panel": "five_year",
            "left": {"kind": "globe"},
        },
        {
            "id": "twenty_five_years",
            "layout": "single",
            "figures": [{"panel": "twenty_five_years", "kind": "svg", "animate": True}],
            "caption_panel": "twenty_five_years",
            "left": {"kind": "globe"},
        },
        {
            "id": "fifty_year",
            "layout": "single",
            "figures": [{"panel": "fifty_year", "kind": "svg", "animate": True}],
            "caption_panel": "fifty_year",
            "left": {"kind": "globe"},
        },
        {
            "id": "seasons_shift",
            "layout": "single",
            "figures": [{"panel": "seasons_shift", "kind": "svg", "animate": True}],
            "caption_panel": "seasons_shift",
            "left": {"kind": "globe"},
        },
        {
            "id": "seasons_range",
            "layout": "two_up",
            "figures": [
                {
                    "panel": "seasons_range_earlier",
                    "slot": "left",
                    "kind": "svg",
                    "animate": True,
                },
                {
                    "panel": "seasons_range_recent",
                    "slot": "right",
                    "kind": "svg",
                    "animate": True,
                },
            ],
            "caption_panel": "seasons_range",
            "left": {"kind": "globe"},
        },
        {
            "id": "you_vs_world",
            "layout": "two_up",
            "figures": [
                {
                    "panel": "you_vs_world_local",
                    "slot": "left",
                    "kind": "svg",
                    "animate": False,
                },
                {
                    "panel": "you_vs_world_global",
                    "slot": "right",
                    "kind": "svg",
                    "animate": False,
                },
            ],
            "caption_panel": "you_vs_world",
            "left": {"kind": "globe"},
        },
    ]

    if has_ocean:
        slides.extend(
            [
                {
                    "id": "ocean_sst_anom",
                    "layout": "single",
                    "figures": [
                        {"panel": "ocean_sst_anom", "kind": "svg", "animate": True}
                    ],
                    "caption_panel": "ocean_sst_anom",
                    "left": {"kind": "svg", "asset": "maps/ocean_sst_map.svg"},
                },
                {
                    "id": "ocean_sst_hotdays",
                    "layout": "single",
                    "figures": [
                        {"panel": "ocean_sst_hotdays", "kind": "svg", "animate": False}
                    ],
                    "caption_panel": "ocean_sst_hotdays",
                    "left": {"kind": "svg", "asset": "maps/ocean_sst_map.svg"},
                },
                {
                    "id": "ocean_dhw",
                    "layout": "single",
                    "figures": [
                        {
                            "panel": "ocean_dhw",
                            "kind": "svg",
                            "animate": False,
                            "variants": [
                                {
                                    "panel": "ocean_dhw_with_trend",
                                    "kind": "svg",
                                    "icon": "curve",
                                },
                                {
                                    "panel": "ocean_dhw_heatmap",
                                    "kind": "webp",
                                    "icon": "heatmap",
                                },
                            ],
                        }
                    ],
                    "caption_panel": "ocean_dhw",
                    "left": {"kind": "svg", "asset": "maps/ocean_context_map.svg"},
                },
            ]
        )

    return {
        "version": 1,
        "slug": slug,
        "slides": slides,
    }


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
            write_panel_caption(
                slug_dir, "intro", unit, md, title="", header="", source="", url=""
            )

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
                (
                    "last_year",
                    build_last_year_data,
                    build_last_year_figure,
                    last_year_caption,
                ),
                (
                    "five_year",
                    build_five_year_data,
                    build_five_year_figure,
                    five_year_caption,
                ),
                (
                    "fifty_year",
                    build_fifty_year_data,
                    build_fifty_year_figure,
                    fifty_year_caption,
                ),
                (
                    "twenty_five_years",
                    build_twenty_five_years_data,
                    build_twenty_five_years_figure,
                    twenty_five_years_caption,
                ),
            ]
            for panel_name, build_data_fn, build_fig_fn, caption_fn in panel_specs:
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
                    write_panel_caption(
                        slug_dir,
                        panel_name,
                        unit,
                        cap,
                        source="ERA5 (climatology) / local processing",
                    )

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
                    fig_shift, _tiny = build_seasons_then_now_figure(
                        ctx_u, facts, seasons_data
                    )
                    p = panel_paths(slug_dir / "panels", "seasons_shift", unit)
                    write_plotly_svg(p.svg, fig_shift)
                    write_panel_caption(
                        slug_dir,
                        "seasons_shift",
                        unit,
                        seasons_then_now_caption(ctx_u, facts, seasons_data),
                        source="ERA5 (climatology) / local processing",
                    )

                    # Slide 2: two figures side-by-side + shared caption
                    fig_past, fig_recent = build_seasons_then_now_separate_figures(
                        ctx_u, facts, seasons_data
                    )

                    p_past = panel_paths(
                        slug_dir / "panels", "seasons_range_earlier", unit
                    )
                    p_recent = panel_paths(
                        slug_dir / "panels", "seasons_range_recent", unit
                    )
                    write_plotly_svg(p_past.svg, fig_past)
                    write_plotly_svg(p_recent.svg, fig_recent)

                    write_panel_caption(
                        slug_dir,
                        "seasons_range",
                        unit,
                        seasons_then_now_separate_caption(ctx_u, facts, seasons_data),
                        source="ERA5 (climatology) / local processing",
                    )
            else:
                print(
                    f"[info] monthly climatologies unavailable for {slug}; skipping seasons panels"
                )

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
                fig_local, fig_global, tiny = build_you_vs_world_figures(
                    ctx_u, facts, data_w
                )
                cap = you_vs_world_caption(ctx_u, facts, data_w)

                # Append the tiny streamlit caption as a final italic line (optional but nice for sharing)
                if tiny:
                    cap = cap.rstrip() + "\n\n" + f"_{tiny}_"

                p_local = panel_paths(slug_dir / "panels", "you_vs_world_local", unit)
                p_global = panel_paths(slug_dir / "panels", "you_vs_world_global", unit)

                write_plotly_svg(p_local.svg, fig_local)
                write_plotly_svg(p_global.svg, fig_global)
                write_panel_caption(
                    slug_dir,
                    "you_vs_world",
                    unit,
                    cap,
                    source="ERA5 (climatology) / local processing",
                )

            # -----------------------------------------------------------
            # OCEAN STRESS (SST anomaly, SST hot-days, coral heat stress / DHW)
            #
            # Writes per unit:
            #   - ocean_sst_anom.<UNIT>.svg + ocean_sst_anom.<UNIT>.caption.md
            #   - ocean_sst_hotdays.<UNIT>.svg + ocean_sst_hotdays.<UNIT>.caption.md
            #   - ocean_dhw.<UNIT>.svg + ocean_dhw.<UNIT>.caption.md
            #
            # Writes unit-agnostic maps (SVG):
            #   - maps/ocean_context_map.svg
            #   - maps/ocean_sst_map.svg   (reserved for later; not written yet)
            # -----------------------------------------------------------
            try:
                sst_anom_data = build_sst_anom_data(ctx_data)
                sst_hotdays_data = build_sst_hotdays_data(ctx_data)
                dhw_data = build_dhw_data(ctx_data)
            except Exception as e:
                sst_anom_data = None
                sst_hotdays_data = None
                dhw_data = None
                print(
                    f"[info] ocean cache unavailable for {slug}; skipping ocean exports ({type(e).__name__}: {e})"
                )

            if sst_anom_data is not None:
                # Map (unit-agnostic): current “context” map (DHW box / coastline context)
                try:
                    fig_map, tiny = build_ocean_context_map_figure(
                        ctx_data, facts, dhw_data
                    )
                    map_path = slug_dir / "maps" / "ocean_context_map.svg"
                    write_matplotlib_svg(map_path, fig_map)
                except Exception as e:
                    print(
                        f"[info] ocean context map failed for {slug} ({type(e).__name__}: {e})"
                    )

                # Reserve room for later (SST anomaly map), but don't write anything yet:
                # slug_dir / "maps" / "ocean_sst_map.svg"

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

                    # SST anomaly
                    fig, tiny = build_sst_anom_figure(ctx_u, facts, sst_anom_data)
                    cap = sst_anom_caption(ctx_u, facts, sst_anom_data)
                    if tiny:
                        cap = cap.rstrip() + "\n\n" + f"_{tiny}_"
                    p = panel_paths(slug_dir / "panels", "ocean_sst_anom", unit)
                    write_plotly_svg(p.svg, fig)
                    write_text(p.caption_md, normalize_caption(cap))

                    # SST hot days (baseline P90)
                    fig, tiny = build_sst_hotdays_figure(ctx_u, facts, sst_hotdays_data)
                    cap = sst_hotdays_caption(ctx_u, facts, sst_hotdays_data)
                    if tiny:
                        cap = cap.rstrip() + "\n\n" + f"_{tiny}_"
                    p = panel_paths(slug_dir / "panels", "ocean_sst_hotdays", unit)
                    write_plotly_svg(p.svg, fig)
                    write_text(p.caption_md, normalize_caption(cap))

                    # DHW (coral heat stress) — default bars
                    fig, tiny = build_dhw_figure(ctx_u, facts, dhw_data)
                    cap = dhw_caption(ctx_u, facts, dhw_data)
                    if tiny:
                        cap = cap.rstrip() + "\n\n" + f"_{tiny}_"
                    p = panel_paths(slug_dir / "panels", "ocean_dhw", unit)
                    write_plotly_svg(p.svg, fig)
                    write_text(p.caption_md, normalize_caption(cap))

                    # Variant A: bars + max-DHW trend (dual axis) — SVG only, no caption
                    fig2, _tiny2 = build_dhw_figure_with_trend(ctx_u, facts, dhw_data)
                    p2 = panel_paths(slug_dir / "panels", "ocean_dhw_with_trend", unit)
                    write_plotly_svg(p2.svg, fig2)

                    # Variant B: heatmap (Design 2) — WEBP raster, no caption
                    fig_hm, _tiny_hm = build_dhw_heatmap_figure(
                        ctx_u, facts, dhw_data, use_threshold_jumps=True
                    )
                    if fig_hm is not None:
                        p3 = panel_paths(slug_dir / "panels", "ocean_dhw_heatmap", unit)
                        heat_path = p3.svg.with_suffix(".webp")
                        heat_path.parent.mkdir(parents=True, exist_ok=True)
                        fig_hm.savefig(
                            heat_path,
                            format="webp",
                            dpi=220,
                            bbox_inches="tight",
                            transparent=True,
                        )
                        plt.close(fig_hm)

        # story manifest (static bundle)
        ocean_path = Path("data/story_ocean") / f"ocean_{slug}.nc"
        has_ocean = ocean_path.exists()
        write_json(
            slug_dir / "story.json", build_story_manifest_v1(slug, has_ocean=has_ocean)
        )

        # meta (optional, useful for debugging)
        ocean_path = Path("data/story_ocean") / f"ocean_{slug}.nc"
        has_ocean = ocean_path.exists()
        write_json(
            slug_dir / "meta.json",
            {
                "slug": slug,
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "climatology_file": str(clim_path),
                "ocean_file": str(ocean_path) if has_ocean else None,
                "today": today.isoformat(),
            },
        )

        print(f"[ok] {slug} -> {slug_dir}")

    print(f"[done] wrote {out_index_path}")


if __name__ == "__main__":
    main()
