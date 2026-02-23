- UI:
  - Add scale to UI when showing globe textures
  - Test on mobile (need to run `./scripts/api_backend.sh --lan`):
    -- hide the close button: swiping down should close the panel (revisit).
    -- about/sources button should be under the selected location panel, should they be moved to a menu (?)
  - update Licenses/Copyrights
  - coral reef layer should have blue background ?
- Graphs:
  - why doesn't Palma, Spain have sea temperature information ?
  - zoomout graph needs work + rephrase graph captions + info bubble
- Code:
  - clean up unused css and methods in code.
  - Prepare a `demo` release that can be tar-gzed or zipped with correct locations / no zoomout / shorter time range - reef only on great barrier => upload it somewhere and reference it in the docs to have a demo version up and running
  - Finalise doc: public URL, latest screenshots, link to `demo` release

---

For later:

- precipitations graph (?)
- graph with all years on top of each other and last 5 years in bright colours to distinguish them from older years (grey)
- Place Resolver:
  - Add a “best match” endpoint for a free‑text query (single request) (replace `autocomplete`->`resolve` by `best-match`)
  - Add prefix‑length + fuzziness tuning knobs to autocomplete (`Lodnon` -> `London`)
- UX:
  - case study pages that illustrate recent headlines like "2025 was second hottest year on record", effect of el nino/la nina on temperatures, etc.
