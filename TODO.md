Next:

- for resolve/autocomplete:
  - Add a “best match” endpoint for a free‑text query (single request)
  - Add prefix‑length + fuzziness tuning knobs to autocomplete
  - clicking on wellington returns Fiji ("GET /api/v/dev/panel?lat=-41.26954950284258&lon=534.7650146484376&unit=C HTTP/1.1")
- for packager:
  - era5 is downloaded as whole globe but then sliced, maybe this should be in the datasets/metrics as currently we need to force `--batch-tiles 4` for the packager to read the slices
- graphs:
- mobile version

---

For later:

- case study pages that illustrate recent headlines like "2025 was second hottest year on record", effect of el nino/la nina on temperatures, etc.
