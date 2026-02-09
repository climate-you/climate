Next:

- when toggling the temperature unit, we need to re-send panel query
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
- keep score maps in memory? [done via SCORE_MAP_PRELOAD]
- score_1_map shouldn't use a metric [done via constant_score]

---

For later:

- case study pages that illustrate recent headlines like "2025 was second hottest year on record", effect of el nino/la nina on temperatures, etc.
