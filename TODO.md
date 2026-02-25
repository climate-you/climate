- UI:
  - BUGFIX: fix scale getting harcoded color for gradient scale for warming layers.
  - BUGFIX: coral reef map renders all black on mobile.
  - update Licenses/Copyrights.
  - update help bubbles: calculation of pre-industrial warming
  - check UI for coral reef graph
- Graphs:
  - BUGFIX: why doesn't sea off Palma, Spain lat=39.50297210372494&lon=2.6395117761082076 have sea temperature information ? Afficher la grid for debug purposes.
  - BUGFIX: why for lat=3.740930549248077&lon=8.77532958984375 the monthly mean looks like it's offset ? Use daily mean to create monthly mean.
- Code:
  - BUGFIX: nearest point with mixed grid still not implemented
  - Prepare a `demo` release that can be tar-gzed or zipped with correct locations / no zoomout / shorter time range - reef only on great barrier => upload it somewhere and reference it in the docs to have a demo version up and running
  - cloud setup + first VM running
  - Zoomout - do we need defer loading?

Last steps:

- clean up unused css and methods in code when all features and bugfix are done.
- test mobile and dark mode.
- refine ko-fi and stripe account desciption when site is up
- add link to https://ko-fi.com/climateyou to github when repo is public (see `Display a "Sponsor" button` in settings).
- Decide/write license for github public repository
- Finalise doc: public URL, latest screenshots, link to `demo` release

---

For later:

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
