- Place Resolver:
  - (needed?) Add a “best match” endpoint for a free‑text query (single request)
  - (needed?) Add prefix‑length + fuzziness tuning knobs to autocomplete
- UI:
  - Mobile version
  - Map: don't reset zoom when clicking on map (don't zoom out)
  - remove "Selected Location: "
  - fix search bar overlapping home button when window is resized
  - change scrolling style to snap
- Graphs:
  - zoomout graph needs work
  - support trend with negative temperatures (overlay is above trend)
- Packager script:
  - era5 is downloaded as whole globe but then sliced, maybe this should be in the datasets/metrics as currently we need to force `--batch-tiles 4` for the packager to read the slices

---

For later:

- case study pages that illustrate recent headlines like "2025 was second hottest year on record", effect of el nino/la nina on temperatures, etc.
