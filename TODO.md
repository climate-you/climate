Next:

- for resolve/autocomplete:
  - Return geonameid only and drop slugs from responses entirely
  - Add a “best match” endpoint for a free‑text query (single request)
  - Add prefix‑length + fuzziness tuning knobs to autocomplete
- for packager:
  - era5 is downloaded as whole globe but then sliced, maybe this should be in the datasets/metrics as currently we need to force `--batch-tiles 4` for the packager to read the slices

---

For later:

- case study pages that illustrate recent headlines like "2025 was second hottest year on record", effect of el nino/la nina on temperatures, etc.
