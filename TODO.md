Next:

- for resolve/autocomplete:
  - Return geonameid only and drop slugs from responses entirely
  - Add a “best match” endpoint for a free‑text query (single request)
    -Add prefix‑length + fuzziness tuning knobs to autocomplete
- for ocean locations, maybe the ocean polygons with natural earth make the most sense. But how would we be able to return "Coast off <city>" with this? Would we do:
  - check if water cell, then find nearest city, if less than X km, return "<ocean name> off <city>", otherwise return "<ocean name>"
  - if not water cell, find nearest city and returns it
    So in both cases, we need to check water cell + nearest city.
- add animated graphs:
  - add steps, each step a different graph
  - how to handle the animation: we need to keep series from one step to another, so a true zoomout animation can be performed, is that supported?

---

For later:

- case study pages that illustrate recent headlines like "2025 was second hottest year on record", effect of el nino/la nina on temperatures, etc.
