"""
Chat orchestrator: runs the agentic loop across a prioritised list of provider tiers
and yields SSE event dicts.

Event types yielded by ChatOrchestrator.run():
  {"type": "tool_call",  "step": N, "name": "...", "args": {...}}
  {"type": "notice",     "text": "..."}            # degraded-model disclaimer, if applicable
  {"type": "answer",     "text": "..."}
  {"type": "done",       "session_id": "...", "step_count": N, "tools_called": [...], "tier": "...",
                         "model": "...", "rejected_tiers": [...], "model_override": "...|null",
                         "total_ms": N, "steps_timing": [{"step": N, "model_ms": N, "tools_ms": N}, ...],
                         "charts": [{"title": "...", "unit": "...", "series": [{"label": "...", "x": [...], "y": [...]}]}]}
  {"type": "error",      "message": "..."}

Provider tiers are tried in order. If a tier's API call returns a daily-token-quota error
on its *first* call (before any events have been yielded for this question), the orchestrator
silently falls through to the next tier. Any other error is surfaced as an "error" event.
"""

from __future__ import annotations

import datetime
import json
import logging
import re
import time as _time
import uuid

import numpy as np

logger = logging.getLogger(__name__)
from dataclasses import dataclass, field
from typing import Any, Iterator

from climate_api.store.location_index import LocationIndex, _norm as _norm_location
from climate_api.store.tile_data_store import TileDataStore
from climate_api.chat import tools as _tools


# ---------------------------------------------------------------------------
# Provider tier
# ---------------------------------------------------------------------------


@dataclass
class ProviderTier:
    """One entry in the fallback chain."""

    name: str  # e.g. "groq_70b_free", "groq_8b", "local"
    client: Any  # groq.Groq or openai.OpenAI instance
    model: str
    is_degraded: bool = False  # True → emit disclaimer notice before answer
    degraded_notice: str = field(default="")
    max_request_tokens: int | None = None  # If set, skip tier when estimated request exceeds this

    def __post_init__(self):
        if self.is_degraded and not self.degraded_notice:
            self.degraded_notice = _DEGRADED_MODEL_NOTICE


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEGRADED_MODEL_NOTICE = (
    "Note: The primary AI model's daily allowance has been exceeded. "
    "A smaller backup model is being used — answers may be less accurate."
)

_BUDGET_EXHAUSTED_MSG = (
    "The AI assistant's daily budget is exhausted. This project is provided for "
    "free and is self-funded. If you find it useful, please consider supporting "
    "it at ko-fi.com/climateyou."
)


# ---------------------------------------------------------------------------
# Quota detection
# ---------------------------------------------------------------------------


class _QuotaExhaustedError(Exception):
    """Raised when a tier's first API call hits a daily-token-quota limit."""


_INTERNAL_FIELDS = {"alt_names"}


_MONTHLY_COMPRESS_THRESHOLD = 60  # data points; below this, send raw


def _compress_series_for_context(result_json: str) -> str:
    """Replace large monthly data arrays with a compact statistical summary.

    The full data is already saved in series_results for chart rendering.
    The model only needs statistics to write its answer, so replace long
    monthly arrays with 12 climatological averages + overall stats.
    Yearly series (≤60 points) are kept as-is.
    """
    try:
        d = json.loads(result_json)
    except Exception:
        return result_json
    if not isinstance(d, dict) or "data" not in d:
        return result_json
    data = d["data"]
    if not isinstance(data, list) or len(data) <= _MONTHLY_COMPRESS_THRESHOLD:
        return result_json

    # Monthly series: entries have "year", "month", "value"
    if not data or "month" not in data[0]:
        return result_json

    from collections import defaultdict

    month_values: dict[int, list[float]] = defaultdict(list)
    all_values: list[float] = []
    min_val, min_entry = float("inf"), data[0]
    max_val, max_entry = float("-inf"), data[0]
    for entry in data:
        v = entry.get("value")
        if v is None:
            continue
        m = entry["month"]
        month_values[m].append(v)
        all_values.append(v)
        if v < min_val:
            min_val, min_entry = v, entry
        if v > max_val:
            max_val, max_entry = v, entry

    _MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    climatology = {
        _MONTH_NAMES[m - 1]: round(sum(vs) / len(vs), 2)
        for m, vs in sorted(month_values.items())
    }
    years = sorted({e["year"] for e in data})
    summary = {
        "period": f"{years[0]}-{years[-1]}",
        "n_records": len(data),
        "monthly_climatology": climatology,
        "overall_mean": round(sum(all_values) / len(all_values), 2),
        "record_low": {"year": min_entry["year"], "month": min_entry["month"], "value": round(min_val, 2)},
        "record_high": {"year": max_entry["year"], "month": max_entry["month"], "value": round(max_val, 2)},
    }
    d = {k: v for k, v in d.items() if k != "data"}
    d["summary"] = summary
    return json.dumps(d)


def _strip_internal_fields(result_json: str) -> str:
    """Remove backend-only fields from a tool result before sending to the LLM."""
    try:
        d = json.loads(result_json)
    except Exception:
        return result_json
    if isinstance(d, dict):
        for key in _INTERNAL_FIELDS:
            d.pop(key, None)
        if "results" in d and isinstance(d["results"], list):
            for r in d["results"]:
                if isinstance(r, dict):
                    for key in _INTERNAL_FIELDS:
                        r.pop(key, None)
    return json.dumps(d)


_BOLD_CITY_RE = re.compile(r"\*\*([^*,\n]+?)\*\*")


def _supplement_locations_from_answer(
    answer: str,
    locations: list[dict],
    location_index: Any,
) -> list[dict]:
    """Resolve city names mentioned in bold in the answer that weren't returned by any tool.

    This handles hallucinated or paraphrased city names (e.g. the LLM writes
    "Cologne" but the tool only returned cities with pop >= 1 000 000, so Köln
    was never in the results).

    Existing tool-returned locations take precedence: if a bold name matches any
    city already in the locations list (by label or alt_name), it is skipped so
    that less-populated but contextually correct entries (e.g. London, Ontario)
    are never shadowed by a higher-population city with the same name.
    """
    existing_keys = {(round(loc["lat"], 1), round(loc["lon"], 1)) for loc in locations}

    # Build a set of normalized names that are already covered by tool results.
    # Any bold name matching one of these is skipped — the correct location is
    # already present.
    existing_norm_names: set[str] = set()
    for loc in locations:
        city = loc["label"].split(",")[0].strip()
        n = _norm_location(city)
        if n:
            existing_norm_names.add(n)
        for alt in (loc.get("alt_names") or "").split(","):
            n = _norm_location(alt.strip())
            if n:
                existing_norm_names.add(n)

    extra: list[dict] = []
    seen_keys = set(existing_keys)
    for m in _BOLD_CITY_RE.finditer(answer):
        candidate = m.group(1).strip().split(",")[0].strip()
        if not candidate:
            continue
        if _norm_location(candidate) in existing_norm_names:
            continue
        hit = location_index.resolve_by_any_name(candidate)
        if hit is None:
            continue
        key = (round(hit.lat, 1), round(hit.lon, 1))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        extra.append({"label": hit.label, "alt_names": hit.alt_names, "lat": hit.lat, "lon": hit.lon})
    return locations + extra


def _extract_locations(name: str, args: dict, result_dict: dict) -> list[dict]:
    """Extract {label, lat, lon} entries from a tool result dict."""
    if "error" in result_dict:
        return []
    if name == "get_metric_series":
        lat = result_dict.get("lat")
        lon = result_dict.get("lon")
        if lat is not None and lon is not None:
            return [{"label": str(args.get("location", "")), "lat": lat, "lon": lon}]
    elif name == "find_extreme_location":
        if "lat" in result_dict:
            return [{"label": result_dict.get("nearest_city", ""), "alt_names": result_dict.get("alt_names", ""), "lat": result_dict["lat"], "lon": result_dict["lon"]}]
        return [
            {"label": r.get("nearest_city", ""), "alt_names": r.get("alt_names", ""), "lat": r["lat"], "lon": r["lon"]}
            for r in result_dict.get("results", [])
            if "lat" in r
        ]
    elif name == "find_similar_locations":
        lat = result_dict.get("reference_lat")
        lon = result_dict.get("reference_lon")
        if lat is not None and lon is not None:
            return [{"label": result_dict.get("reference", ""), "lat": lat, "lon": lon}]
    return []


def _collect_series_for_extreme(
    extreme_result: dict,
    args: dict,
    tile_store: Any,
    temperature_unit: str,
    series_results: list[dict],
) -> None:
    """Fetch get_metric_series for each city returned by find_extreme_location
    and append to series_results so a chart is shown alongside the answer."""
    metric_id = args.get("metric_id")
    if not metric_id:
        return
    start_year = args.get("start_year")
    end_year = args.get("end_year")
    month_filter = args.get("month_filter")
    aggregate_by_year = bool(args.get("aggregate_by_year", False))
    aggregation = str(args.get("aggregation", ""))

    # Normalise to a flat list of {label, lat, lon} entries, capped at 5
    _MAX_CHART_LOCATIONS = 5
    if "results" in extreme_result:
        cities = [
            {"label": r["nearest_city"], "lat": r["lat"], "lon": r["lon"]}
            for r in extreme_result["results"]
            if "lat" in r
        ][:_MAX_CHART_LOCATIONS]
    elif "lat" in extreme_result:
        cities = [{"label": extreme_result.get("nearest_city", ""), "lat": extreme_result["lat"], "lon": extreme_result["lon"]}]
    else:
        return

    spec = tile_store.metrics.get(metric_id, {})

    for city in cities:
        # Use coordinates directly — location is already resolved by find_extreme_location
        series_result = _tools._get_metric_series(
            lat=city["lat"],
            lon=city["lon"],
            metric_id=metric_id,
            tile_store=tile_store,
            start_year=int(start_year) if start_year is not None else None,
            end_year=int(end_year) if end_year is not None else None,
            month_filter=month_filter,
            aggregate_by_year=aggregate_by_year,
        )
        if "error" in series_result or "data" not in series_result:
            continue
        # Apply temperature unit conversion (mirrors get_metric_series)
        if temperature_unit == "F" and spec.get("unit") == "C":
            is_delta = _tools._is_delta_metric(spec)
            series_result["data"] = [
                {**entry, "value": _tools._convert_temp(entry["value"], spec, is_delta=is_delta, target="F")}
                for entry in series_result["data"]
            ]
            series_result["unit"] = _tools._output_unit(spec, "F")
        series_result["location"] = city["label"]
        series_result["_source"] = "auto"
        dedup_key = (series_result.get("metric_id"), series_result.get("location"), "raw")
        series_results[:] = [
            r for r in series_results
            if (r.get("metric_id"), r.get("location"), r.get("role", "raw")) != dedup_key
        ]
        series_results.append(series_result)

        # For trend_slope queries with a single location, append a linear regression series
        if aggregation == "trend_slope" and len(cities) == 1:
            data_pts = series_result.get("data", [])
            years = [d["year"] for d in data_pts]
            values = [d["value"] for d in data_pts]
            if len(years) >= 2:
                coeffs = np.polyfit(years, values, 1)
                trend_values = [round(float(np.polyval(coeffs, y)), 3) for y in years]
                trend_series: dict = {
                    "metric_id": metric_id,
                    "unit": series_result.get("unit", ""),
                    "location": city["label"],
                    "role": "trend",
                    "data": [{"year": y, "value": v} for y, v in zip(years, trend_values)],
                }
                trend_dedup_key = (metric_id, city["label"], "trend")
                series_results[:] = [
                    r for r in series_results
                    if (r.get("metric_id"), r.get("location"), r.get("role", "raw")) != trend_dedup_key
                ]
                series_results.append(trend_series)


def _filter_series_results(series_results: list[dict]) -> list[dict]:
    """Drop auto-collected series for metrics that have explicit get_metric_series results.

    When the LLM explicitly calls get_metric_series, those results should take
    precedence over series auto-fetched by _collect_series_for_extreme.  This
    prevents phantom cities (e.g. the global hottest city found by
    find_extreme_location) from appearing in charts when the question is really
    comparing specific named cities.
    """
    metrics_with_explicit = {
        r["metric_id"]
        for r in series_results
        if r.get("_source") == "explicit" and "metric_id" in r
    }
    if not metrics_with_explicit:
        return series_results
    return [
        r for r in series_results
        if r.get("_source") != "auto" or r.get("metric_id") not in metrics_with_explicit
    ]


def _build_chart_payloads(series_results: list[dict], tile_store: Any, temperature_unit: str = "C") -> list[dict]:
    """Build chart payload(s) from accumulated get_metric_series results.

    Groups results by metric_id, producing one chart per distinct metric.
    Each chart has the shape:
      {"title": str, "unit": str, "series": [{"label": str, "x": [...], "y": [...]}]}
    """
    series_results = _filter_series_results(series_results)
    if not series_results:
        return []

    groups: dict[str, list[dict]] = {}
    for r in series_results:
        groups.setdefault(r["metric_id"], []).append(r)

    charts = []
    for metric_id, results in groups.items():
        spec = tile_store.metrics.get(metric_id, {})
        metric_title = spec.get("title", metric_id)

        series = []
        for r in results:
            # Use city name only (drop country) to keep legend labels short
            label = r.get("location", metric_id).split(",")[0].strip() or metric_id
            x: list = []
            y: list = []
            for entry in r.get("data", []):
                if "month" in entry:
                    x.append(f"{entry['year']:04d}-{entry['month']:02d}")
                else:
                    x.append(entry["year"])
                y.append(entry.get("value"))
            series_entry: dict = {"label": label, "x": x, "y": y}
            if "role" in r:
                series_entry["role"] = r["role"]
            series.append(series_entry)

        # If a yearly series has fewer than 3 data points, re-fetch with an
        # extended range so the chart renders a proper curve rather than a dot.
        all_x_ints = sorted({xi for s in series for xi in s["x"] if isinstance(xi, int)})
        if 0 < len(all_x_ints) < 3:
            axis = tile_store.axis(metric_id)
            valid_min: int | None = None
            valid_max: int | None = None
            if axis:
                try:
                    valid_min = int(axis[0])
                    valid_max = int(axis[-1])
                except (ValueError, TypeError):
                    pass
            target: set[int] = set(all_x_ints)
            while len(target) < 3:
                lo, hi = min(target), max(target)
                can_before = valid_min is None or lo - 1 >= valid_min
                can_after = valid_max is None or hi + 1 <= valid_max
                if not can_before and not can_after:
                    break
                if can_before:
                    target.add(lo - 1)
                if len(target) < 3 and can_after:
                    target.add(hi + 1)
            new_start, new_end = min(target), max(target)
            spec = tile_store.metrics.get(metric_id, {})
            new_series = []
            for r, s in zip(results, series):
                if r.get("role") == "trend":
                    new_series.append(s)
                    continue
                lat, lon = r.get("lat"), r.get("lon")
                if lat is None or lon is None:
                    new_series.append(s)
                    continue
                extended = _tools._get_metric_series(
                    lat=lat, lon=lon, metric_id=metric_id, tile_store=tile_store,
                    start_year=new_start, end_year=new_end,
                )
                if "error" in extended or "data" not in extended:
                    new_series.append(s)
                    continue
                if temperature_unit == "F" and spec.get("unit") == "C":
                    is_delta = _tools._is_delta_metric(spec)
                    extended["data"] = [
                        {**entry, "value": _tools._convert_temp(entry["value"], spec, is_delta=is_delta, target="F")}
                        for entry in extended["data"]
                    ]
                new_x = [entry["year"] for entry in extended["data"]]
                new_y = [entry.get("value") for entry in extended["data"]]
                new_entry: dict = {"label": s["label"], "x": new_x, "y": new_y}
                if "role" in s:
                    new_entry["role"] = s["role"]
                new_series.append(new_entry)
            series = new_series

        # Build title from raw (non-trend) locations only, deduplicated
        seen_locs: set[str] = set()
        title_locations: list[str] = []
        for r in results:
            if r.get("role", "raw") == "trend":
                continue
            loc = r.get("location", "").split(",")[0].strip()
            if loc and loc not in seen_locs:
                seen_locs.add(loc)
                title_locations.append(loc)
        if len(title_locations) > 2:
            location_label = "Multiple cities"
        else:
            location_label = " & ".join(title_locations)
        title = f"{metric_title} \u2014 {location_label}" if location_label else metric_title
        unit = results[0].get("unit", "")
        charts.append({"title": title, "unit": unit, "series": series})

    return charts


def _is_quota_exhausted(exc: Exception) -> bool:
    """Return True if the exception signals a daily token quota exhaustion."""
    # Groq SDK raises RateLimitError for 429; check that first.
    try:
        from groq import RateLimitError

        if isinstance(exc, RateLimitError):
            # Distinguish TPD (daily) from TPM (per-minute).
            # TPM errors should be retried with a delay, not trigger tier fallback.
            msg = str(exc).lower()
            if "tokens per day" in msg or " tpd" in msg:
                return True
            # A generic 429 with no TPM marker is also treated as quota.
            if "tokens per minute" not in msg and "tpm" not in msg:
                return True
    except ImportError:
        pass
    # Fallback: check status code + error body
    if getattr(exc, "status_code", None) == 429:
        body = getattr(exc, "body", {}) or {}
        error_info = body.get("error") or {}
        msg = error_info.get("message", "").lower()
        if "tokens per day" in msg or " tpd" in msg:
            return True
    return False


def _is_context_too_large(exc: Exception) -> bool:
    """Return True if the exception signals that the request is too large for the model."""
    if getattr(exc, "status_code", None) == 413:
        return True
    msg = str(exc).lower()
    return "request too large" in msg or "please reduce your message size" in msg


def _is_tpm_error(exc: Exception) -> bool:
    """Return True if the exception is a per-minute rate limit (retryable by waiting).
    Excludes 'request too large' errors which can't be fixed by waiting."""
    if _is_context_too_large(exc):
        return False
    msg = str(exc).lower()
    return ("tokens per minute" in msg or " tpm" in msg) and "try again in" in msg


def _parse_retry_after_s(exc: Exception) -> float:
    m = re.search(r"try again in\s+(?:(\d+)m)?(?:\s*(\d+(?:\.\d+)?)s)?", str(exc), re.I)
    if m:
        return float(m.group(1) or 0) * 60 + float(m.group(2) or 0)
    return 5.0


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "find_extreme_location",
            "description": (
                "Find the location(s) with the highest or lowest value of a climate metric. "
                "Use for questions like 'which city is the hottest?', 'top 10 warmest large cities', "
                "'hottest capital', 'warmest city in France', 'warmest cities in South America'. "
                "Returns a single result when limit=1, or a ranked list when limit>1. "
                "Use min_population to restrict to large cities (e.g. 1000000 for megacities). "
                "Use capital_only=true to restrict to national capital cities. "
                "Use country to restrict to a specific country (full English name, e.g. 'France'). "
                "Use continent to restrict to an entire continent instead of querying per-country."
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
                        "description": "First year to include (inclusive). Must be a number, e.g. 2020.",
                    },
                    "end_year": {
                        "description": "Last year to include (inclusive). Must be a number, e.g. 2024.",
                    },
                    "month_filter": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Months to include, e.g. [12, 1, 2] for winter. Only for monthly metrics.",
                    },
                    "country": {
                        "type": "string",
                        "description": "Restrict to cities in this country (full English name, e.g. 'France'). Takes precedence over continent.",
                    },
                    "continent": {
                        "type": "string",
                        "description": (
                            "Restrict to cities on this continent. "
                            "Accepted values: Africa, Antarctica, Asia, Europe, "
                            "North America, Oceania, South America. "
                            "Also accepts common aliases like 'Latin America', 'Middle East', 'Australasia'. "
                            "Use this instead of making separate per-country calls when the question covers a whole continent."
                        ),
                    },
                    "capital_only": {
                        "type": "boolean",
                        "description": "If true, only consider national capital cities.",
                    },
                    "min_population": {
                        "type": "integer",
                        "description": "Only consider cities with at least this population. Use 1000000 for 'large cities'.",
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
                "'cities with similar temperatures to Tokyo'. Scans cities with population >= 100k."
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
                "Filter by year range and/or specific months (1=Jan ... 12=Dec). "
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
                        "description": "First year to include (inclusive). Must be a number, e.g. 2020.",
                    },
                    "end_year": {
                        "description": "Last year to include (inclusive). Must be a number, e.g. 2024.",
                    },
                    "month_filter": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Months to include, e.g. [12, 1, 2] for winter. Only valid for monthly metrics.",
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
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_TEMPLATE = """\
You are a climate data assistant. You answer questions about historical climate data \
using the tools available to you.

Rules:
- Always call the tools to retrieve data before answering — never guess numerical values.
- Use the metric catalogue below to choose the correct metric_id directly.
- Pass a place name directly to get_metric_series — it resolves the location internally. \
Never guess or supply your own coordinates.
- Multiple independent tool calls can be made in a single step. When comparing multiple \
locations, call get_metric_series for all of them in one parallel step.
- Be selective with metrics: fetch only what the question requires. For a general \
temperature overview, t2m_yearly_mean_c alone is sufficient. Only add monthly metrics \
(t2m_monthly_mean_c, t2m_monthly_max_c, t2m_monthly_min_c) if the user explicitly asks \
about seasonal patterns, monthly variation, or temperature range. Never call multiple \
overlapping temperature metrics unless each one is specifically needed.
- When the question asks for a specific year or time range, always pass start_year and \
end_year to get_metric_series so the result is focused. For example, to get the 2020 \
value, pass start_year=2020, end_year=2020. Only omit year bounds when you need the full \
historical series (e.g. to find the hottest year across all years).
- For seasonal trend questions spanning multiple years (e.g. "how have winters changed"), \
pass month_filter for the season and aggregate_by_year=true. This returns one annual mean \
per year instead of one record per month, which is far more efficient. Only omit \
aggregate_by_year when per-month detail is needed (e.g. "which month of winter 2020 was \
coldest?").
- Before calling any tool that takes a year, check whether the requested year is in the \
future (beyond today's date). If it is a future year, do not retry — instead explain that \
our dataset only covers historical data up to the date shown in the metric catalogue above.
- Finding the hottest or coldest year at a specific location: use get_metric_series (not \
find_extreme_location) to retrieve the full series for that location, then identify the \
extremum year from the returned data. find_extreme_location is for finding which city or \
region has the most extreme value across many locations — not for finding the extreme year \
at a known location.
- Prefer pre-derived scalar metrics over on-the-fly aggregation: when a dedicated metric \
exists for a concept (e.g. t2m_trend_1979_2025_c_per_decade for warming trends, \
t2m_total_warming_vs_preindustrial_c for total warming since pre-industrial), use it with \
aggregation="mean" rather than computing trend_slope on t2m_yearly_mean_c. Check metric \
notes in the catalogue for guidance.
- You have at most {max_steps} tool-call steps. Use them efficiently — group independent \
lookups into one parallel step where possible. If after a few steps the available data \
does not fully answer the question, stop calling tools and give the best answer you can \
from what you have, clearly stating what data is and is not available in our dataset.
- Never mention tool names, function names, or raw JSON in your final response. \
Present findings as natural language only.
- When a tool returns fewer results than requested (e.g. find_extreme_location returns 3 \
cities instead of 5), report only those results — never invent additional cities or values \
to pad the list.
- Round all temperatures to one decimal place (e.g. {temp_example}). \
Round trend slopes to two decimal places (e.g. {trend_example}).
- Use markdown formatting in your final text response only (never inside tool arguments): \
bold (**text**) for location names and key numerical values (temperatures, trends). \
Use numbered lists when ranking multiple items.

Spatial precision: climate data is at 0.25 degree resolution (roughly 28 km per cell). \
A data point covers a geographic area, not a precise city. Prefer phrasing like "in the \
Tokyo area" rather than "in Tokyo specifically".

Two-tier answers: for questions about why something is happening, you may draw on \
general climate science knowledge — but clearly label it with an equivalent phrase in the \
user's language (e.g. in English: "Beyond what our dataset shows, climate science suggests...") \
and hedge appropriately. Never state general knowledge with the same certainty as a tool result.

Data availability: if the tool returns an error saying the requested time period is not \
available, retry with the most recent available period.

Reporting time periods: always state the explicit year or date from the data you retrieved \
— never echo the user's relative phrasing like "last year" or "last month". Say "in 2024" \
not "last year". If the year or month you fetched is the last one listed in the metric \
catalogue, add "(most recent available in our dataset)" after the year.

Respond in the same language as the user's question. Be concise and always include specific numbers from the data.

Today's date: {current_date}. Use this to interpret relative time expressions like \
"last year" or "this decade".
{map_context_block}{unit_block}\
Available metrics:
{metric_catalogue}
"""


def _format_metric_catalogue(metrics: list[dict]) -> str:
    lines = []
    for m in metrics:
        line = f"- {m['metric_id']}: {m['description']} ({m['unit']}), available {m['available_range']}, source: {m['source']}"
        if m.get("note"):
            line += f" -- {m['note']}"
        lines.append(line)
    return "\n".join(lines)


def _build_system_prompt(
    tile_store: TileDataStore,
    map_context: dict[str, Any] | None,
    max_steps: int = 5,
    temperature_unit: str = "C",
) -> str:
    metrics_result = _tools.list_available_metrics(tile_store)
    catalogue = _format_metric_catalogue(metrics_result.get("metrics", []))
    current_date = datetime.date.today().strftime("%Y-%m-%d")

    if map_context:
        label = (
            map_context.get("label")
            or f"{map_context.get('lat', 0)}, {map_context.get('lon', 0)}"
        )
        map_context_block = (
            f"\nMap context: the user is currently viewing [{label}]. "
            "For questions about 'here', 'this location', or 'this place', "
            f'pass "{label}" as the location parameter — do not use raw coordinates.\n'
        )
    else:
        map_context_block = "\n"

    if temperature_unit == "F":
        temp_example = "85.3°F, not 85.28°F"
        trend_example = "2.18°F/decade"
        unit_block = (
            "Temperature unit: the user's preference is Fahrenheit (°F). "
            "All temperature values in tool results are already in °F. "
            "Always express temperatures as °F in your answer.\n"
        )
    else:
        temp_example = "29.6°C, not 29.576°C"
        trend_example = "1.21°C/decade"
        unit_block = ""

    return _SYSTEM_PROMPT_TEMPLATE.format(
        current_date=current_date,
        map_context_block=map_context_block,
        metric_catalogue=catalogue,
        max_steps=max_steps,
        temp_example=temp_example,
        trend_example=trend_example,
        unit_block=unit_block,
    )


# ---------------------------------------------------------------------------
# XML text tool call fallback parser
# ---------------------------------------------------------------------------


def _parse_text_tool_calls(text: str) -> list[dict]:
    """
    Llama models sometimes emit tool calls as XML-ish text instead of structured
    tool_calls. This extracts them as a fallback.
    """
    matches = re.findall(r"<function[^>]*>(.*?)</function>", text, re.DOTALL)
    calls = []
    for raw in matches:
        raw = raw.strip().rstrip(")")
        brace = raw.find("{")
        if brace == -1:
            continue
        name = raw[:brace].lstrip('=("').rstrip('=("" ')
        try:
            arguments = json.loads(raw[brace:])
        except json.JSONDecodeError:
            continue
        calls.append(
            {"id": f"parsed_{name}_{len(calls)}", "name": name, "arguments": arguments}
        )
    return calls


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class ChatOrchestrator:
    def __init__(
        self,
        tiers: list[ProviderTier],
        tile_store: TileDataStore,
        location_index: LocationIndex,
        country_names: dict[str, str] | None = None,
        max_steps: int = 5,
    ) -> None:
        self.tiers = tiers
        self.tile_store = tile_store
        self.location_index = location_index
        self.country_name_to_code: dict[str, str] = {}
        if country_names:
            self.country_name_to_code = {
                v.casefold(): k for k, v in country_names.items()
            }
        self.max_steps = max_steps

    def _dispatch(self, name: str, args: dict, temperature_unit: str = "C") -> str:
        def _int_or_none(v: Any) -> int | None:
            return int(v) if v is not None else None

        if name == "get_metric_series":
            result = _tools.get_metric_series(
                location=str(args["location"]),
                metric_id=str(args["metric_id"]),
                tile_store=self.tile_store,
                location_index=self.location_index,
                start_year=_int_or_none(args.get("start_year")),
                end_year=_int_or_none(args.get("end_year")),
                month_filter=args.get("month_filter"),
                aggregate_by_year=bool(args.get("aggregate_by_year", False)),
                temperature_unit=temperature_unit,
            )
        elif name == "find_extreme_location":
            result = _tools.find_extreme_location(
                metric_id=str(args["metric_id"]),
                aggregation=str(args["aggregation"]),
                extremum=str(args["extremum"]),
                tile_store=self.tile_store,
                location_index=self.location_index,
                country_name_to_code=self.country_name_to_code,
                start_year=_int_or_none(args.get("start_year")),
                end_year=_int_or_none(args.get("end_year")),
                month_filter=args.get("month_filter"),
                country=args.get("country"),
                continent=args.get("continent"),
                capital_only=bool(args.get("capital_only", False)),
                min_population=int(args.get("min_population", 0)),
                limit=int(args.get("limit", 1)),
                temperature_unit=temperature_unit,
            )
        elif name == "find_similar_locations":
            result = _tools.find_similar_locations(
                reference_name=str(args["reference_name"]),
                metric_id=str(args["metric_id"]),
                tile_store=self.tile_store,
                location_index=self.location_index,
                limit=int(args.get("limit", 5)),
                temperature_unit=temperature_unit,
            )
        else:
            result = {"error": f"Unknown tool: '{name}'"}
        return json.dumps(result)

    def _run_tier(
        self,
        tier: ProviderTier,
        question: str,
        map_context: dict[str, Any] | None,
        session_id: str,
        history: list[tuple[str, str]] | None = None,
        temperature_unit: str = "C",
    ) -> Iterator[dict]:
        """
        Run the agentic loop for one tier. Yields SSE event dicts.

        Raises _QuotaExhaustedError if the very first API call hits a daily token
        quota limit (before any events have been yielded for this question).
        Any other error is yielded as an "error" event and the generator returns.
        """
        system_prompt = _build_system_prompt(self.tile_store, map_context, self.max_steps, temperature_unit)
        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        for role, text in (history or []):
            messages.append({"role": role, "content": text})
        messages.append({"role": "user", "content": question})

        tools_called: list[str] = []
        locations: list[dict] = []
        _location_keys: set[tuple] = set()
        series_results: list[dict] = []  # successful get_metric_series results for charting
        retried = False
        tpm_retries = 0
        events_yielded = False  # True once we've emitted at least one tool_call event

        t_start = _time.monotonic()
        steps_timing: list[dict] = []
        step_model_ms = 0  # accumulated model latency for current step (across retries)
        step_usage: dict = {}  # token counts for current step (from latest API response)
        last_unique_step = 0  # last step that was newly entered (not a retry)

        step = 0
        while step < self.max_steps:
            step += 1
            if step > last_unique_step:
                last_unique_step = step
                step_model_ms = 0  # new step — reset accumulator
                step_usage = {}
            try:
                # Pre-flight token estimate: chars / 4 is a standard approximation.
                # Include tool schemas in the estimate since they count against the limit.
                if tier.max_request_tokens is not None:
                    messages_chars = sum(
                        len(json.dumps(m)) for m in messages
                    )
                    tools_chars = sum(len(json.dumps(t)) for t in TOOL_SCHEMAS)
                    estimated_tokens = (messages_chars + tools_chars) // 4
                    if estimated_tokens > tier.max_request_tokens:
                        if not events_yielded:
                            raise _QuotaExhaustedError()
                        # Mid-conversation: can't fall back, surface a clear error
                        steps_timing.append({"step": step, "model_ms": 0, "error": True, **step_usage})
                        total_ms = int((_time.monotonic() - t_start) * 1000)
                        yield {
                            "type": "error",
                            "message": "The conversation has grown too long for this model. Please start a new chat.",
                            "detail": f"Pre-flight estimate: ~{estimated_tokens:,} tokens exceeds tier limit of {tier.max_request_tokens:,}.",
                        }
                        yield {
                            "type": "done",
                            "session_id": session_id,
                            "step_count": step,
                            "tools_called": tools_called,
                            "tier": tier.name,
                            "model": tier.model,
                            "total_ms": total_ms,
                            "steps_timing": steps_timing,
                            "locations": locations,
                        }
                        return

                model_t0 = _time.monotonic()
                stream = tier.client.chat.completions.create(
                    model=tier.model,
                    messages=messages,
                    tools=TOOL_SCHEMAS,
                    tool_choice="auto",
                    parallel_tool_calls=True,
                    temperature=0,
                    stream=True,
                )

                streamed_text = ""
                raw_tool_calls: dict[int, dict] = {}  # index → assembled tool call

                for chunk in stream:
                    if chunk.usage:
                        step_usage = {
                            "prompt_tokens": chunk.usage.prompt_tokens,
                            "completion_tokens": chunk.usage.completion_tokens,
                        }
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if delta.content:
                        streamed_text += delta.content
                        yield {"type": "chunk", "text": delta.content}
                    if delta.tool_calls:
                        for tc_delta in delta.tool_calls:
                            idx = tc_delta.index
                            if idx not in raw_tool_calls:
                                raw_tool_calls[idx] = {
                                    "id": "",
                                    "type": "function",
                                    "function": {"name": "", "arguments": ""},
                                }
                            entry = raw_tool_calls[idx]
                            if tc_delta.id:
                                entry["id"] = tc_delta.id
                            if tc_delta.function:
                                if tc_delta.function.name:
                                    entry["function"]["name"] += tc_delta.function.name
                                if tc_delta.function.arguments:
                                    entry["function"]["arguments"] += tc_delta.function.arguments

                step_model_ms += int((_time.monotonic() - model_t0) * 1000)
            except Exception as exc:
                # Always accumulate model latency, even for failed calls
                step_model_ms += int((_time.monotonic() - model_t0) * 1000)

                # Quota exhaustion or request-too-large on the very first call
                # (no events sent yet) → raise so the caller can fall through to
                # the next tier silently.
                if not events_yielded and (
                    _is_quota_exhausted(exc) or _is_context_too_large(exc)
                ):
                    raise _QuotaExhaustedError() from exc

                error_body = getattr(exc, "body", {}) or {}
                error_info = error_body.get("error") or {}
                error_code = error_info.get("code", "")
                error_msg = error_info.get("message", str(exc))

                is_tool_error = (
                    error_code == "tool_use_failed"
                    or "tool call validation" in error_msg.lower()
                )
                if is_tool_error and not retried:
                    retried = True
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"Your previous tool call was rejected due to a schema error: {error_msg}. "
                                "Please fix the argument types and call the tool again."
                            ),
                        }
                    )
                    step -= 1
                    continue

                # Per-minute rate limit — sleep briefly and retry (up to 3 times)
                if _is_tpm_error(exc) and tpm_retries < 3:
                    import time

                    wait = min(_parse_retry_after_s(exc) + 2.0, 30.0)
                    time.sleep(wait)
                    tpm_retries += 1
                    step -= 1
                    continue

                logger.warning(
                    "Chat API error (tier=%s, step=%d): %s",
                    tier.name,
                    step,
                    error_msg,
                    exc_info=True,
                )
                steps_timing.append(
                    {"step": step, "model_ms": step_model_ms, "error": True, **step_usage}
                )
                total_ms = int((_time.monotonic() - t_start) * 1000)
                if _is_context_too_large(exc):
                    user_msg = "The conversation has grown too long for this model. Please start a new chat."
                else:
                    user_msg = f"API error: {error_msg}"
                yield {"type": "error", "message": user_msg, "detail": error_msg}
                yield {
                    "type": "done",
                    "session_id": session_id,
                    "step_count": step,
                    "tools_called": tools_called,
                    "tier": tier.name,
                    "model": tier.model,
                    "total_ms": total_ms,
                    "steps_timing": steps_timing,
                    "locations": locations,
                }
                return

            # Normalise tool calls: structured (from stream), XML text fallback
            tool_calls = [raw_tool_calls[i] for i in sorted(raw_tool_calls)]
            if not tool_calls and streamed_text and "<function" in streamed_text:
                parsed = _parse_text_tool_calls(streamed_text)
                if parsed:
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
                tools_t0 = _time.monotonic()
                seen_calls: dict[str, str] = {}  # call_key → cached result
                for tc in tool_calls:
                    args = json.loads(tc["function"]["arguments"])
                    name = tc["function"]["name"]
                    call_key = f"{name}:{json.dumps(args, sort_keys=True)}"
                    if call_key in seen_calls:
                        result = json.dumps({"note": "Duplicate call — result identical to the previous call with the same arguments."})
                    else:
                        yield {
                            "type": "tool_call",
                            "step": step,
                            "name": name,
                            "args": args,
                        }
                        events_yielded = True
                        tools_called.append(name)
                        result = self._dispatch(name, args, temperature_unit)
                        seen_calls[call_key] = result
                        if name == "get_metric_series":
                            parsed_result = json.loads(result)
                            if "error" not in parsed_result and "data" in parsed_result:
                                parsed_result["_source"] = "explicit"
                                # Deduplicate by (metric_id, location) — keep the latest call
                                dedup_key = (parsed_result.get("metric_id"), parsed_result.get("location"))
                                series_results = [
                                    r for r in series_results
                                    if (r.get("metric_id"), r.get("location")) != dedup_key
                                ]
                                series_results.append(parsed_result)
                        elif name == "find_extreme_location":
                            parsed_result = json.loads(result)
                            if "error" not in parsed_result:
                                _collect_series_for_extreme(
                                    parsed_result, args, self.tile_store,
                                    temperature_unit, series_results,
                                )
                        try:
                            for loc in _extract_locations(name, args, json.loads(result)):
                                key = (round(loc["lat"], 1), round(loc["lon"], 1))
                                if key not in _location_keys:
                                    _location_keys.add(key)
                                    locations.append(loc)
                        except Exception:
                            pass
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": _compress_series_for_context(
                                _strip_internal_fields(result)
                            ),
                        }
                    )
                tools_ms = int((_time.monotonic() - tools_t0) * 1000)
                steps_timing.append(
                    {"step": step, "model_ms": step_model_ms, "tools_ms": tools_ms, **step_usage}
                )
            else:
                # Final text response
                steps_timing.append({"step": step, "model_ms": step_model_ms, **step_usage})
                total_ms = int((_time.monotonic() - t_start) * 1000)
                answer = streamed_text
                locations = _supplement_locations_from_answer(answer, locations, self.location_index)
                if tier.is_degraded:
                    yield {"type": "notice", "text": tier.degraded_notice}
                yield {"type": "answer", "text": answer}
                yield {
                    "type": "done",
                    "session_id": session_id,
                    "step_count": step,
                    "tools_called": tools_called,
                    "tier": tier.name,
                    "model": tier.model,
                    "total_ms": total_ms,
                    "steps_timing": steps_timing,
                    "locations": locations,
                    "charts": _build_chart_payloads(series_results, self.tile_store, temperature_unit),
                }
                return

        total_ms = int((_time.monotonic() - t_start) * 1000)
        yield {
            "type": "error",
            "message": "Reached maximum steps without a final answer.",
        }
        yield {
            "type": "done",
            "session_id": session_id,
            "step_count": self.max_steps,
            "tools_called": tools_called,
            "tier": tier.name,
            "model": tier.model,
            "total_ms": total_ms,
            "steps_timing": steps_timing,
            "locations": locations,
        }

    def run(
        self,
        question: str,
        history: list[tuple[str, str]] | None = None,
        map_context: dict[str, Any] | None = None,
        session_id: str | None = None,
        model_override: str | None = None,
        temperature_unit: str = "C",
    ) -> Iterator[dict]:
        """
        Run the agentic loop, trying each tier in order on quota exhaustion.

        model_override: tier name to start from (e.g. "local" to skip to Ollama).
        If the named tier is not in the list, yields an error event immediately.
        """
        if session_id is None:
            session_id = str(uuid.uuid4())

        tiers = self.tiers

        if model_override:
            idx = next(
                (i for i, t in enumerate(tiers) if t.name == model_override), None
            )
            if idx is None:
                yield {
                    "type": "error",
                    "message": f"Requested model '{model_override}' is not available on this server.",
                }
                yield {
                    "type": "done",
                    "session_id": session_id,
                    "step_count": 0,
                    "tools_called": [],
                    "tier": None,
                    "locations": [],
                }
                return
            tiers = tiers[idx:]

        rejected_tiers: list[str] = []

        import os as _os

        if _os.environ.get("CHAT_TEST_EXHAUSTED") == "1":
            tiers = []

        for tier in tiers:
            try:
                for event in self._run_tier(tier, question, map_context, session_id, history, temperature_unit):
                    if event["type"] == "done":
                        event = {
                            **event,
                            "rejected_tiers": rejected_tiers,
                            "model_override": model_override,
                        }
                    yield event
                return
            except _QuotaExhaustedError:
                rejected_tiers.append(tier.name)
                continue

        # All tiers quota-exhausted
        yield {"type": "answer", "text": _BUDGET_EXHAUSTED_MSG}
        yield {
            "type": "done",
            "session_id": session_id,
            "step_count": 0,
            "tools_called": [],
            "tier": None,
            "model": None,
            "rejected_tiers": rejected_tiers,
            "model_override": model_override,
            "locations": [],
        }
