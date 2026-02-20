- UI:
  - Add scale to UI when showing globe textures
  - Globe textures: move icon to bottom, and close menu on user interaction outside menu (click on search, etc.)
  - Test on mobile
  - Dark mode
  - Search bar: remove blue border, remove "Searching..." text, and remove "min 3 chars" text
  - Add Source page
  - Default to ºF when user location in US
  - when backend down, page shows "In this location, human activities have caused warming since 1850-1900", maybe a clearer error page?
- Graphs:
  - Add text to info bubbles to explain how data is computed
  - zoomout graph needs work + rephrase graph captions
  - extra coral reef stress graph + new texture for 3D globe
- Code:
  - add more python tests
  - add e2e tests
  - README: present project + images for github

---

For later:

- precipitations graph (?)
- Place Resolver:
  - Add a “best match” endpoint for a free‑text query (single request) (replace `autocomplete`->`resolve` by `best-match`)
  - Add prefix‑length + fuzziness tuning knobs to autocomplete (`Lodnon` -> `London`)
- UX:
  - case study pages that illustrate recent headlines like "2025 was second hottest year on record", effect of el nino/la nina on temperatures, etc.
