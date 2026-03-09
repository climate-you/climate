Bug fixes / Cleanup:

- add better system to close/reduce `selected location` panel on mobile. Disable swipe down reloads page.
- move steps button to the right just above legend. On mobile reduce it to one button that change label when clicking on it.
- when recent warming layer is selected change the `selected location` title to appropriate warming value. Same for sea layers. Also change visible graph... Link graph cards and title tbd...
- `Annual air temperature` instead of `Annual temperature`.
- track with goat counter which graphs and layers are viewed.
- double check color scale of warming layers in India.
- ask Claude to code review.
- create small video presentation, cold open + fly-to London.
- (?) Make it clear year range for graphs, eg. "Annual temperature (1979-2025)" (or maybe just in info bubble)
- clean up unused css and methods in code when all features and bugfix are done.

Before public website+github:

- Sitemap/robots.txt for google?
- refine stripe account desciption when site is up
- add link to https://ko-fi.com/climateyou to github when repo is public (see `Display a "Sponsor" button` in settings).
- create a new demo release (+ upload somewhere, github?)
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
