- UI:
  - Rephrase graph captions
  - Rephrase title
  - Add scale to UI when showing warming map layers
  - Clicking on space picks a point
  - Home page with cold open
  - Globe textures menu overlaps with cities search bar
  - Test on mobile
  - Dark mode
- Graphs:
  - zoomout graph needs work
  - extra coral reef stress graph + new texture for 3D globe
  - precipitations graph (?)
- Cache:
  - Redis keys are `climate_api:panel:dev:registry:air_temperature:C:cells:global_0p25:688:151`, shouldn't we cache the whole panel instead of individual graphs? Check speed gain.
  - `--score-map-preload` should force loading maps for latest release without having to hit it first
- Code:
  - add more python tests
  - add e2e tests
  - tile_coverage reports some metrics with 98% - check why
  - README: present project + images for github

---

For later:

- Place Resolver:
  - Add a “best match” endpoint for a free‑text query (single request) (replace `autocomplete`->`resolve` by `best-match`)
  - Add prefix‑length + fuzziness tuning knobs to autocomplete (`Lodnon` -> `London`)
- UX:
  - case study pages that illustrate recent headlines like "2025 was second hottest year on record", effect of el nino/la nina on temperatures, etc.
