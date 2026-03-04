Bug fixes / Cleanup:

- ExplorerPage has several places with layer names hardcoded (eg. `warming_air`): legend, dark mode
- clean up unused css and methods in code when all features and bugfix are done.
- add link to github

Before beta tests:

- Finish transition from Google Cloud to Hetzner. Check Firewall options, create other user than root.
- Install ssh certificate.
- Transfer DNS domain to new static IP.

Before public website+github:

- refine stripe account desciption when site is up
- add link to https://ko-fi.com/climateyou to github when repo is public (see `Display a "Sponsor" button` in settings).
- Decide/write license for github public repository
- Finalise doc: latest screenshots, link to `demo` release

---

For later:

- [WIP] Continue investigating offset between texture and cells
- [WIP] map of users and clicks in GoatCounter (?)
- Seasons graph: do we need defer loading of daily metrics?
- [WIP] Revisit dual-repository setup (public core + private) - `docs/public-open-source-repository-strategy-plan.md`
- [Codex] Packager optimization for sparse domains: build mask-aware rectangular download batches (cluster occupied tiles, split oversized boxes on 413) to reduce ERDDAP overfetch for reef-like datasets.
- precipitations graph (?)
- seasons step on `Annual sea temperature`
- graph with all years on top of each other and last 5 years in bright colours to distinguish them from older years (grey)
- Place Resolver:
  - Add a “best match” endpoint for a free‑text query (single request) (replace `autocomplete`->`resolve` by `best-match`)
  - Add prefix‑length + fuzziness tuning knobs to autocomplete (`Lodnon` -> `London`)
- UX:
  - case study pages that illustrate recent headlines like "2025 was second hottest year on record", effect of el nino/la nina on temperatures, etc.
- Spread the word:
  - Terrain tiles say "tell us about your project": https://registry.opendata.aws/terrain-tiles/
