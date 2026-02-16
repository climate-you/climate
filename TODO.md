- Place Resolver:
  - (needed?) Add a “best match” endpoint for a free‑text query (single request)
  - (needed?) Add prefix‑length + fuzziness tuning knobs to autocomplete
  - Use zoom level to decide whether to snap to bigger cities (eg. Paris instead of Clichy)
- UI:
  - Clean location label (font, population)
  - Rephrase graph captions
  - Rephrase title
  - Add scale to UI when showing warming map layers
  - Clicking on space picks a point
- Graphs:
  - zoomout graph needs work
- Packager script:
  - era5 is downloaded as whole globe but then sliced, maybe this should be in the datasets/metrics as currently we need to force `--batch-tiles 4` for the packager to read the slices
  - maps are copied to `web/public/data`, should they go in a release folder? or the next app pointed to `data/releases/`?
- Code:
  - add more python tests
  - add e2e tests
  - benchmark scripts:
    - is the `bench_place_resolver` script needed?
    - `bench_api_endpoints` doesn't test `nearest` endpoint
    - update README with typical smoke test
  - tile_coverage reports some metrics with 98% - check why
  - we should have a single test script that runs packager check + tile coverage + unit tests + smoke tests
  - we should have the same css properties for all graphs
  -

## Error Type

Runtime TypeError

## Error Message

Cannot read properties of undefined (reading 'getDataParams')

    at <unknown> (file:///Users/benoit.leveau/Documents/Programming/Fanny/climate/web/.next/dev/static/chunks/node_modules_echarts_lib_component_tooltip_f384d9ab._.js:1811:43)
    at Array.forEach (<anonymous>:null:null)
    at each (file:///Users/benoit.leveau/Documents/Programming/Fanny/climate/web/.next/dev/static/chunks/node_modules_zrender_lib_83be358d._.js:460:13)
    at <unknown> (file:///Users/benoit.leveau/Documents/Programming/Fanny/climate/web/.next/dev/static/chunks/node_modules_echarts_lib_component_tooltip_f384d9ab._.js:1808:175)
    at Array.forEach (<anonymous>:null:null)
    at each (file:///Users/benoit.leveau/Documents/Programming/Fanny/climate/web/.next/dev/static/chunks/node_modules_zrender_lib_83be358d._.js:460:13)
    at <unknown> (file:///Users/benoit.leveau/Documents/Programming/Fanny/climate/web/.next/dev/static/chunks/node_modules_echarts_lib_component_tooltip_f384d9ab._.js:1794:171)
    at Array.forEach (<anonymous>:null:null)
    at each (file:///Users/benoit.leveau/Documents/Programming/Fanny/climate/web/.next/dev/static/chunks/node_modules_zrender_lib_83be358d._.js:460:13)
    at TooltipView._showAxisTooltip (file:///Users/benoit.leveau/Documents/Programming/Fanny/climate/web/.next/dev/static/chunks/node_modules_echarts_lib_component_tooltip_f384d9ab._.js:1793:167)
    at TooltipView._tryShow (file:///Users/benoit.leveau/Documents/Programming/Fanny/climate/web/.next/dev/static/chunks/node_modules_echarts_lib_component_tooltip_f384d9ab._.js:1730:18)
    at TooltipView.manuallyShowTip (file:///Users/benoit.leveau/Documents/Programming/Fanny/climate/web/.next/dev/static/chunks/node_modules_echarts_lib_component_tooltip_f384d9ab._.js:1636:18)
    at <unknown> (file:///Users/benoit.leveau/Documents/Programming/Fanny/climate/web/.next/dev/static/chunks/node_modules_echarts_lib_component_tooltip_f384d9ab._.js:1575:45)

Next.js version: 16.1.6 (Turbopack)

---

For later:

- case study pages that illustrate recent headlines like "2025 was second hottest year on record", effect of el nino/la nina on temperatures, etc.
