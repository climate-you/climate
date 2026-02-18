- UI:
  - Add scale to UI when showing warming map layers
  - Home page with cold open: test globe fading in from all blue so we don't see tiles loading.
  - Add info bubble next to title and graphs' titles to explain how data is computed.
  - Globe textures menu overlaps with cities search bar
  - Test on mobile
  - Dark mode
- Graphs:
  - zoomout graph needs work + rephrase graph captions
  - "Hot days per year" => "Number of Hot Days (NHD)"
  - extra coral reef stress graph + new texture for 3D globe
- Code:
  - add more python tests
  - add e2e tests
  - [WIP] tile_coverage reports some metrics with 98% - check why
  - README: present project + images for github
  - dev local changes to panels.json cp

---

For later:

- precipitations graph (?)
- Place Resolver:
  - Add a “best match” endpoint for a free‑text query (single request) (replace `autocomplete`->`resolve` by `best-match`)
  - Add prefix‑length + fuzziness tuning knobs to autocomplete (`Lodnon` -> `London`)
- UX:
  - case study pages that illustrate recent headlines like "2025 was second hottest year on record", effect of el nino/la nina on temperatures, etc.
