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

-

Place Resolver:

- check if locations.csv can add more places from geonames (check if available for <500)
- add search bar with autocomplete for place names: add index to be able to search quickly
- check if we should use KD tree for place lookup
- what location to use in the middle of the oceans?

Caching:

- we should cache panels per cell not per (lat,lon), we can change the cache key but should we do a redirect (lat,lon)->(cell_i,cell_j) so that browser requests can be cached too?

--

Queue status

My jobs on CDS are staying in `Accepted` (not moving to `Running`) for a long time (~30 minutes at the moment). When I display more information I see this information:

```
- Requests for ERA5 daily statistics datasets is limited to 60 concurrent requests | Running: 60 — Queued: 1468
- The maximum number of requests that access the CDS-MARS archive is 400 | Running: 400 — Queued: 5945
- Large (> two variables, one months) requests for ERA5 daily statistics datasets are limited to 40 | Running: 40 — Queued: 1162
```

I'm not sure what I can do about the maximum number of requests (the 60 and 400) but I wonder about the last point about large requests. Because I'm doing 6 month at a time, I guess the jobs are considered large. Would they go faster if they were just one month at a time?

--
for oisst

SST: both PFEL ERDDAP hosts timing out — what I recommend

At this point it looks like your network path to pfeg.noaa.gov is unreliable (timeouts on both coastwatch.pfeg.noaa.gov and upwell.pfeg.noaa.gov). Increasing timeouts might help, but you’ll still get brittle runs.

So for the spike, I’d switch SST acquisition to NCEI direct daily NetCDF files, and download a reduced set of years first (to prove it works + already likely relevant to coral stress).

Why this is reasonable:

NCEI explicitly provides OISST v2.1 daily data and notes it’s updated daily.

There’s a browsable directory of daily files like oisst-avhrr-v02r01.YYYYMMDD.nc.

NCEI also warns there can be access delays due to outages, so you want caching + retries anyway.
