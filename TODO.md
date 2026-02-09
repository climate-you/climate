Next:

- for resolve/autocomplete:
  - Return geonameid only and drop slugs from responses entirely
  - Add a “best match” endpoint for a free‑text query (single request)
  - Add prefix‑length + fuzziness tuning knobs to autocomplete
- for ocean locations, a binary mask of oceans would be the fastest/easiest. The process could become:
  - check if water cell, then find nearest city, if less than X km, return "<ocean name> off <city>", otherwise return "<ocean name>"
  - if not water cell, returns nearest city
    So in both cases, we need to check water cell + nearest city.
- add animated graphs:
  - zoomout animation
  - no `series` field when animated is on otherwise we have duplicate/conflicting entries

---

For later:

- case study pages that illustrate recent headlines like "2025 was second hottest year on record", effect of el nino/la nina on temperatures, etc.
