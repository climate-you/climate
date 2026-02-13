- Place Resolver:
  - (needed?) Add a “best match” endpoint for a free‑text query (single request)
  - (needed?) Add prefix‑length + fuzziness tuning knobs to autocomplete
  - use zoom level to decide whether to snap to bigger cities (eg. Paris instead of Clichy)
- UI:
  - Mobile version fix backend doesn't access data
  - Mobile version fix minzoom of globe
  - Map: don't reset zoom when clicking on map (don't zoom out)
  - remove "Selected Location: "
  - change scrolling style to snap to two graphs if size allows it or one.
  - layer selector
- Graphs:
  - zoomout graph needs work
- Packager script:
  - specify projection in maps.json so it can be applied to MapLibre
  - era5 is downloaded as whole globe but then sliced, maybe this should be in the datasets/metrics as currently we need to force `--batch-tiles 4` for the packager to read the slices

---

For later:

- case study pages that illustrate recent headlines like "2025 was second hottest year on record", effect of el nino/la nina on temperatures, etc.
