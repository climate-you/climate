- UI:
  - Add scale to UI when showing globe textures
  - Test on mobile (need to run `./scripts/api_backend.sh --lan`)
  - Make top left buttons more pleasing: increase size of buttons to match search bar, keep same number of blue pixels up and left, move the search bar a bit to the right to accomodate larger icons
  - merge info icon and sources button? (only one button that opens the popup window)
  - info window with several tabs: About (description of project + authors) | Sources | Licenses/Copyrights)
- Graphs:
  - zoomout graph needs work + rephrase graph captions + info bubble
  - extra coral reef stress graph + new texture for 3D globe (beware of different grid size)
- Code:
  - add more python tests so coverage is higher (current 21%)
  - add e2e tests
  - Update README for github: project intro + few screenshots + diagram showing datasets->metrics->etc.

---

For later:

- precipitations graph (?)
- graph with all years on top of each other and last 5 years in bright colours to distinguish them from older years (grey)
- Place Resolver:
  - Add a “best match” endpoint for a free‑text query (single request) (replace `autocomplete`->`resolve` by `best-match`)
  - Add prefix‑length + fuzziness tuning knobs to autocomplete (`Lodnon` -> `London`)
- UX:
  - case study pages that illustrate recent headlines like "2025 was second hottest year on record", effect of el nino/la nina on temperatures, etc.
