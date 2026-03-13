Deploy v1:

- tag as `v1.0.0`
- make github repository public
- change `The code for this website will soon be available on`
- enable `Report a bug`
- copy `registry/` to `data/releases/2026_03_04/registry/` after git pull

Run this after new deploy:
rg -n "goatcounter|gc.zgo.at" /opt/climate/app/web/.next
curl -fsS https://climate.you | rg "goatcounter|gc.zgo.at"

---

For later:

- Year constants should come from registry.
- [WIP] map of users and clicks (in GoatCounter ? or in a lightweight file/db sqlite, etc.)
- [WIP] precipitations graph (annual temperature, dry spells, maybe check patterns?)
- Seasons graph: do we need defer loading of daily metrics? (check performance)
- [Plan] Revisit dual-repository setup (public core + private) - `docs/public-open-source-repository-strategy-plan.md`
- [Codex] Packager optimization for sparse domains: build mask-aware rectangular download batches (cluster occupied tiles, split oversized boxes on 413) to reduce ERDDAP overfetch for reef-like datasets.
- seasons step on `Annual sea temperature`
- graph with all years on top of each other and last 5 years in bright colours to distinguish them from older years (grey)
- Place Resolver / Search bar:
  - add a “best match” endpoint for a free‑text query (single request) (replace `autocomplete`->`resolve` by `best-match`)
  - Add prefix‑length + fuzziness tuning knobs to autocomplete (`Lodnon` -> `London`)
  - should we start autocomplete at 1/2 characters?
- case study pages that illustrate recent headlines like "2025 was second hottest year on record", effect of el nino/la nina on temperatures, etc.
- Spread the word:
  - Terrain tiles say "tell us about your project": https://registry.opendata.aws/terrain-tiles/
  - contact CDS
- revamp releases:
  - add compatibility version in `release/manifest.json` (eg. `requires: v1.0`)
  - metrics should be versioned, and a release should be a list of `metric->version` (so a new release with 95% of metrics same as before won't take up much more space on disk)

---
