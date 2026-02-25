- UI:
  - update Licenses/Copyrights.
  - BUGFIX: coral reef map renders all black on mobile.
  - consider black background on 3D globe in dark mode.
- Graphs:
  - BUGFIX: why doesn't sea off Palma, Spain lat=39.50297210372494&lon=2.6395117761082076 have sea temperature information ? Afficher la grid for debug purposes.
  - BUGFIX: why for lat=3.740930549248077&lon=8.77532958984375 the monthly mean looks like it's offset ? Use daily mean to create monthly mean.
- Code:
  - Prepare a `demo` release that can be tar-gzed or zipped with correct locations / no zoomout / shorter time range - reef only on great barrier => upload it somewhere and reference it in the docs to have a demo version up and running

Last steps:

- refine ko-fi and stripe account desciption when site is up
- add link to https://ko-fi.com/climateyou to github when repo is public (see `Display a "Sponsor" button` in settings).
- Finalise doc: public URL, latest screenshots, link to `demo` release

---

For later:

- precipitations graph (?)
- seasons step on `Annual sea temperature`
- graph with all years on top of each other and last 5 years in bright colours to distinguish them from older years (grey)
- Place Resolver:
  - Add a “best match” endpoint for a free‑text query (single request) (replace `autocomplete`->`resolve` by `best-match`)
  - Add prefix‑length + fuzziness tuning knobs to autocomplete (`Lodnon` -> `London`)
- UX:
  - case study pages that illustrate recent headlines like "2025 was second hottest year on record", effect of el nino/la nina on temperatures, etc.
