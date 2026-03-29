#!/usr/bin/env python3
"""
Phase -1 CLI proof-of-concept: validates the Groq agentic loop with mock tools.

Requirements:
    (groq is already installed in the climate conda environment)

Usage (Groq):
    export GROQ_API_KEY=gsk_...
    export GROQ_MODEL=llama-3.1-8b-instant   # optional; default: llama-3.3-70b-versatile
    python experiments/chat_poc.py

Usage (Ollama local):
    ollama pull llama3.1:8b && ollama serve
    export OLLAMA_BASE_URL=http://localhost:11434/v1
    python experiments/chat_poc.py

Iteration 1 (MOCK_TOOLS = True):  hardcoded stubs, proves the agentic loop works.
Iteration 2 (MOCK_TOOLS = False): real TileDataStore + LocationIndex from data/.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "")

if _OLLAMA_BASE_URL:
    MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
else:
    MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

MAX_STEPS = 5
MOCK_TOOLS = False  # Set False to use real TileDataStore + LocationIndex
MAX_HISTORY_TURNS = 3  # keep last N user+assistant pairs in multi-turn mode


def _make_client(api_key: str | None = None):
    """Return a Groq or Ollama (OpenAI-compatible) chat client based on env vars."""
    if _OLLAMA_BASE_URL:
        try:
            from openai import OpenAI
        except ImportError:
            print(
                "Error: 'openai' package not installed. Run: pip install openai",
                file=sys.stderr,
            )
            sys.exit(1)
        return OpenAI(base_url=_OLLAMA_BASE_URL, api_key="ollama")
    else:
        try:
            from groq import Groq
        except ImportError:
            print(
                "Error: 'groq' package not installed. Run: pip install groq",
                file=sys.stderr,
            )
            sys.exit(1)
        return Groq(api_key=api_key)


REPO_ROOT = Path(__file__).parent.parent

_SYSTEM_PROMPT_BASE = """\
You are a climate data assistant. You answer questions about historical climate data \
using the tools available to you.

Rules:
- Always call the tools to retrieve data before answering — never guess numerical values.
- Use the metric catalogue below to choose the correct metric_id directly.
- Pass a place name directly to get_metric_series — it resolves the location internally. \
Never guess or supply your own coordinates.
- Multiple independent tool calls can be made in a single step. When comparing multiple \
locations, call get_metric_series for all of them in one parallel step.
- When the question asks for a specific year or a specific time range, always pass \
start_year and end_year to get_metric_series so the result is focused. For example, \
to get the 2020 value, pass start_year=2020, end_year=2020. Only omit year bounds when \
you need the full historical series (e.g. to find the hottest year in a range).

Spatial precision: climate data is at 0.25° resolution (~28 km per cell). A data point \
covers a geographic area, not a precise city. Prefer phrasing like "in the Tokyo area" \
rather than "in Tokyo specifically".

Two-tier answers: for questions about *why* something is happening, you may draw on \
general climate science knowledge — but clearly label it: "Beyond what our dataset shows, \
climate science suggests..." and hedge appropriately. Never state general knowledge with \
the same certainty as a tool result.

Data availability: if the tool returns an error saying the requested time period is not available, \
check whether the requested year is in the future (beyond today's date). \
If it is a future year, do not retry — instead explain that our dataset only covers historical data \
up to the most recent available year and state what that year is. \
If the requested time period is in the past but not yet available, retry with the most recent available period.

Finding the hottest or coldest year at a specific location: use get_metric_series (not \
find_extreme_location) to retrieve the full series for that location, then identify the \
year with the maximum or minimum value from the returned data.

Reporting time periods: always state the explicit year or date from the data you retrieved — \
never echo the user's relative phrasing like "last year" or "last month". Say "in 2024" not \
"last year". If the year or month you fetched is the last one listed in the metric catalogue, \
add "(most recent available in our dataset)" after the year. \
Example: "The mean temperature in the Paris area in 2024 (most recent available in our dataset) was 14.9°C."

Respond in English only. Be concise and always include specific numbers from the data.
Never mention tool names, function names, or raw JSON in your final response. \
Present findings as natural language — e.g. "The temperature in Paris in 2020 was 12.8°C", \
not "I called get_metric_series to find that...".

Today's date: {current_date}. Use this to interpret relative time expressions like "last year" or "this decade".

Available metrics:
{metric_catalogue}
"""


def _format_metric_catalogue(metrics: list[dict]) -> str:
    lines = []
    for m in metrics:
        line = f"- {m['metric_id']}: {m['description']} ({m['unit']}), available {m['available_range']}, source: {m['source']}"
        if m.get("note"):
            line += f" — {m['note']}"
        lines.append(line)
    return "\n".join(lines)


def build_system_prompt(metrics: list[dict]) -> str:
    import datetime

    current_date = datetime.date.today().strftime("%Y-%m-%d")
    return _SYSTEM_PROMPT_BASE.format(
        current_date=current_date,
        metric_catalogue=_format_metric_catalogue(metrics),
    )


# ---------------------------------------------------------------------------
# Tool schemas (OpenAI function-calling format, compatible with Groq)
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "find_extreme_location",
            "description": (
                "Find the location(s) with the highest or lowest value of a climate metric. "
                "Use for questions like 'which city is the hottest?', 'top 10 warmest large cities', "
                "'hottest capital', 'warmest city in France'. "
                "Returns a single result when limit=1, or a ranked list when limit>1. "
                "Use min_population to restrict to large cities (e.g. 1000000 for megacities). "
                "Use capital_only=true to restrict to national capital cities. "
                "Use country to restrict to a specific country (full English name, e.g. 'France')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "metric_id": {
                        "type": "string",
                        "description": "Metric ID from the catalogue",
                    },
                    "aggregation": {
                        "type": "string",
                        "enum": ["mean", "max", "min", "trend_slope"],
                        "description": (
                            "How to aggregate the time series per location: "
                            "mean (average over the period), max, min, or trend_slope (°C/decade)."
                        ),
                    },
                    "extremum": {
                        "type": "string",
                        "enum": ["max", "min"],
                        "description": "Whether to find the location with the highest (max) or lowest (min) value.",
                    },
                    "start_year": {
                        "type": "integer",
                        "description": "First year to include (inclusive).",
                    },
                    "end_year": {
                        "type": "integer",
                        "description": "Last year to include (inclusive).",
                    },
                    "month_filter": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Months to include, e.g. [12, 1, 2] for winter. Only for monthly metrics.",
                    },
                    "country": {
                        "type": "string",
                        "description": "Restrict to cities in this country (full English name, e.g. 'France').",
                    },
                    "capital_only": {
                        "type": "boolean",
                        "description": "If true, only consider national capital cities.",
                    },
                    "min_population": {
                        "type": "integer",
                        "description": (
                            "Only consider cities with at least this population. "
                            "Use 1000000 for 'large cities', 500000 for 'major cities'."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of results to return (default 1). Use >1 for ranking questions.",
                    },
                },
                "required": ["metric_id", "aggregation", "extremum"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_similar_locations",
            "description": (
                "Find cities whose long-term mean for a metric is closest to a reference city. "
                "Use for questions like 'which cities have a similar climate to London?' or "
                "'cities with similar temperatures to Tokyo'. "
                "Scans cities with population >= 100k."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reference_name": {
                        "type": "string",
                        "description": "Name of the reference city. Use the city name only, e.g. 'London' or 'Tokyo' — do not append country codes.",
                    },
                    "metric_id": {
                        "type": "string",
                        "description": "Metric ID to use for comparison (e.g. t2m_yearly_mean_c).",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of similar cities to return (default 5).",
                    },
                },
                "required": ["reference_name", "metric_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_metric_series",
            "description": (
                "Return a time-series of a climate metric for a named location. "
                "Filter by year range and/or specific months (1=Jan … 12=Dec). "
                "The returned data array can be used to compute means, trends, extremes, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": (
                            "City or place name, e.g. 'Tokyo' or 'Paris, France'. "
                            "When the user asks about 'here' or 'this location', use the label "
                            "from the map context exactly as provided."
                        ),
                    },
                    "metric_id": {
                        "type": "string",
                        "description": "Metric ID from the catalogue",
                    },
                    "start_year": {
                        "type": "integer",
                        "description": "First year to include (inclusive)",
                    },
                    "end_year": {
                        "type": "integer",
                        "description": "Last year to include (inclusive)",
                    },
                    "month_filter": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": (
                            "Months to include, e.g. [12, 1, 2] for winter. "
                            "Only valid for monthly metrics. Omit for annual metrics."
                        ),
                    },
                    "aggregate_by_year": {
                        "type": "boolean",
                        "description": (
                            "When true and month_filter is set, return one annual mean per year "
                            "instead of individual monthly records. Use for trend questions "
                            "spanning multiple years. Omit when per-month detail is needed."
                        ),
                    },
                },
                "required": ["location", "metric_id"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Mock tool implementations (iteration 1)
# ---------------------------------------------------------------------------

_MOCK_LOCATIONS: dict[str, dict] = {
    "paris": {"lat": 48.85, "lon": 2.35, "label": "Paris, France", "country": "FR"},
    "tokyo": {"lat": 35.68, "lon": 139.69, "label": "Tokyo, Japan", "country": "JP"},
    "new york": {
        "lat": 40.71,
        "lon": -74.01,
        "label": "New York, USA",
        "country": "US",
    },
    "london": {"lat": 51.51, "lon": -0.13, "label": "London, UK", "country": "GB"},
    "sydney": {
        "lat": -33.87,
        "lon": 151.21,
        "label": "Sydney, Australia",
        "country": "AU",
    },
}

# A single illustrative yearly series (same values for all locations in mock mode)
_MOCK_YEARLY_VALUES = [
    11.8,
    12.1,
    11.9,
    12.3,
    12.0,
    12.4,
    12.2,
    12.6,
    12.3,
    12.7,
    12.5,
    12.9,
    12.6,
    13.0,
    12.8,
    13.1,
    12.9,
    13.3,
    13.0,
    13.4,
    13.2,
    13.5,
    13.3,
    13.7,
    13.5,
    13.8,
    13.6,
    13.9,
    13.7,
    14.0,
    14.1,
    14.0,
    14.2,
    14.3,
    14.1,
    14.4,
    14.2,
    14.5,
    14.3,
    14.6,
    14.4,
    14.7,
    14.5,
    14.8,
    14.6,
    14.9,
]
_MOCK_YEARLY_AXIS = list(range(1979, 1979 + len(_MOCK_YEARLY_VALUES)))

_MOCK_METRICS = [
    {
        "metric_id": "t2m_yearly_mean_c",
        "description": "Annual mean 2m air temperature",
        "unit": "°C",
        "available_range": "1979-2024",
        "source": "ERA5 reanalysis",
    },
    {
        "metric_id": "t2m_monthly_mean_c",
        "description": "Monthly mean 2m air temperature",
        "unit": "°C",
        "available_range": "1979-2024",
        "source": "ERA5 reanalysis",
        "note": "Use month_filter to select specific months",
    },
]


def _mock_list_available_metrics() -> dict:
    return {"metrics": _MOCK_METRICS}


def _mock_resolve_location(name: str) -> dict:
    key = name.lower().strip()
    for k, v in _MOCK_LOCATIONS.items():
        if k in key or key in k:
            return v
    return {
        "error": f"Location not found in mock data: '{name}'. Try: Paris, Tokyo, New York, London, Sydney."
    }


def _mock_get_metric_series(
    lat: float,
    lon: float,
    metric_id: str,
    start_year: int | None = None,
    end_year: int | None = None,
    month_filter: list[int] | None = None,
) -> dict:
    if metric_id not in ("t2m_yearly_mean_c", "t2m_monthly_mean_c"):
        return {
            "error": f"Unknown metric_id: '{metric_id}'. Call list_available_metrics for valid IDs."
        }

    available_min, available_max = _MOCK_YEARLY_AXIS[0], _MOCK_YEARLY_AXIS[-1]

    pairs = list(zip(_MOCK_YEARLY_AXIS, _MOCK_YEARLY_VALUES))
    if start_year is not None:
        pairs = [(y, v) for y, v in pairs if y >= start_year]
    if end_year is not None:
        pairs = [(y, v) for y, v in pairs if y <= end_year]

    if not pairs:
        return {
            "error": (
                f"No data available for the requested range. "
                f"Available range for {metric_id}: {available_min}-{available_max}."
            )
        }

    note = "mock data — values are illustrative only, not tied to this location"
    if month_filter:
        note += f"; month_filter {month_filter} ignored in mock mode (yearly series returned)"

    return {
        "metric_id": metric_id,
        "lat": lat,
        "lon": lon,
        "unit": "°C",
        "note": note,
        "data": [{"year": y, "value": round(v, 2)} for y, v in pairs],
    }


# ---------------------------------------------------------------------------
# Real tool implementations (iteration 2)
# ---------------------------------------------------------------------------

_real_store = None
_real_location_index = None


def _init_real_tools() -> None:
    global _real_store, _real_location_index
    sys.path.insert(0, str(REPO_ROOT))
    from climate_api.store.tile_data_store import TileDataStore
    from climate_api.store.location_index import LocationIndex

    tiles_root = REPO_ROOT / "data" / "releases" / "dev" / "series"
    locations_index_csv = REPO_ROOT / "data" / "locations" / "locations.index.csv"

    if not tiles_root.exists():
        raise RuntimeError(f"Tiles root not found: {tiles_root}")
    if not locations_index_csv.exists():
        raise RuntimeError(f"Location index not found: {locations_index_csv}")

    _real_store = TileDataStore.discover(tiles_root)
    _real_location_index = LocationIndex(locations_index_csv)
    print(f"  [real tools] TileDataStore loaded from {tiles_root}")
    print(f"  [real tools] LocationIndex loaded from {locations_index_csv}")


def _real_list_available_metrics() -> dict:
    metrics = []
    for metric_id, spec in _real_store.metrics.items():
        axis = _real_store.axis(metric_id)
        if axis:
            date_range = f"{axis[0]}-{axis[-1]}"
        else:
            date_range = "unknown"
        metrics.append(
            {
                "metric_id": metric_id,
                "description": spec.get("label", metric_id),
                "unit": spec.get("unit", "unknown"),
                "available_range": date_range,
                "source": spec.get("dataset_id", "unknown"),
            }
        )
    return {"metrics": metrics}


def _real_resolve_location(name: str) -> dict:
    hits = _real_location_index.autocomplete(name, limit=1)
    if not hits and "," in name:
        # Retry with just the city part — handles abbreviations like "London, UK"
        # or "New York City, USA" that the index doesn't recognise as country qualifiers.
        city_only = name.split(",", 1)[0].strip()
        hits = _real_location_index.autocomplete(city_only, limit=1)
    if not hits:
        return {"error": f"Location not found: '{name}'"}
    h = hits[0]
    return {"lat": h.lat, "lon": h.lon, "label": h.label, "country": h.country_code}


def _real_get_metric_series(
    lat: float,
    lon: float,
    metric_id: str,
    start_year: int | None = None,
    end_year: int | None = None,
    month_filter: list[int] | None = None,
    aggregate_by_year: bool = False,
) -> dict:
    spec = _real_store.metrics.get(metric_id)
    if spec is None:
        return {
            "error": f"Unknown metric_id: '{metric_id}'. Call list_available_metrics for valid IDs."
        }

    try:
        vec = _real_store.try_get_metric_vector(metric_id, lat, lon)
    except FileNotFoundError as e:
        return {"error": str(e)}

    if vec is None:
        return {
            "error": f"No data at lat={lat}, lon={lon} for metric {metric_id} (ocean/missing cell)."
        }

    axis = _real_store.axis(metric_id)
    if len(axis) != len(vec):
        return {"error": f"Axis/vector length mismatch: {len(axis)} vs {len(vec)}"}

    time_axis_type = spec.get("time_axis", "yearly")
    unit = spec.get("unit", "unknown")

    if time_axis_type == "monthly":
        data: list[dict[str, int | float]] = []
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

        return {
            "metric_id": metric_id,
            "lat": lat,
            "lon": lon,
            "unit": unit,
            "data": data,
        }

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


def _real_get_metric_series_by_location(
    location: str,
    metric_id: str,
    start_year: int | None = None,
    end_year: int | None = None,
    month_filter: list[int] | None = None,
    aggregate_by_year: bool = False,
) -> dict:
    """Tool-facing wrapper: resolves location name then fetches the metric series."""
    loc = _real_resolve_location(location)
    if "error" in loc:
        return loc
    result = _real_get_metric_series(
        loc["lat"], loc["lon"], metric_id,
        start_year=start_year, end_year=end_year, month_filter=month_filter,
        aggregate_by_year=aggregate_by_year,
    )
    if "error" not in result:
        result["location"] = loc["label"]
    return result


# Country name → code lookup (loaded lazily from country_names.json)
_country_code_by_name: dict[str, str] | None = None


def _get_country_code(name: str) -> str | None:
    global _country_code_by_name
    if _country_code_by_name is None:
        p = REPO_ROOT / "data" / "locations" / "country_names.json"
        if p.exists():
            raw: dict[str, str] = json.loads(p.read_text(encoding="utf-8"))
            # raw maps code → name; invert to name → code (case-folded)
            _country_code_by_name = {v.casefold(): k for k, v in raw.items()}
        else:
            _country_code_by_name = {}
    return _country_code_by_name.get(name.strip().casefold())


def _real_find_extreme_location(
    metric_id: str,
    aggregation: str,
    extremum: str,
    start_year: int | None = None,
    end_year: int | None = None,
    month_filter: list[int] | None = None,
    country: str | None = None,
    capital_only: bool = False,
    min_population: int = 0,
    limit: int = 1,
) -> dict:
    """
    Scan candidate cities, compute an aggregation for each, return the
    top `limit` cities ranked by the aggregation value.

    NOTE (PoC): scans per-city tile reads — suitable for filtered queries
    (capital_only, country, large min_population). For global unfiltered
    queries this is slow; production should use a pre-aggregated grid scan.
    """
    import numpy as np

    if metric_id not in _real_store.metrics:
        return {
            "error": f"Unknown metric_id: '{metric_id}'. Call list_available_metrics for valid IDs."
        }
    if aggregation not in ("mean", "max", "min", "trend_slope"):
        return {
            "error": f"Unknown aggregation: '{aggregation}'. Use: mean, max, min, trend_slope."
        }
    if extremum not in ("max", "min"):
        return {"error": f"Unknown extremum: '{extremum}'. Use: max or min."}

    # Resolve country filter
    country_code: str | None = None
    if country:
        country_code = _get_country_code(country)
        if country_code is None:
            return {
                "error": f"Country not recognised: '{country}'. Use the full English country name."
            }

    # Build candidate list
    effective_min_pop = max(min_population, 1000)  # always exclude micro-villages
    candidates = _real_location_index.iter_all(
        min_population=effective_min_pop,
        capitals_only=capital_only,
    )
    if country_code:
        candidates = [c for c in candidates if c.country_code == country_code]

    if not candidates:
        return {"error": "No locations match the given filters."}

    unit = _real_store.metrics[metric_id].get("unit", "unknown")
    scored: list[tuple[float, object]] = []
    seen_cells: set[tuple[int, int]] = (
        set()
    )  # deduplicate cities that fall in the same grid cell

    for city in candidates:
        # Snap to 0.25° grid cell to avoid returning the same cell multiple times
        cell_key = (round(city.lat * 4), round(city.lon * 4))
        if cell_key in seen_cells:
            continue
        seen_cells.add(cell_key)

        series_result = _real_get_metric_series(
            city.lat,
            city.lon,
            metric_id,
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
        else:  # trend_slope
            if len(values) < 2:
                continue
            slope = float(np.polyfit(years, values, 1)[0])
            score = slope * 10  # convert to per-decade

        scored.append((score, year_of_extreme, city))

    if not scored:
        return {
            "error": f"No data found for metric '{metric_id}' with the given filters."
        }

    scored.sort(key=lambda t: t[0], reverse=(extremum == "max"))
    top = scored[:limit]

    if limit == 1:
        score, year_of_extreme, city = top[0]
        result: dict = {
            "nearest_city": city.label,
            "lat": city.lat,
            "lon": city.lon,
            "value": round(score, 3),
            "unit": unit,
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
                "value": round(score, 3),
                "unit": unit,
                **({"year": year_of_extreme} if year_of_extreme is not None else {}),
            }
            for i, (score, year_of_extreme, city) in enumerate(top)
        ]
    }


def _real_find_similar_locations(
    reference_name: str,
    metric_id: str,
    limit: int = 5,
) -> dict:
    """
    Find cities whose long-term metric mean is closest to the reference city.
    Scans cities with population >= 100k to keep tile reads manageable.
    """
    import numpy as np

    if metric_id not in _real_store.metrics:
        return {
            "error": f"Unknown metric_id: '{metric_id}'. Call list_available_metrics for valid IDs."
        }

    ref = _real_resolve_location(reference_name)
    if "error" in ref:
        return ref

    ref_series = _real_get_metric_series(ref["lat"], ref["lon"], metric_id)
    if "error" in ref_series:
        return ref_series

    ref_values = [d["value"] for d in ref_series.get("data", [])]
    if not ref_values:
        return {"error": f"No data for reference location '{reference_name}'."}
    ref_mean = float(np.mean(ref_values))

    unit = _real_store.metrics[metric_id].get("unit", "unknown")
    candidates = _real_location_index.iter_all(min_population=100_000)

    scored: list[tuple[float, float, object]] = []  # (delta, mean, city)
    for city in candidates:
        # Skip the reference cell itself
        if abs(city.lat - ref["lat"]) < 0.13 and abs(city.lon - ref["lon"]) < 0.13:
            continue
        series = _real_get_metric_series(city.lat, city.lon, metric_id)
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
    top = scored[:limit]

    return {
        "reference": ref["label"],
        "reference_lat": ref["lat"],
        "reference_lon": ref["lon"],
        "reference_mean": round(ref_mean, 3),
        "unit": unit,
        "similar_locations": [
            {
                "city": city.label,
                "lat": city.lat,
                "lon": city.lon,
                "value": round(mean, 3),
                "delta": round(delta, 3),
            }
            for delta, mean, city in top
        ],
    }


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------

_TOOL_ARGUMENT_CASTS = {
    "get_metric_series": {
        "start_year": int,
        "end_year": int,
        "month_filter": lambda values: [int(v) for v in values],
        "aggregate_by_year": bool,
    },
    "find_extreme_location": {
        "start_year": int,
        "end_year": int,
        "month_filter": lambda values: [int(v) for v in values],
        "capital_only": bool,
        "min_population": int,
        "limit": int,
    },
    "find_similar_locations": {
        "start_year": int,
        "end_year": int,
        "month_filter": lambda values: [int(v) for v in values],
        "country": str,
        "limit": int,
    },
}


def _coerce_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    return bool(value)


def _normalize_tool_arguments(name: str, arguments: dict) -> dict:
    casts = _TOOL_ARGUMENT_CASTS.get(name)
    if not casts:
        return arguments

    normalized = dict(arguments)
    for key, caster in casts.items():
        if key not in normalized or normalized[key] is None:
            continue

        value = normalized[key]
        try:
            if caster is bool:
                normalized[key] = _coerce_bool(value)
            else:
                normalized[key] = caster(value)
        except (TypeError, ValueError):
            # Leave invalid values intact so the downstream tool can return a
            # user-facing error rather than crashing dispatch.
            pass

    return normalized


def dispatch_tool(name: str, arguments: dict) -> str:
    arguments = _normalize_tool_arguments(name, arguments)

    try:
        if MOCK_TOOLS:
            if name == "get_metric_series":
                # Mock: resolve location name then delegate to lat/lon stub
                loc_name = arguments.pop("location", "unknown")
                loc = _mock_resolve_location(loc_name)
                if "error" in loc:
                    result = loc
                else:
                    result = _mock_get_metric_series(loc["lat"], loc["lon"], **arguments)
                    if "error" not in result:
                        result["location"] = loc["label"]
            else:
                result = {"error": f"Unknown tool: {name}"}
        else:
            if name == "get_metric_series":
                result = _real_get_metric_series_by_location(**arguments)
            elif name == "find_extreme_location":
                result = _real_find_extreme_location(**arguments)
            elif name == "find_similar_locations":
                result = _real_find_similar_locations(**arguments)
            else:
                result = {"error": f"Unknown tool: {name}"}
    except Exception as exc:
        result = {"error": f"Tool '{name}' raised an unexpected error: {exc}. Check that all arguments have the correct types."}

    return json.dumps(result)


# ---------------------------------------------------------------------------
# Text-based tool call parser (fallback for when the model generates tool
# calls as plain text instead of structured tool_calls)
# ---------------------------------------------------------------------------


def _parse_text_tool_calls(text: str) -> list[dict]:
    """
    Llama models sometimes output tool calls as text in various malformed formats:
      <function=name{...}</function>
      <function(name>...)</function>
      <function=name={"key": val}</function>
    This parser extracts the function name and JSON arguments from any variant.
    Returns a list of dicts with keys: id, name, arguments (as a dict).
    """
    import re

    # Capture everything between <function...> and </function>, non-greedy
    matches = re.findall(r"<function[^>]*>(.*?)</function>", text, re.DOTALL)
    calls = []
    for raw in matches:
        raw = raw.strip().rstrip(")")
        # The function name precedes the first '{'; strip any leading =, (, "
        brace = raw.find("{")
        if brace == -1:
            continue
        name = raw[:brace].lstrip('=("').rstrip('=("" ')
        try:
            arguments = json.loads(raw[brace:])
        except json.JSONDecodeError:
            continue
        calls.append(
            {
                "id": f"parsed_{name}_{len(calls)}",
                "name": name,
                "arguments": arguments,
            }
        )
    return calls


# ---------------------------------------------------------------------------
# Agentic loop
# ---------------------------------------------------------------------------


def run_agent(
    client,
    user_message: str,
    system_prompt: str,
    history: list[tuple[str, str]] | None = None,
) -> str | None:
    """Run the agentic loop and return the final answer text, or None on error."""
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    for role, text in (history or []):
        messages.append({"role": role, "content": text})
    messages.append({"role": "user", "content": user_message})

    retried = False  # allow at most one retry per conversation
    retry_count = 0
    step_usages: list[dict] = []

    for step in range(1, MAX_STEPS + 1):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
                parallel_tool_calls=True,
                temperature=0,
            )
        except Exception as exc:
            error_body = getattr(exc, "body", {}) or {}
            error_info = error_body.get("error") or {}
            error_code = error_info.get("code", "")
            error_msg = error_info.get("message", str(exc))

            if error_code == "tool_use_failed" and not retried:
                # Groq rejected a malformed tool call. Append a short correction
                # and retry once — the nudge is enough to get the model back on track.
                retried = True
                retry_count += 1
                print(f"  [step {step}] malformed tool call, retrying...", flush=True)
                messages.append(
                    {
                        "role": "user",
                        "content": "Your previous tool call was malformed. Please call the tool again using the correct JSON format.",
                    }
                )
                step -= 1  # don't count the retry as a new step
                continue
            elif error_code == "tool_use_failed":
                failed = error_info.get("failed_generation", "")
                print(
                    f"\n[error at step {step}] Model generated a malformed tool call (retry also failed)."
                )
                if failed:
                    print(f"  failed_generation: {failed}")
            else:
                print(f"\n[error at step {step}] API error: {error_msg}")
            return

        message = response.choices[0].message
        usage = response.usage
        if usage:
            step_usages.append({
                "step": step,
                "prompt": usage.prompt_tokens,
                "completion": usage.completion_tokens,
            })

        # Normalise tool calls: prefer structured tool_calls, fall back to
        # parsing the text content for the XML-style format Llama sometimes emits.
        tool_calls = []
        if message.tool_calls:
            tool_calls = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in message.tool_calls
            ]
        elif message.content and "<function" in message.content:
            parsed = _parse_text_tool_calls(message.content)
            if parsed:
                print(
                    f"  [step {step}] (parsed {len(parsed)} tool call(s) from text response)",
                    flush=True,
                )
                tool_calls = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["arguments"]),
                        },
                    }
                    for tc in parsed
                ]

        if tool_calls:
            messages.append({"role": "assistant", "tool_calls": tool_calls})

            tokens_str = (
                f"  prompt={usage.prompt_tokens:,} completion={usage.completion_tokens:,}"
                if usage else ""
            )
            print(f"  [step {step}{tokens_str}]", flush=True)
            seen_calls: dict[str, str] = {}  # call_key → cached result
            for tc in tool_calls:
                args = json.loads(tc["function"]["arguments"])
                name = tc["function"]["name"]
                call_key = f"{name}:{json.dumps(args, sort_keys=True)}"
                if call_key in seen_calls:
                    result = json.dumps({"note": "Duplicate call — result identical to the previous call with the same arguments."})
                    print(f"    {name}({json.dumps(args)})  [duplicate — placeholder sent]", flush=True)
                else:
                    print(f"    {name}({json.dumps(args)})", flush=True)
                    result = dispatch_tool(name, args)
                    seen_calls[call_key] = result
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result,
                    }
                )
        else:
            # Final text response
            answer = message.content or ""
            print(f"\nAssistant: {answer}\n")
            retry_str = f", {retry_count} retry" if retry_count else ""
            print(
                f"  [{step} step(s) used, {step + retry_count} Groq request(s){retry_str}]"
            )
            if step_usages:
                for u in step_usages:
                    print(f"  step {u['step']}: prompt={u['prompt']:,}  completion={u['completion']:,}")
                total_p = sum(u["prompt"] for u in step_usages)
                total_c = sum(u["completion"] for u in step_usages)
                print(f"  total tokens: {total_p:,} prompt + {total_c:,} completion = {total_p + total_c:,}")
            return answer

    print("[error] Reached maximum steps without a final answer.")
    return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    if _OLLAMA_BASE_URL:
        api_key = None
        print(f"Using Ollama at {_OLLAMA_BASE_URL}  |  model: {MODEL}")
    else:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            print(
                "Error: GROQ_API_KEY not set (or set OLLAMA_BASE_URL for local inference)",
                file=sys.stderr,
            )
            sys.exit(1)

    if not MOCK_TOOLS:
        try:
            _init_real_tools()
        except Exception as e:
            print(f"Error initialising real tools: {e}", file=sys.stderr)
            sys.exit(1)

    client = _make_client(api_key)

    metrics = (
        _mock_list_available_metrics()["metrics"]
        if MOCK_TOOLS
        else _real_list_available_metrics()["metrics"]
    )
    system_prompt = build_system_prompt(metrics)

    mode = "mock tools" if MOCK_TOOLS else "real tile data"
    print(f"Climate chat PoC  |  model: {MODEL}  |  {mode}\n")

    # Single-shot mode: prompt passed as a command-line argument
    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
        print(f"You: {question}")
        run_agent(client, question, system_prompt)
        return

    # Interactive mode
    print("Type a question and press Enter. Ctrl-C or Ctrl-D to exit.\n")
    conversation_history: list[tuple[str, str]] = []
    while True:
        try:
            question = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not question:
            continue

        answer = run_agent(client, question, system_prompt, history=conversation_history)
        if answer:
            conversation_history.append(("user", question))
            conversation_history.append(("assistant", answer))
            conversation_history = conversation_history[-(MAX_HISTORY_TURNS * 2):]


if __name__ == "__main__":
    main()
