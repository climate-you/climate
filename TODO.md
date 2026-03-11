Bug fixes / Cleanup:

- recent warming:
  - double check color scale of warming layers in India.
  - virer recent warming layer.
- [WIP] ask Claude to code review.
  - asked about hardcoded thingys in the code: (?) Year constants (1979, 2000, 1850) — should live in one place in climate_api/ rather than inline in panels.py and tile_data_store.py

Before public website+github:

- [WIP] create small video presentation, cold open + fly-to London.
- [WIP] create a new demo release
  - create tar.gz file
  - create tag `demo-v20260310`
  - create release (mark as pre-release) in github and upload tar.gz file
  - update docs with proper link
- Finalise doc: latest screenshots (or video?), link to `demo` release

---

For later:

- [WIP] Continue investigating offset between texture and cells (display a specific lat/lon area in texture and check in debug)
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
