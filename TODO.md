- UI:
  - Add scale to UI when showing globe textures
  - Test on mobile (need to run `./scripts/api_backend.sh --lan`):
    -- `Couldn't load data` appears as the data loads for the first time.
    -- Cold open interaction doesn't respect the sequence order.
    -- move the close button swiping down should close the panel (revisit).
    -- about/sources button should be under the selected location panel, should they be moved to a menu (?)
    -- move the temperature widget (where?)
  - update Licenses/Copyrights
- Graphs:
  - zoomout graph needs work + rephrase graph captions + info bubble
  - extra coral reef stress graph + new texture for 3D globe (beware of different grid size)
- Code:
  - add more python tests so coverage is higher (current 21%)
  - Update README for github: project intro + few screenshots + diagram showing datasets->metrics->etc.
  - clean up unused css and methods in code.

---

For later:

- precipitations graph (?)
- graph with all years on top of each other and last 5 years in bright colours to distinguish them from older years (grey)
- Place Resolver:
  - Add a “best match” endpoint for a free‑text query (single request) (replace `autocomplete`->`resolve` by `best-match`)
  - Add prefix‑length + fuzziness tuning knobs to autocomplete (`Lodnon` -> `London`)
- UX:
  - case study pages that illustrate recent headlines like "2025 was second hottest year on record", effect of el nino/la nina on temperatures, etc.
