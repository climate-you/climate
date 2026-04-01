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

from climate_api.store.location_index import LocationIndex
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
        metrics.append({
            "metric_id": metric_id,
            "description": spec.get("title", metric_id),
            "unit": spec.get("unit", "unknown"),
            "available_range": date_range,
            "source": spec.get("source", {}).get("_dataset_ref", "unknown"),
        })
    return {"metrics": metrics}


def resolve_location(name: str, location_index: LocationIndex) -> dict:
    """Resolve a place name to coordinates. Internal helper — not exposed as a tool."""
    name = name.strip().strip("*")
    hits = location_index.autocomplete(name, limit=1)
    if not hits and "," in name:
        # Retry with just the city part — handles "London, UK", "New York City, USA", etc.
        city_only = name.split(",", 1)[0].strip()
        hits = location_index.autocomplete(city_only, limit=1)
    if not hits:
        return {"error": f"Location not found: '{name}'"}
    h = hits[0]
    return {"lat": h.lat, "lon": h.lon, "label": h.label, "country": h.country_code}


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
        return {"error": f"No data at lat={lat}, lon={lon} for metric '{metric_id}' (ocean/missing cell)."}

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
                "metric_id": metric_id, "lat": lat, "lon": lon, "unit": unit,
                "data": data,
                "note": f"Annual means for months {month_filter}.",
            }

        return {"metric_id": metric_id, "lat": lat, "lon": lon, "unit": unit, "data": data}

    else:
        # yearly axis — int years
        years = [int(a) for a in axis]
        pairs = [(y, float(v)) for y, v in zip(years, vec)]
        available_min, available_max = years[0], years[-1]

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
) -> dict:
    """Tool-facing wrapper: resolves location name then fetches the metric series."""
    loc = resolve_location(location, location_index)
    if "error" in loc:
        return loc
    result = _get_metric_series(
        loc["lat"], loc["lon"], metric_id, tile_store,
        start_year=start_year, end_year=end_year, month_filter=month_filter,
        aggregate_by_year=aggregate_by_year,
    )
    if "error" not in result:
        result["location"] = loc["label"]
        spec = tile_store.metrics.get(metric_id, {})
        if temperature_unit == "F" and spec.get("unit") == "C":
            is_delta = _is_delta_metric(spec)
            result["data"] = [
                {**entry, "value": _convert_temp(entry["value"], spec, is_delta=is_delta, target="F")}
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
        return {"error": f"Unknown aggregation: '{aggregation}'. Use: mean, max, min, trend_slope."}
    if extremum not in ("max", "min"):
        return {"error": f"Unknown extremum: '{extremum}'. Use: max or min."}

    time_axis_type = spec.get("time_axis", "yearly")
    if aggregation == "trend_slope" and time_axis_type == "monthly":
        return {"error": "trend_slope is not supported for monthly metrics. Use mean, max, or min."}

    # Resolve country filter
    country_code: str | None = None
    if country:
        country_code = country_name_to_code.get(country.strip().casefold())
        if country_code is None:
            return {"error": f"Country not recognised: '{country}'. Use the full English country name."}

    effective_min_pop = max(min_population, 1000)
    candidates = location_index.iter_all(
        min_population=effective_min_pop,
        capitals_only=capital_only,
    )
    if country_code:
        candidates = [c for c in candidates if c.country_code == country_code]

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
            city.lat, city.lon, metric_id, tile_store,
            start_year=start_year, end_year=end_year, month_filter=month_filter,
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
        return {"error": f"No data found for metric '{metric_id}' with the given filters."}

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
            "lat": city.lat,
            "lon": city.lon,
            "value": _convert_temp(round(score, 3), spec, is_delta=is_delta, target=temperature_unit),
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
                "lat": city.lat,
                "lon": city.lon,
                "value": _convert_temp(round(score, 3), spec, is_delta=is_delta, target=temperature_unit),
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
) -> dict:
    """
    Find cities whose long-term metric mean is closest to the reference city.
    Scans cities with population >= 100k.
    """
    spec = tile_store.metrics.get(metric_id)
    if spec is None:
        return {"error": f"Unknown metric_id: '{metric_id}'."}

    ref = resolve_location(reference_name, location_index)
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
        "reference_mean": _convert_temp(round(ref_mean, 3), spec, is_delta=is_delta, target=temperature_unit),
        "unit": out_unit,
        "similar_locations": [
            {
                "city": city.label,
                "lat": city.lat,
                "lon": city.lon,
                "value": _convert_temp(round(mean, 3), spec, is_delta=is_delta, target=temperature_unit),
                # delta between cities is always a difference (no +32 offset)
                "delta": _convert_temp(round(delta, 3), spec, is_delta=True, target=temperature_unit),
            }
            for delta, mean, city in scored[:limit]
        ],
    }
