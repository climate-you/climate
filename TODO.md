- [ ] Track: Cleanup
  - [x] Store code in google drive
  - [x] Make sure all data paths come from same root dir (might be hardcoded in some files)
  - [x] Some wordings are incorrect in captions (-0.0ºC, falling by -0.7ºC, shift is in Oct)
  - [x] Lint on whole codebase: Prettier for Javascript, Black for Python => format on save
  - [ ] There's a "+1.0C" hardcoded for global warming in the intro panel
  - [ ] Apply changes suggested to mention real figure in Monte Carlo
  - [ ] Add Sources under each graph
- [x] Track: Globe design
  - [x] Prototype several looks
  - [x] Decide on a look
  - [x] Tweak/improve
  - [x] Setup hero vs mini
  - [x] Swap in main page
- [x] Track: front end v1
  - [x] Landing page: show globe + get user location + get current temp at location
  - [x] Tweak landing page look
  - [x] With a front end version will we get live data queried by client or by backend? (ie. will it burn our allowance or use free allowance from user’s ip?)
  - [x] Add intro panel
  - [x] Add zoomout panels
  - [x] Setup scroller for "1 slide per page" look
  - [x] Show animated SVGs
  - [x] Setup light vs dark mode
  - [x] Add season panels (+ title change)
    - [x] General graphs+captions + add new slides
    - [x] Proper bullet markers for lists
    - [x] Title change
  - [x] Add you vs world panels (+ title change)
  - [x] Add world map panel using 3d globe + warming texture (+ title change)
    - [x] Should target location but with equator in the middle
    - [x] Disable grid lines
    - [x] No texture animation, straight to warming texture => fine as short animation
    - [x] Marker should disappear when globe starts spinning
    - [x] Caption is only visible at the bottom when scrolling again => text on the side
- [ ] Track: precompute
  - [ ] Refactor precompute scripts to use new `climate.datasets` module
  - [ ] Generate updated handoff summary
  - [ ] Discuss again cds vs openmeteo (resolution especially) for precompute
  - [ ] Is it doable to go on paid sub and basically process any location on the fly? We precompute a few cities etc and then any new city triggers a precompute for missing data
  - [ ] Rewrite make_city_list.py with better selection criteria
  - [ ] Rewrite precompute_story_cities.py with CDS requests + append every quarter/month
- [ ] Track: Better slide layout
  - [ ] Dynamic loading of slides
  - [ ] Look at how to have better captions+graphs:
    - maybe caption has a header (before the graph)
    - maybe some sentences could be revealed before some curves
      => captions generated as json with different fields ("header", "source", etc.)
- [ ] Track: Add MonteCarlo simulation
- [ ] Track: Revisit story
  - [x] Do we need to compute data from several datasets (air temperature, water temperature, precipitation, pollution) and extract a few key points for this location: what has changed?
  - [x] Prototype computing SST, DHW for coastal areas + precipitations for inland
  - [x] Add ocean stress slides
- [ ] Track: Add comparisons with other cities
  - [ ] Introduce some "compare your result with 2 other cities showing different patterns", examples:
    - it's currently XXºC could be shown on a vertical slide with name of city, and show some extreme cities (very cold, very hot, etc.)
    - compare how a city in southern/northern hemisphere has shifted summer/winter cycle
    - if not much change, then show a city with much bigger change
    - if lot of change, then show a city with no change

---

For later:

- case study pages that illustrate recent headlines like "2025 was second hottest year on record", effect of el nino/la nina on temperatures, etc.

---

NEXT:

- for resolve/autocomplete:
  - Return geonameid only and drop slugs from responses entirely
  - Add a “best match” endpoint for a free‑text query (single request)
    -Add prefix‑length + fuzziness tuning knobs to autocomplete
- have a better redis monitoring (only display if changes detected)
- for ocean locations, maybe the ocean polygons with natural earth make the most sense. But how would we be able to return "Coast off <city>" with this? Would we do:
- check if water cell, then find nearest city, if less than X km, return "<ocean name> off <city>", otherwise return "<ocean name>"
- if not water cell, find nearest city and returns it
  So in both cases, we need to check water cell + nearest city.
- add `maps.json` to generate maps from metrics:
  - `source: metric_id`
  - type: `png` for textures (linear option, colour palette)
  - type: `png` black/white for interestingness
  - type: `binary` for interestingness (to do lookups: `(lat,lon)->(cell_i, cell_j)->interesting?`)
- add animated graphs:
  - add steps, each step a different graph
  - how to handle the animation: we need to keep series from one step to another, so a true zoomout animation can be performed, is that supported?
