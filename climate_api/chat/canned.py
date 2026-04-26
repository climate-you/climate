"""
Pre-written answers for the example questions shown in the chat UI.

Answers and chart specs are stored in question_tree.json and loaded at startup
via question_tree.py.  This module derives the lookup dict from the tree so
there is a single source of truth for all question content.

Temperature values are encoded as [[C_VALUE|F_VALUE]] tokens.  At stream time,
_apply_unit() strips the token and emits the appropriate value.  Absolute
temperatures use the full C→F conversion (×9/5 + 32); delta/trend values use
the scale-only conversion (×9/5).
"""

from __future__ import annotations

import re
import time
from typing import Any

from .question_tree import QUESTION_TREE, TREE_VERSION

# Build lookup: question text (normalised) → (answer, locations, chart_spec, follow_up_ids)
CANNED: dict[str, tuple[str, list[dict], dict | None, list[str]]] = {
    " ".join(node.question.strip().lower().split()): (
        node.answer,
        node.locations,
        node.chart_spec,
        node.follow_up_ids,
    )
    for node in QUESTION_TREE.values()
    if node.answer is not None and node.status == "active"
}

_TOKEN_RE = re.compile(r"\[\[([^\]|]+)\|([^\]]+)\]\]")


def _apply_unit(text: str, unit: str) -> str:
    """Replace [[C_VALUE|F_VALUE]] tokens with the value matching the requested unit."""
    if unit == "F":
        return _TOKEN_RE.sub(r"\2", text)
    return _TOKEN_RE.sub(r"\1", text)


def lookup(question: str) -> tuple[str, list[dict], dict | None, list[str]] | None:
    """Return (answer, locations, chart_spec, follow_up_ids) for a question, or None."""
    key = " ".join(question.strip().lower().split())
    return CANNED.get(key)


def build_canned_charts(
    locations: list[dict],
    chart_spec: dict,
    tile_store: Any,
    temperature_unit: str = "C",
) -> list[dict]:
    """Fetch series for each canned location and build chart payloads."""
    import numpy as np
    from climate_api.chat import tools as _tools
    from climate_api.chat.orchestrator import _build_chart_payloads

    metric_id = chart_spec.get("metric_id")
    if not metric_id:
        return []

    start_year = chart_spec.get("start_year")
    end_year = chart_spec.get("end_year")
    month_filter = chart_spec.get("month_filter")
    aggregate_by_year = bool(chart_spec.get("aggregate_by_year", False))
    show_trend = bool(chart_spec.get("show_trend", False))
    spec = tile_store.metrics.get(metric_id, {})

    series_results: list[dict] = []

    region_ids = chart_spec.get("region_ids")
    if region_ids:
        aggregation = chart_spec.get("aggregation", "mean")
        for region_id in region_ids:
            result = _tools.get_region_metric_series(
                region_id=region_id,
                metric_id=metric_id,
                aggregation=aggregation,
                tile_store=tile_store,
                start_year=start_year,
                end_year=end_year,
                temperature_unit=temperature_unit,
            )
            if "error" in result or "data" not in result:
                continue
            series_results.append(result)
    else:
        for loc in locations:
            result = _tools._get_metric_series(
                lat=loc["lat"],
                lon=loc["lon"],
                metric_id=metric_id,
                tile_store=tile_store,
                start_year=start_year,
                end_year=end_year,
                month_filter=month_filter,
                aggregate_by_year=aggregate_by_year,
            )
            if "error" in result or "data" not in result:
                continue
            if temperature_unit == "F" and spec.get("unit") == "C":
                is_delta = _tools._is_delta_metric(spec)
                result["data"] = [
                    {
                        **entry,
                        "value": _tools._convert_temp(
                            entry["value"], spec, is_delta=is_delta, target="F"
                        ),
                    }
                    for entry in result["data"]
                ]
                result["unit"] = _tools._output_unit(spec, "F")
            result["location"] = loc["label"]
            series_results.append(result)

            if show_trend:
                data_pts = result.get("data", [])
                years = [d["year"] for d in data_pts]
                values = [d["value"] for d in data_pts]
                if len(years) >= 2:
                    coeffs = np.polyfit(years, values, 1)
                    trend_values = [
                        round(float(np.polyval(coeffs, y)), 3) for y in years
                    ]
                    series_results.append(
                        {
                            "metric_id": metric_id,
                            "unit": result.get("unit", ""),
                            "location": loc["label"],
                            "role": "trend",
                            "data": [
                                {"year": y, "value": v}
                                for y, v in zip(years, trend_values)
                            ],
                        }
                    )

    return _build_chart_payloads(series_results, tile_store)


def stream_canned(
    answer: str,
    locations: list[dict],
    charts: list[dict] | None = None,
    follow_up_ids: list[str] | None = None,
    delay_s: float = 1.5,
    temperature_unit: str = "C",
):
    """
    Yield SSE event dicts that mimic a real orchestrator response.
    Streams the answer word-by-word as chunk events, then emits the
    full answer event at the end for consistency with the live path.
    """
    resolved = _apply_unit(answer, temperature_unit)

    time.sleep(min(delay_s, 0.3))

    words = resolved.split(" ")
    for i, word in enumerate(words):
        chunk = word if i == 0 else " " + word
        yield {"type": "chunk", "text": chunk}
        time.sleep(0.02)

    yield {"type": "answer", "text": resolved}
    yield {
        "type": "done",
        "session_id": None,
        "step_count": 0,
        "tools_called": [],
        "tier": "canned",
        "model": None,
        "rejected_tiers": [],
        "model_override": None,
        "total_ms": int(delay_s * 1000),
        "steps_timing": [],
        "locations": locations,
        "charts": charts or [],
        "follow_up_ids": follow_up_ids or [],
        "question_tree_version": TREE_VERSION,
    }
