# Case-study data: generating a page's figures

How a case-study page gets its numbers, and how to build the next one.

## The rule

**No figure is typed into the markup.** Every number the prose quotes and every
series the charts draw comes from one generated JSON file that the page
imports. A data refresh plus one re-run of the generator moves the prose and the
charts together.

This exists because the alternative was tried. The June 2026 heatwave page has
its figures typed into the JSX and its chart values baked into a literal array.
When the data was refreshed to 13 July, one day was revised down 0.34 °C by
ERA5T, which moved the headline peak from +9.3 °C on 27 June to +9.0 °C on the
26th — and that single revision had to be chased by hand through the prose, the
stat cards, the chart annotation and 43 bar heights. Anything not regenerated
silently disagrees with everything else.

## The shape

```
release (packaged metrics + regional aggregates)
   │
   ├── scripts/make_<story>_story_data.py  ──►  content/stories/<slug>/data.json
   │        (also reads the episode JSON below)
   │
   └── experiments/heatwave_analysis.py    ──►  logs/**/episodes_global.json
            (reads the whole-globe CDS cache; needs the external drive)
```

The page imports `data.json` through a typed view (`storyData.ts`), so it is
compiled into the client bundle at build time. **The charts make no API call.**
Only the maps do — see "What still needs the API" below.

## Building the data

```bash
# 1. Heat episodes, if the story counts them. Needs the CDS globe cache mounted.
PYTHONPATH=$PWD conda run -n climate python experiments/heatwave_analysis.py \
    --set global --json-out logs/<run>/episodes_global.json

# 2. The page's data file. Local only; no cache, no downloads.
PYTHONPATH=$PWD conda run -n climate python \
    scripts/make_summer_2026_story_data.py \
    --json web/src/content/stories/<slug>/data.json
```

Re-run step 2 after **any** data refresh, and after changing a window, a
baseline or a country set. The generator prints which episode file it used.

## Starting a third case study

1. **Copy the generator**, not the page. `scripts/make_summer_2026_story_data.py`
   is the template: a set of small functions that each read a packaged metric's
   regional aggregates and return plain data, then one `export_json` that
   assembles them. Keep that shape — one function per figure group, no HTML, no
   formatting decisions.
2. **Type the output.** Mirror `storyData.ts`: a `StoryData` type plus small
   helpers (`pct`, `days`, `n0`, `n1`). The type is what stops a renamed field
   failing silently at runtime.
3. **Charts read the typed object and draw SVG directly.** They take no props
   beyond a selection. Colour and mark classes live in the story's CSS module
   as `:global` class names, because the export path serializes computed styles
   and needs real class names to bake.
4. **Prose interpolates the same helpers.** If a sentence states a number, it
   reads it from `DATA`. If a number cannot be computed, it needs a footnote to
   an external source, not a literal.
5. **No HTML entities in JSX text.** A text node containing `&#8202;` or
   `&apos;` loses its leading space in the compiled output, and the obvious
   workaround (`</b>{" "}text`) is undone by prettier the next time it joins
   the line. Use the literal character instead: `U+200A` for a hair space,
   `’` for an apostrophe, `&` for an ampersand. Check a rendered page with
   `curl <url> | grep -oE '</(b|em|strong|span|a|sup)>[A-Za-z][a-z]{2,}'`;
   it should print nothing.
6. **Watch the bundle.** Daily series dominate: eight countries of daily
   maximum over a 31-year baseline is ~225 KB of a 273 KB file. Store them as
   `{d0, v[]}` (start day-of-year plus consecutive values) rather than pairs;
   that halved it. If it grows past a few hundred KB, load it on demand instead
   of importing it.

## What still needs the API

Measured on the summer 2026 page: **7 requests on load** (1 × `/release` for the
layer list, 6 × rendered map textures) and **2 × `/panel` after clicking a
location** — the only metric queries on the page.

So a deploy needs the release published for:

- the map textures any `<AnomalyMap>` or `<StoryGlobe>` draws,
- `/release`, which resolves layer ids to asset paths,
- the metrics the location panel plots (`t2m_daily_mean`, `tp_daily_total`).

It does **not** need the release for any chart or any figure in the text.

One more coupling: if the story's pipeline work added a field to a file under
`climate/registry/*.schema.json`, the **code must be deployed before the
release is published**, or the old API rejects the new registry and the whole
site breaks — not just the story. See the deployment runbook, "Order: code
before data".

If a story's maps render as grey placeholders, check first whether the API is
reachable from the client: it binds `127.0.0.1` by default, so a phone on the
LAN gets the page from Next (which binds all interfaces) and nothing from the
API. Start it with `./scripts/api_backend.sh --lan`.

## Registry entries for a window run

A story that steps through many windows needs one metric, map and layer per
window. Generate them rather than hand-editing:
`scripts/make_heat_window_registry.py` writes ~18 windows across three registry
files from a single description, and replaces its own block on a re-run. Prefix
the ids with the story (`t2m_heatslider_sum26_*`) so a later study can add its
own without collision.

Rendering them is local: delete the texture and manifest, then

```bash
python scripts/build/packager.py --release dev --all --resume \
    --start-year 2026 --end-year 2026 --maps <comma,separated,map,ids>
```

`--resume` keeps every derived metric at `tiles_written=0`, so nothing touches
the CDS cache. Note `--maps` takes a comma list; a shell-built string of
repeated `--map` flags does not word-split under zsh.

## Attribution

The Copernicus licence prescribes the wording for derived products. Pages and
exported images carry:

> Contains modified Copernicus Climate Change Service information \<year\>

and the page also carries the no-endorsement note the licence asks for. Do not
embed the ECMWF or Copernicus logos: ECMWF's terms permit the logo for linking
to their site and no other purpose, and a logo on a figure reads as endorsement.
