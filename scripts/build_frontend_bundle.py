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

from climate.panels.intro import intro_caption  # we will build intro "data" ourselves


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
