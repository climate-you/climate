- Place Resolver:
  - (needed?) Add a “best match” endpoint for a free‑text query (single request)
  - (needed?) Add prefix‑length + fuzziness tuning knobs to autocomplete
  - paris selects saint vincent de paul, 3 entries in csv: 2976607, 2976608, 12808657
  - filter out PPLX and only use PPA2 for city name
- UI:
  - Rephrase graph captions
  - Rephrase title
  - Add scale to UI when showing warming map layers
  - Clicking on space picks a point
  - Home page with cold open
  - Globe textures menu overlaps with cities search bar
  - Test on mobile
- Graphs:
  - zoomout graph needs work
  - extra coral reef stress graph + new texture for 3D globe
  - precipitations graph (?)
- Packager script:
  - era5 is downloaded as whole globe but then sliced, maybe this should be in the datasets/metrics as currently we need to force `--batch-tiles 4` for the packager to read the slices
  - maps are copied to `web/public/data`, should they go in a release folder? or the next app pointed to `data/releases/`?
  - release process not clear, `/api/v/<release>/panel` ignores the `release` tag and reads panels from `registry/`
- Code:
  - add more python tests
  - add e2e tests
  - benchmark scripts:
    - is the `bench_place_resolver` script needed?
    - `bench_api_endpoints` doesn't test `nearest` endpoint
    - update README with typical smoke test
  - tile_coverage reports some metrics with 98% - check why
  - we should have a single test script that runs packager check + tile coverage + unit tests + smoke tests

---

For later:

- case study pages that illustrate recent headlines like "2025 was second hottest year on record", effect of el nino/la nina on temperatures, etc.
