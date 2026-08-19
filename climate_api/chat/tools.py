"""
Climate tool implementations used by the chat orchestrator.

Each function is pure (no globals) and takes explicit dependencies.
Returns a dict that will be JSON-serialised and sent back to the LLM as a
tool result.  Errors are returned as {"error": "..."} so the LLM can
react rather than crashing the loop.
"""

from __future__ import annotations

from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# Continent → country-code mapping (GeoNames continent codes)
# ---------------------------------------------------------------------------

from climate.geo.continents import CONTINENT_TO_CC as _CONTINENT_TO_CC
from climate.geo.continents import CONTINENT_ALIASES as _CONTINENT_ALIASES
from climate.geo.continents import resolve_continent as _resolve_continent

from climate_api.store.location_index import LocationIndex
from climate_api.store.sovereignty import is_sovereign
from climate_api.store.tile_data_store import TileDataStore


# ---------------------------------------------------------------------------
# Temperature unit conversion helpers
# ---------------------------------------------------------------------------


def _is_delta_metric(spec: dict) -> bool:
    """Return True if the metric measures a temperature change rather than an absolute value.

    Inferred from the aggregator name — offset/anomaly aggregators produce deltas.
    """
    agg = spec.get("source", {}).get("agg", "")
    return any(kw in agg for kw in ("offset", "anomaly", "delta"))


def _convert_temp(value: float, spec: dict, *, is_delta: bool, target: str) -> float:
    """Convert a Celsius value to the target unit.

    is_delta=True  → multiply by 9/5 only (no +32 offset), for trends/anomalies.
    is_delta=False → full absolute conversion (×9/5 + 32).
    Non-temperature metrics (unit != "C") are returned unchanged.
    """
    if target != "F" or spec.get("unit") != "C":
        return value
    if is_delta:
        return round(value * 9 / 5, 3)
    return round(value * 9 / 5 + 32, 3)


def _output_unit(spec: dict, target: str) -> str:
    """Return the unit label to include in tool results."""
    if target == "F" and spec.get("unit") == "C":
        return "F"
    return spec.get("unit", "unknown")


def list_available_metrics(tile_store: TileDataStore) -> dict:
    metrics = []
    for metric_id, spec in tile_store.metrics.items():
        if spec.get("llm_hidden"):
            continue
        axis = tile_store.axis(metric_id)
        date_range = f"{axis[0]}-{axis[-1]}" if axis else "unknown"
        entry: dict = {
            "metric_id": metric_id,
            "description": spec.get("title", metric_id),
            "unit": spec.get("unit", "unknown"),
            "available_range": date_range,
            # Stated so the model can tell which metrics accept month_filter.
            # Without it, seasonal questions get aimed at yearly metrics, where
            # the filter cannot apply and a step is wasted re-querying.
            "resolution": spec.get("time_axis", "yearly"),
            "source": spec.get("source", {}).get("_dataset_ref", "unknown"),
        }
        if spec.get("llm_note"):
            entry["note"] = spec["llm_note"]
        metrics.append(entry)
    return {"metrics": metrics}


_COUNTRY_ALIASES = {
    "uk": "GB",
    "u k": "GB",
    "great britain": "GB",
    "britain": "GB",
    "england": "GB",
    "scotland": "GB",
    "wales": "GB",
    "usa": "US",
    "u s a": "US",
    "u s": "US",
    "america": "US",
    "united states of america": "US",
    "uae": "AE",
    "south korea": "KR",
    "north korea": "KP",
    "russia": "RU",
    "holland": "NL",
    "czechia": "CZ",
    "czech republic": "CZ",
}


def _country_code_for(
    qualifier: str, country_name_to_code: dict[str, str] | None
) -> str | None:
    """Map a trailing qualifier ("Germany", "UK", "DE") to an ISO country code."""
    q = " ".join(qualifier.strip().casefold().split())
    if not q:
        return None
    # Aliases first: "UK" is two letters but the ISO code is "GB", so a bare
    # two-letter passthrough would produce a code that matches nothing.
    if q in _COUNTRY_ALIASES:
        return _COUNTRY_ALIASES[q]
    if len(q) == 2 and q.isalpha():
        return q.upper()
    return (country_name_to_code or {}).get(q)


def resolve_location(
    name: str,
    location_index: LocationIndex,
    country_name_to_code: dict[str, str] | None = None,
) -> dict:
    """Resolve a place name to coordinates. Internal helper — not exposed as a tool.

    Exact name matches (which include alternate/exonym names such as "Londres"
    for London or "Cologne" for Köln) are tried before the prefix search, and a
    trailing country qualifier is used to disambiguate homonyms rather than
    being discarded. Without this, "Londres" reaches Londres in Argentina and
    "Cologne, Germany" reaches Cologne in Italy, since the prefix search matches
    only literal labels and ranks purely by population.
    """
    name = name.strip().strip("*")

    city_part, qualifier = name, ""
    if "," in name:
        city_part, qualifier = (p.strip() for p in name.split(",", 1))

    wanted_cc = (
        _country_code_for(qualifier, country_name_to_code) if qualifier else None
    )

    # Candidates in decreasing order of trust: exact match on the whole string,
    # exact match on the city part, then the prefix search as a last resort.
    candidates = location_index.resolve_all_by_any_name(name)
    if city_part != name:
        seen = {h.geonameid for h in candidates}
        candidates += [
            h
            for h in location_index.resolve_all_by_any_name(city_part)
            if h.geonameid not in seen
        ]
    if not candidates:
        candidates = location_index.autocomplete(name, limit=10)
    if not candidates and city_part != name:
        # Handles "London, UK" where the label carries a different country wording
        candidates = location_index.autocomplete(city_part, limit=10)

    if not candidates:
        return {"error": f"Location not found: '{name}'"}

    hit = candidates[0]
    if wanted_cc:
        # Prefer a candidate in the requested country; fall back to the most
        # populous match when the qualifier names no country we recognise.
        in_country = [h for h in candidates if h.country_code == wanted_cc]
        if in_country:
            hit = in_country[0]

    return {
        "lat": hit.lat,
        "lon": hit.lon,
        "label": hit.label,
        "country": hit.country_code,
    }


# A yearly series over the full record is ~47 points; this leaves room for a
# couple of calls plus the conversation inside an 8,000-token request budget.
_MAX_SERIES_POINTS = 120


def _summarise_long_series(result: dict, unit: str) -> dict:
    """Replace an over-long series with per-year means plus the extremes.

    Keeps what an answer actually needs — the shape of the record, the record
    highs and lows, and the most recent value — at a fraction of the size.
    """
    data = result["data"]
    by_year: dict[str, list[float]] = {}
    for point in data:
        value = point.get("value")
        if value is not None:
            by_year.setdefault(str(point["year"])[:4], []).append(value)

    def _year_key(year: str):
        # Emit numeric years, matching what a natively-yearly series returns.
        # Callers fit trend lines over this field, so a string here turns a
        # working chart into a numpy dtype error.
        try:
            return int(year)
        except (TypeError, ValueError):
            return year

    yearly = [
        {"year": _year_key(year), "value": round(sum(vals) / len(vals), 3)}
        for year, vals in sorted(by_year.items())
    ]

    finite = [p for p in data if p.get("value") is not None]
    hottest = max(finite, key=lambda p: p["value"], default=None)
    coldest = min(finite, key=lambda p: p["value"], default=None)

    return {
        **result,
        "data": yearly,
        # Flag rather than prose, so the chart title can say so too — a chart of
        # yearly means must not be captioned as if it were the native series.
        "collapsed_to_yearly": True,
        "resolution": "yearly means (the native series was too long to return in full)",
        "note": (
            (
                f"The underlying series has {len(data)} points at its native "
                f"resolution, which is too large to return in full. It has been "
                f"collapsed to {len(yearly)} yearly means. Highest single value: "
                f"{hottest['value']} {unit} at {hottest['year']}. Lowest: "
                f"{coldest['value']} {unit} at {coldest['year']}. To see individual "
                f"months or days, call again with a narrower start_year/end_year, "
                f"or with month_filter to pick specific months."
            )
            if hottest and coldest
            else "Series collapsed to yearly means; it was too long to return in full."
        ),
    }


def _resolve_region_id(
    region_id: str,
    tile_store: TileDataStore,
    metric_id: str,
    aggregation: str,
) -> str | None:
    """
    Try to resolve a human-readable region name or region_id to the canonical
    region_id key as stored in the aggregate data.

    Accepts:
    - Direct region_id: "country:FR", "continent:europe", "ocean:indian_ocean", "globe"
    - Country name: "France" → "country:FR"
    - Continent name: "Europe" → "continent:europe"
    - Ocean name: "Indian Ocean" → "ocean:indian_ocean"
    """
    agg_data = tile_store.aggregates.get((metric_id, aggregation))
    if agg_data is None:
        return None
    regions = agg_data.get("regions", {})

    # Direct lookup
    if region_id in regions:
        return region_id

    # Normalise for fuzzy lookup
    norm = region_id.strip().casefold()

    # Try "globe" alias
    if norm in ("global", "worldwide", "world", "globe"):
        if "globe" in regions:
            return "globe"

    # Try continent slug: "north america" → "continent:north_america"
    slug = norm.replace(" ", "_")
    for prefix in ("continent:", "country:", "ocean:"):
        candidate = f"{prefix}{slug}"
        if candidate in regions:
            return candidate
    # Also try upper case for country codes (e.g. "fr" → "country:FR")
    candidate_upper = f"country:{norm.upper()}"
    if candidate_upper in regions:
        return candidate_upper

    # Scan region names for a case-insensitive match
    for rid, info in regions.items():
        if info.get("name", "").casefold() == norm:
            return rid

    return None


def _get_metric_series(
    lat: float,
    lon: float,
    metric_id: str,
    tile_store: TileDataStore,
    start_year: int | None = None,
    end_year: int | None = None,
    month_filter: list[int] | None = None,
    aggregate_by_year: bool = False,
) -> dict:
    """Fetch metric series by coordinates. Internal — called by get_metric_series and scan tools."""
    spec = tile_store.metrics.get(metric_id)
    if spec is None:
        return {"error": f"Unknown metric_id: '{metric_id}'."}

    try:
        vec = tile_store.try_get_metric_vector(metric_id, lat, lon)
    except FileNotFoundError as e:
        return {"error": str(e)}

    if vec is None:
        return {
            "error": f"No data at lat={lat}, lon={lon} for metric '{metric_id}' (ocean/missing cell)."
        }

    axis = tile_store.axis(metric_id)
    if len(axis) != len(vec):
        return {"error": f"Axis/vector length mismatch: {len(axis)} vs {len(vec)}"}

    time_axis_type = spec.get("time_axis", "yearly")
    unit = spec.get("unit", "unknown")

    if time_axis_type == "monthly":
        # axis values are "YYYY-MM" strings
        data: list[dict[str, Any]] = []
        for a, v in zip(axis, vec):
            s = str(a)
            year, month = int(s[:4]), int(s[5:7])
            if start_year is not None and year < start_year:
                continue
            if end_year is not None and year > end_year:
                continue
            if month_filter is not None and month not in month_filter:
                continue
            data.append({"year": year, "month": month, "value": round(float(v), 3)})

        if not data:
            return {
                "error": (
                    f"No data for requested range. "
                    f"Available for '{metric_id}': {axis[0]} to {axis[-1]}."
                )
            }

        if aggregate_by_year and month_filter:
            year_vals: dict[int, list[float]] = {}
            for entry in data:
                year_vals.setdefault(entry["year"], []).append(entry["value"])
            data = [
                {"year": y, "value": round(sum(vs) / len(vs), 3)}
                for y, vs in sorted(year_vals.items())
            ]
            return {
                "metric_id": metric_id,
                "lat": lat,
                "lon": lon,
                "unit": unit,
                "data": data,
                # Carried so the chart can say which months it covers — a
                # June-only series titled "monthly mean" reads as all months.
                "month_filter": list(month_filter),
                "note": f"Annual means for months {month_filter}.",
            }

        monthly_result = {
            "metric_id": metric_id,
            "lat": lat,
            "lon": lon,
            "unit": unit,
            "data": data,
            **({"month_filter": list(month_filter)} if month_filter else {}),
        }
        # Same backstop as the regional tool: an unfiltered monthly series is
        # ~560 points, which is both unreadable as a chart and large enough to
        # overrun the request budget on its own.
        if len(data) > _MAX_SERIES_POINTS:
            monthly_result = _summarise_long_series(monthly_result, unit)
        return monthly_result

    else:
        # yearly axis — int years (also catches any unknown time_axis_type)
        try:
            years = [int(a) for a in axis]
        except (ValueError, TypeError):
            return {
                "error": f"Unsupported time axis format for metric '{metric_id}' (type: {time_axis_type!r})."
            }

        pairs = [(y, float(v)) for y, v in zip(years, vec)]
        available_min, available_max = years[0], years[-1]

        # Expand a narrow year range to at least 3 years so charts render a
        # curve rather than a dot.  Only applies when both bounds are set and
        # the range covers fewer than 3 distinct years.  Alternates extending
        # end then start so the result stays centred (e.g. 2024 → 2023-2025).
        if start_year is not None and end_year is not None:
            extend_end = True
            while end_year - start_year < 2:
                if extend_end and end_year + 1 <= available_max:
                    end_year += 1
                elif not extend_end and start_year - 1 >= available_min:
                    start_year -= 1
                elif end_year + 1 <= available_max:
                    end_year += 1
                elif start_year - 1 >= available_min:
                    start_year -= 1
                else:
                    break
                extend_end = not extend_end

        if start_year is not None:
            pairs = [(y, v) for y, v in pairs if y >= start_year]
        if end_year is not None:
            pairs = [(y, v) for y, v in pairs if y <= end_year]

        if not pairs:
            return {
                "error": (
                    f"No data for requested range. "
                    f"Available for '{metric_id}': {available_min}-{available_max}."
                )
            }

        result: dict = {
            "metric_id": metric_id,
            "lat": lat,
            "lon": lon,
            "unit": unit,
            "data": [{"year": y, "value": round(v, 3)} for y, v in pairs],
        }
        if month_filter:
            result["note"] = (
                f"month_filter {month_filter} is not applicable to a yearly metric; "
                "all years returned. Use a monthly metric (e.g. t2m_monthly_mean_c) "
                "to filter by month."
            )
            # The data is annual, not the months that were asked for, so it
            # answers a different question than the one posed. The model still
            # gets it (with the note above) and can re-query, but it must not
            # become a chart: an annual-mean curve shown beside a winter answer
            # reads as the winter trend.
            result["month_filter_ignored"] = True
        return result


def get_metric_series(
    location: str,
    metric_id: str,
    tile_store: TileDataStore,
    location_index: LocationIndex,
    start_year: int | None = None,
    end_year: int | None = None,
    month_filter: list[int] | None = None,
    aggregate_by_year: bool = False,
    temperature_unit: str = "C",
    country_name_to_code: dict[str, str] | None = None,
) -> dict:
    """Tool-facing wrapper: resolves location name then fetches the metric series."""
    loc = resolve_location(location, location_index, country_name_to_code)
    if "error" in loc:
        return loc
    result = _get_metric_series(
        loc["lat"],
        loc["lon"],
        metric_id,
        tile_store,
        start_year=start_year,
        end_year=end_year,
        month_filter=month_filter,
        aggregate_by_year=aggregate_by_year,
    )
    if "error" not in result:
        result["location"] = loc["label"]
        spec = tile_store.metrics.get(metric_id, {})
        if temperature_unit == "F" and spec.get("unit") == "C":
            is_delta = _is_delta_metric(spec)
            result["data"] = [
                {
                    **entry,
                    "value": _convert_temp(
                        entry["value"], spec, is_delta=is_delta, target="F"
                    ),
                }
                for entry in result["data"]
            ]
            result["unit"] = _output_unit(spec, "F")
    return result


def find_extreme_location(
    metric_id: str,
    aggregation: str,
    extremum: str,
    tile_store: TileDataStore,
    location_index: LocationIndex,
    country_name_to_code: dict[str, str],
    start_year: int | None = None,
    end_year: int | None = None,
    month_filter: list[int] | None = None,
    country: str | None = None,
    continent: str | None = None,
    capital_only: bool = False,
    min_population: int = 0,
    limit: int = 1,
    temperature_unit: str = "C",
) -> dict:
    """
    Scan candidate cities, compute an aggregation for each, return the
    top `limit` cities ranked by the aggregation value.

    NOTE: scans per-city tile reads — fast for filtered queries
    (capital_only, country, large min_population). Global unfiltered
    queries are slow and should be optimised in a later phase.
    """
    spec = tile_store.metrics.get(metric_id)
    if spec is None:
        return {"error": f"Unknown metric_id: '{metric_id}'."}
    if aggregation not in ("mean", "max", "min", "trend_slope"):
        return {
            "error": f"Unknown aggregation: '{aggregation}'. Use: mean, max, min, trend_slope."
        }
    if extremum not in ("max", "min"):
        return {"error": f"Unknown extremum: '{extremum}'. Use: max or min."}

    time_axis_type = spec.get("time_axis", "yearly")
    if aggregation == "trend_slope" and time_axis_type == "monthly":
        return {
            "error": "trend_slope is not supported for monthly metrics. Use mean, max, or min."
        }

    # Resolve country filter
    country_code: str | None = None
    if country:
        country_code = country_name_to_code.get(country.strip().casefold())
        if country_code is None:
            return {
                "error": f"Country not recognised: '{country}'. Use the full English country name."
            }

    # Resolve continent filter
    continent_codes: frozenset[str] | None = None
    if continent:
        continent_codes = _resolve_continent(continent)
        if continent_codes is None:
            return {
                "error": (
                    f"Continent not recognised: '{continent}'. "
                    "Use one of: Africa, Antarctica, Asia, Europe, "
                    "North America, Oceania, South America."
                )
            }

    # Fast-path: use precomputed ranking if available and no time-range/month filters.
    if start_year is None and end_year is None and month_filter is None:
        ranking = tile_store.rankings.get((metric_id, aggregation))
        if ranking is not None:
            effective_min_pop = max(min_population, 1000)
            filtered = [
                c
                for c in ranking
                if c["population"] >= effective_min_pop
                and (
                    not capital_only
                    or (c.get("capital") and is_sovereign(c.get("country")))
                )
                and (not country_code or c.get("country") == country_code)
                and (not continent_codes or c.get("country") in continent_codes)
            ]
            if not filtered:
                return {"error": "No locations match the given filters."}
            top = (
                filtered[:limit]
                if extremum == "max"
                else list(reversed(filtered))[:limit]
            )
            is_delta = _is_delta_metric(spec) or aggregation == "trend_slope"
            out_unit = _output_unit(spec, temperature_unit)
            if limit == 1:
                c = top[0]
                return {
                    "nearest_city": c["name"],
                    "lat": c["lat"],
                    "lon": c["lon"],
                    "value": _convert_temp(
                        round(c["value"], 3),
                        spec,
                        is_delta=is_delta,
                        target=temperature_unit,
                    ),
                    "unit": out_unit,
                }
            return {
                "results": [
                    {
                        "rank": i + 1,
                        "nearest_city": c["name"],
                        "lat": c["lat"],
                        "lon": c["lon"],
                        "value": _convert_temp(
                            round(c["value"], 3),
                            spec,
                            is_delta=is_delta,
                            target=temperature_unit,
                        ),
                        "unit": out_unit,
                    }
                    for i, c in enumerate(top)
                ]
            }

    effective_min_pop = max(min_population, 1000)
    candidates = location_index.iter_all(
        min_population=effective_min_pop,
        capitals_only=capital_only,
    )
    if country_code:
        candidates = [c for c in candidates if c.country_code == country_code]
    elif continent_codes:
        candidates = [c for c in candidates if c.country_code in continent_codes]

    if not candidates:
        return {"error": "No locations match the given filters."}

    unit = spec.get("unit", "unknown")
    scored: list[tuple[float, int | None, Any]] = []
    seen_cells: set[tuple[int, int]] = set()

    for city in candidates:
        cell_key = (round(city.lat * 4), round(city.lon * 4))
        if cell_key in seen_cells:
            continue
        seen_cells.add(cell_key)

        series_result = _get_metric_series(
            city.lat,
            city.lon,
            metric_id,
            tile_store,
            start_year=start_year,
            end_year=end_year,
            month_filter=month_filter,
        )
        if "error" in series_result:
            continue
        data = series_result.get("data", [])
        if not data:
            continue

        values = [d["value"] for d in data]
        years = [d["year"] for d in data]
        year_of_extreme: int | None = None

        if aggregation == "mean":
            score = float(np.mean(values))
        elif aggregation == "max":
            idx = int(np.argmax(values))
            score = float(values[idx])
            year_of_extreme = int(years[idx])
        elif aggregation == "min":
            idx = int(np.argmin(values))
            score = float(values[idx])
            year_of_extreme = int(years[idx])
        else:  # trend_slope (yearly only, guarded above)
            if len(values) < 2:
                continue
            slope = float(np.polyfit(years, values, 1)[0])
            score = slope * 10  # °C per decade

        scored.append((score, year_of_extreme, city))

    if not scored:
        return {
            "error": f"No data found for metric '{metric_id}' with the given filters."
        }

    scored.sort(key=lambda t: t[0], reverse=(extremum == "max"))
    top = scored[:limit]

    # trend_slope values are deltas (°C/decade); all other aggregations on a
    # delta metric are also deltas; absolute metrics with mean/max/min are absolute.
    is_delta = _is_delta_metric(spec) or aggregation == "trend_slope"
    out_unit = _output_unit(spec, temperature_unit)

    if limit == 1:
        score, year_of_extreme, city = top[0]
        result: dict = {
            "nearest_city": city.label,
            "alt_names": city.alt_names,
            "lat": city.lat,
            "lon": city.lon,
            "value": _convert_temp(
                round(score, 3), spec, is_delta=is_delta, target=temperature_unit
            ),
            "unit": out_unit,
        }
        if year_of_extreme is not None:
            result["year"] = year_of_extreme
        return result
    return {
        "results": [
            {
                "rank": i + 1,
                "nearest_city": city.label,
                "alt_names": city.alt_names,
                "lat": city.lat,
                "lon": city.lon,
                "value": _convert_temp(
                    round(score, 3), spec, is_delta=is_delta, target=temperature_unit
                ),
                "unit": out_unit,
                **({"year": year_of_extreme} if year_of_extreme is not None else {}),
            }
            for i, (score, year_of_extreme, city) in enumerate(top)
        ]
    }


def find_similar_locations(
    reference_name: str,
    metric_id: str,
    tile_store: TileDataStore,
    location_index: LocationIndex,
    limit: int = 5,
    temperature_unit: str = "C",
    country_name_to_code: dict[str, str] | None = None,
) -> dict:
    """
    Find cities whose long-term metric mean is closest to the reference city.
    Scans cities with population >= 100k.
    """
    spec = tile_store.metrics.get(metric_id)
    if spec is None:
        return {"error": f"Unknown metric_id: '{metric_id}'."}

    ref = resolve_location(reference_name, location_index, country_name_to_code)
    if "error" in ref:
        return ref

    ref_series = _get_metric_series(ref["lat"], ref["lon"], metric_id, tile_store)
    if "error" in ref_series:
        return ref_series

    ref_values = [d["value"] for d in ref_series.get("data", [])]
    if not ref_values:
        return {"error": f"No data for reference location '{reference_name}'."}
    ref_mean = float(np.mean(ref_values))

    unit = spec.get("unit", "unknown")
    candidates = location_index.iter_all(min_population=100_000)

    scored: list[tuple[float, float, Any]] = []
    for city in candidates:
        if abs(city.lat - ref["lat"]) < 0.13 and abs(city.lon - ref["lon"]) < 0.13:
            continue
        series = _get_metric_series(city.lat, city.lon, metric_id, tile_store)
        if "error" in series:
            continue
        values = [d["value"] for d in series.get("data", [])]
        if not values:
            continue
        mean = float(np.mean(values))
        scored.append((abs(mean - ref_mean), mean, city))

    if not scored:
        return {"error": "Could not compute similarity — no data for candidate cities."}

    scored.sort(key=lambda t: t[0])
    # similarity compares long-term means — always absolute temperatures
    is_delta = _is_delta_metric(spec)
    out_unit = _output_unit(spec, temperature_unit)
    return {
        "reference": ref["label"],
        "reference_lat": ref["lat"],
        "reference_lon": ref["lon"],
        "reference_mean": _convert_temp(
            round(ref_mean, 3), spec, is_delta=is_delta, target=temperature_unit
        ),
        "unit": out_unit,
        "similar_locations": [
            {
                "city": city.label,
                "lat": city.lat,
                "lon": city.lon,
                "value": _convert_temp(
                    round(mean, 3), spec, is_delta=is_delta, target=temperature_unit
                ),
                # delta between cities is always a difference (no +32 offset)
                "delta": _convert_temp(
                    round(delta, 3), spec, is_delta=True, target=temperature_unit
                ),
            }
            for delta, mean, city in scored[:limit]
        ],
    }


_MAJOR_OCEAN_IDS = frozenset(
    {
        "ocean:arctic_ocean",
        "ocean:indian_ocean",
        "ocean:north_atlantic_ocean",
        "ocean:south_atlantic_ocean",
        "ocean:north_pacific_ocean",
        "ocean:south_pacific_ocean",
        "ocean:southern_ocean",
    }
)


def find_extreme_region(
    metric_id: str,
    aggregation: str,
    extremum: str,
    tile_store: TileDataStore,
    region_type: str | None = None,
    continent: str | None = None,
    limit: int = 1,
    start_year: int | None = None,
    end_year: int | None = None,
    temperature_unit: str = "C",
) -> dict:
    """
    Find the region(s) with the highest or lowest aggregated value of a climate metric.
    Uses precomputed area-weighted regional aggregates (countries, continents, oceans, globe).
    """
    spec = tile_store.metrics.get(metric_id)
    if spec is None:
        return {"error": f"Unknown metric_id: '{metric_id}'."}
    if aggregation not in ("mean", "max", "min", "trend_slope"):
        return {
            "error": f"Unknown aggregation: '{aggregation}'. Use: mean, max, min, trend_slope."
        }
    if extremum not in ("max", "min"):
        return {"error": f"Unknown extremum: '{extremum}'. Use: max or min."}

    valid_region_types = {"country", "continent", "ocean", "globe"}
    if region_type and region_type not in valid_region_types:
        return {
            "error": f"Unknown region_type: '{region_type}'. Use: country, continent, ocean, globe."
        }

    continent_codes: frozenset[str] | None = None
    if continent:
        continent_codes = _resolve_continent(continent)
        if continent_codes is None:
            return {
                "error": (
                    f"Continent not recognised: '{continent}'. "
                    "Use one of: Africa, Antarctica, Asia, Europe, "
                    "North America, Oceania, South America."
                )
            }

    agg_data = tile_store.aggregates.get((metric_id, "mean"))
    if agg_data is None:
        return {
            "error": (
                f"Regional aggregates are not available for metric '{metric_id}'. "
                "Use get_region_metric_series for a known region instead."
            )
        }

    time_axis = agg_data["time_axis"]
    regions = agg_data["regions"]

    scored: list[tuple[float, str, dict]] = []
    for region_id, region_info in regions.items():
        rtype = region_info.get("type", "")
        if region_type and rtype != region_type:
            continue
        if rtype == "ocean" and region_id not in _MAJOR_OCEAN_IDS:
            continue
        if continent_codes and rtype == "country":
            # Extract ISO-2 code from "country:FR" → "FR"
            cc = region_id.split(":", 1)[-1] if ":" in region_id else ""
            if cc not in continent_codes:
                continue

        values = region_info["values"]
        years = [int(y) for y in time_axis]

        if start_year is not None or end_year is not None:
            pairs = [
                (y, v)
                for y, v in zip(years, values)
                if (start_year is None or y >= start_year)
                and (end_year is None or y <= end_year)
                and v is not None
            ]
        else:
            pairs = [(y, v) for y, v in zip(years, values) if v is not None]

        if not pairs:
            continue
        valid_years, valid_vals = zip(*pairs)
        arr = np.array(valid_vals, dtype=np.float64)

        if aggregation == "mean":
            score = float(np.mean(arr))
        elif aggregation == "max":
            score = float(np.max(arr))
        elif aggregation == "min":
            score = float(np.min(arr))
        else:  # trend_slope
            if len(arr) < 2:
                continue
            score = float(np.polyfit(list(valid_years), arr, 1)[0]) * 10

        scored.append((score, region_id, region_info))

    if not scored:
        return {
            "error": f"No regional data found for metric '{metric_id}' with the given filters."
        }

    scored.sort(key=lambda t: t[0], reverse=(extremum == "max"))
    top = scored[:limit]

    is_delta = _is_delta_metric(spec) or aggregation == "trend_slope"
    out_unit = _output_unit(spec, temperature_unit)

    if limit == 1:
        score, region_id, info = top[0]
        return {
            "region_id": region_id,
            "region_name": info["name"],
            "region_type": info["type"],
            "value": _convert_temp(
                round(score, 3), spec, is_delta=is_delta, target=temperature_unit
            ),
            "unit": out_unit,
        }
    return {
        "results": [
            {
                "rank": i + 1,
                "region_id": region_id,
                "region_name": info["name"],
                "region_type": info["type"],
                "value": _convert_temp(
                    round(score, 3), spec, is_delta=is_delta, target=temperature_unit
                ),
                "unit": out_unit,
            }
            for i, (score, region_id, info) in enumerate(top)
        ]
    }


def get_region_metric_series(
    region_id: str,
    metric_id: str,
    aggregation: str,
    tile_store: TileDataStore,
    start_year: int | None = None,
    end_year: int | None = None,
    temperature_unit: str = "C",
    month_filter: list[int] | None = None,
    aggregate_by_year: bool = False,
) -> dict:
    """
    Return the precomputed time series of a climate metric aggregated over a
    country, continent, ocean, or the whole globe.

    region_id: "country:FR", "continent:europe", "ocean:indian_ocean", "globe",
               or a human-readable name like "France", "Europe", "Indian Ocean".
    aggregation: "mean" (area-weighted), "min", or "max" across the region's cells.
    month_filter: months to keep from a monthly metric, e.g. [6] for June only.
    aggregate_by_year: collapse the remaining months into one value per year.

    The last two mirror get_metric_series. Without them a monthly metric can
    only be fetched in full — 47 years of months is ~560 points, which alone
    exceeds the request budget of the smaller models and fails the turn.
    """
    spec = tile_store.metrics.get(metric_id)
    if spec is None:
        return {"error": f"Unknown metric_id: '{metric_id}'."}
    if (
        aggregation not in ("mean", "min", "max")
        and (
            metric_id,
            aggregation,
        )
        not in tile_store.aggregates
    ):
        return {
            "error": f"Unknown aggregation: '{aggregation}'. Use: mean, min, or max."
        }

    agg_data = tile_store.aggregates.get((metric_id, aggregation))
    if agg_data is None:
        supported = sorted(
            {agg for (m, agg) in tile_store.aggregates if m == metric_id}
        )
        if supported:
            return {
                "error": (
                    f"Regional aggregates for '{metric_id}' with aggregation '{aggregation}' "
                    f"are not available. Supported aggregations: {supported}."
                )
            }
        return {
            "error": (
                f"Regional aggregates are not available for metric '{metric_id}'. "
                f"Use get_metric_series for a specific location instead."
            )
        }

    # Resolve region_id (accept human-readable names)
    resolved = _resolve_region_id(region_id, tile_store, metric_id, aggregation)
    if resolved is None:
        available_types = sorted(
            {info["type"] for info in agg_data["regions"].values()}
        )
        return {
            "error": (
                f"Region not found: '{region_id}'. "
                f"Available region types: {available_types}. "
                "For countries use ISO 3166-1 alpha-2 code or full English name "
                "(e.g. 'country:FR' or 'France'). "
                "For continents: africa, antarctica, asia, europe, north_america, oceania, south_america. "
                "For oceans use the natural name (e.g. 'ocean:indian_ocean' or 'Indian Ocean'). "
                "For global use 'globe'."
            )
        }

    region_info = agg_data["regions"][resolved]
    time_axis = agg_data["time_axis"]
    values = region_info["values"]

    # Apply year filter
    if start_year is not None or end_year is not None:
        filtered = [
            (y, v)
            for y, v in zip(time_axis, values)
            if (start_year is None or int(str(y)[:4]) >= start_year)
            and (end_year is None or int(str(y)[:4]) <= end_year)
        ]
        if filtered:
            time_axis, values = zip(*filtered)
            time_axis = list(time_axis)
            values = list(values)
        else:
            time_axis, values = [], []

    # Month filter / yearly rollup, for monthly axes only ("YYYY-MM").
    monthly = bool(time_axis) and len(str(time_axis[0])) == 7
    if monthly and month_filter:
        wanted = {int(m) for m in month_filter}
        kept = [(y, v) for y, v in zip(time_axis, values) if int(str(y)[5:7]) in wanted]
        time_axis = [y for y, _ in kept]
        values = [v for _, v in kept]
    if monthly and aggregate_by_year:
        by_year: dict[str, list[float]] = {}
        for y, v in zip(time_axis, values):
            if v is not None:
                by_year.setdefault(str(y)[:4], []).append(v)
        time_axis = sorted(by_year)
        values = [sum(by_year[y]) / len(by_year[y]) for y in time_axis]

    # Unit conversion
    is_delta = _is_delta_metric(spec)
    out_unit = _output_unit(spec, temperature_unit)
    if temperature_unit == "F" and spec.get("unit") == "C":
        values = [
            (
                _convert_temp(v, spec, is_delta=is_delta, target="F")
                if v is not None
                else None
            )
            for v in values
        ]

    region_name = region_info.get("name", resolved)
    result = {
        "region_id": resolved,
        "region_name": region_name,
        # "location" mirrors get_metric_series so chart builders can use the same field
        "location": region_name,
        "region_type": region_info["type"],
        "metric_id": metric_id,
        "aggregation": aggregation,
        "unit": out_unit,
        "cell_count": region_info.get("cell_count"),
        "data": [{"year": y, "value": v} for y, v in zip(time_axis, values)],
        **({"month_filter": list(month_filter)} if monthly and month_filter else {}),
    }

    # Backstop: even with the filters above a caller can still ask for a full
    # daily or monthly series, which on its own overruns the smaller models'
    # per-request budget and kills the turn. Summarise rather than fail, and
    # say plainly what was left out so the model does not read the trimmed
    # series as the whole record.
    if len(result["data"]) > _MAX_SERIES_POINTS:
        result = _summarise_long_series(result, out_unit)
    return result
