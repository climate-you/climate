# Runbook: Story Coastline Overlay

Use this runbook to rebuild the coastline + country-border overlay drawn on top
of story maps.

What you are building:

- a compact JSON of coastline and national-border polylines, clipped to a
  bounding box and simplified for web delivery

Where it is used:

- `web/src/components/story/AnomalyMap.tsx` draws these lines over a crop of a
  global mercator anomaly texture. The textures carry no geography of their own,
  so without this overlay a story map is an unreadable colour field.
- the same overlay is drawn into the hi-res PNG exports produced by the story
  download buttons

## Input Data Sources

- Natural Earth coastlines (`physical` / `coastline`): <https://www.naturalearthdata.com/>
- Natural Earth national borders (`cultural` / `admin_0_boundary_lines_land`)

Data is fetched and cached by `cartopy.io.shapereader.natural_earth` on first
run, so the first invocation needs network access. Natural Earth is public
domain; see [`web/public/THIRD_PARTY_NOTICES.md`](../../web/public/THIRD_PARTY_NOTICES.md).

## Rebuild

```bash
python scripts/make_coastline_overlay.py
```

Defaults write `web/public/story/europe-lines.json` at `50m` resolution, clipped
to the Europe frame used by the June–July 2026 heat story (`-30 25 55 72`, with
margin so the story can be reframed without regenerating).

Useful options:

```bash
python scripts/make_coastline_overlay.py --help
python scripts/make_coastline_overlay.py --bbox -125 24 -66 50 --out web/public/story/us-lines.json
python scripts/make_coastline_overlay.py --resolution 10m --simplify 0.01
```

| Option         | Default                              | Notes                                                      |
| -------------- | ------------------------------------ | ---------------------------------------------------------- |
| `--bbox`       | `-30 25 55 72`                       | Clip box, `WEST SOUTH EAST NORTH` in degrees                |
| `--out`        | `web/public/story/europe-lines.json` | Output path                                                 |
| `--resolution` | `50m`                                | Natural Earth resolution (`10m`, `50m`, `110m`)             |
| `--simplify`   | `0.02`                               | Tolerance in degrees (~2 km); `0` disables simplification   |

## Output Format

```json
{
  "bbox": [west, south, east, north],
  "coast": [[[lon, lat], ...], ...],
  "borders": [[[lon, lat], ...], ...]
}
```

Coordinates are rounded to 3 decimals (~100 m). The default Europe overlay is
roughly 120 KB with 200 coastline and 143 border polylines.

## Adding an overlay for a new region

1. Generate a JSON for the region's bounding box with `--bbox` and `--out`.
2. Point the story's `linesUrl` at the new file (see the `LINES_URL` constant in
   the story component under `web/src/content/stories/<slug>/`).

Keep the generated bbox a little larger than the frame the story actually
displays, so the map can be reframed without a regeneration.

## Notes

- Increase `--resolution` to `10m` only if a story zooms in far enough for `50m`
  coastlines to look blocky; it materially increases file size.
- Simplification is applied with `preserve_topology=False`, which is fine for
  purely decorative reference lines but is not suitable if the output is ever
  used for analysis.

## Related: social sharing image

`scripts/make_story_og_image.py` builds a story's 1200x630 Open Graph card,
reusing the same texture crop and coastline overlay:

```bash
python scripts/make_story_og_image.py \
  --texture data/releases/dev/maps/global_0p25/t2m_heatwave_2026_w2_mercator_texture/t2m_heatwave_2026_w2_mercator.webp \
  --title "The June–July 2026 heat over Europe" \
  --out web/public/story/june-2026-heatwave-og.png
```

`--kicker`, `--source`, `--bbox`, `--logo` and `--lines` are all overridable.
Reference the result from the story route's `openGraph.images`.
