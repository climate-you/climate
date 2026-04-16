"""
Pre-written answers for the example questions shown in the chat UI.

Matching is case-insensitive and whitespace-normalised.
When a question matches, the answer is streamed via SSE with a short artificial
delay so it behaves like a real response.

Temperature values are encoded as [[C_VALUE|F_VALUE]] tokens.  At stream time,
_apply_unit() strips the token and emits the appropriate value.  Absolute
temperatures use the full C→F conversion (×9/5 + 32); delta/trend values use
the scale-only conversion (×9/5).

Run the questions through the 70b model and update the answers below once
you're happy with them.
"""

from __future__ import annotations

import re
import time
from typing import Any

# question (lowercased, stripped) → (answer text, locations list, chart_spec | None)
# chart_spec: {"metric_id": str, "start_year": int|None, "end_year": int|None,
#              "month_filter": list[int]|None, "aggregate_by_year": bool}
CANNED: dict[str, tuple[str, list[dict], dict | None]] = {
    "what is the hottest capital city in the world?": (
        "The hottest capital city in the world is **Khartoum, Sudan**, with a mean annual "
        "temperature of **[[29.6°C|85.3°F]]**.",
        [{"label": "Khartoum", "lat": 15.55, "lon": 32.53}],
        {"metric_id": "t2m_yearly_mean_c"},
    ),
    "what are the top 5 warmest large cities in the world?": (
        "The top 5 warmest large cities in the world are:\n\n"
        "1. **Khartoum, Sudan** — [[29.6°C|85.3°F]]\n"
        "2. **Niamey, Niger** — [[29.4°C|84.9°F]]\n"
        "3. **Makkah, Saudi Arabia** — [[29.3°C|84.7°F]]\n"
        "4. **Omdurman, Sudan** — [[29.2°C|84.6°F]]\n"
        "5. **Sokoto, Nigeria** — [[29.2°C|84.6°F]]",
        [
            {"label": "Khartoum", "lat": 15.55, "lon": 32.53},
            {"label": "Niamey", "lat": 13.51, "lon": 2.11},
            {"label": "Makkah", "lat": 21.39, "lon": 39.86},
            {"label": "Omdurman", "lat": 15.65, "lon": 32.48},
            {"label": "Sokoto", "lat": 13.06, "lon": 5.24},
        ],
        {"metric_id": "t2m_yearly_mean_c"},
    ),
    "how have winters changed in tokyo since 2000?": (
        "Winter temperatures in the Tokyo area (December–February) have warmed noticeably "
        "since 2000. The coldest winter on record was in 2001, averaging around [[4.3°C|39.7°F]] across "
        "the three winter months, while the warmest was 2023 at around [[6.5°C|43.7°F]]. "
        "The overall trend shows roughly [[+0.3–0.5°C|+0.5–0.9°F]] of warming over the period, consistent "
        "with the broader pattern of urban warming in East Asia.",
        [{"label": "Tokyo", "lat": 35.69, "lon": 139.69}],
        {"metric_id": "t2m_monthly_mean_c", "start_year": 2000,
         "month_filter": [12, 1, 2], "aggregate_by_year": True},
    ),
    "which city has warmed the fastest in the last 50 years?": (
        "The city that has warmed the fastest in the last 50 years is **Longyearbyen, "
        "Svalbard** (Norway), with a warming trend of **[[1.21°C|2.18°F]] per decade** — roughly [[6°C|10.8°F]] "
        "of warming over 50 years. This reflects the Arctic amplification effect, where "
        "polar regions warm at two to three times the global average rate.",
        [{"label": "Longyearbyen", "lat": 78.22, "lon": 15.65}],
        {"metric_id": "t2m_yearly_mean_c", "show_trend": True},
    ),
    "what is the coldest major city in the world?": (
        "The coldest major city in the world is **Krasnoyarsk, Russia**, with a mean annual "
        "temperature of **[[1.0°C|33.8°F]]**.",
        [{"label": "Krasnoyarsk", "lat": 56.02, "lon": 92.87}],
        {"metric_id": "t2m_yearly_mean_c"},
    ),
    "how does the temperature in dubai compare to 20 years ago?": (
        "Dubai is measurably warmer than 20 years ago. The annual mean temperature has risen "
        "from **[[28.1°C|82.6°F]]** in 2006 to **[[28.9°C|84.0°F]]** in 2025 — an increase of **[[0.8°C|1.4°F]]** over "
        "two decades, driven by a combination of global warming and rapid urban expansion.",
        [{"label": "Dubai", "lat": 25.20, "lon": 55.27}],
        {"metric_id": "t2m_yearly_mean_c"},
    ),
    "which continent is warming fastest?": (
        "The continent that is warming the fastest is **Europe**, with a warming trend of "
        "**[[0.51°C|0.92°F]] per decade**.",
        [],
        {
            "metric_id": "t2m_trend_1979_2025_c_per_decade",
            "region_ids": [
                "continent:africa",
                "continent:antarctica",
                "continent:asia",
                "continent:europe",
                "continent:north america",
                "continent:south america",
                "continent:oceania",
            ],
        },
    ),
    "how has the sea surface temperature in the indian ocean changed?": (
        "The sea surface temperature in the Indian Ocean has been increasing over the years, "
        "with a mean temperature of **[[17.3°C|63.1°F]]** in 1982 and **[[18.1°C|64.6°F]]** in 2025.",
        [],
        {
            "metric_id": "sst_yearly_mean_c",
            "start_year": 1982,
            "end_year": 2025,
            "region_ids": ["ocean:indian_ocean"],
        },
    ),
    "how are global temperatures changing?": (
        "Global mean temperature has been increasing steadily, rising from **[[13.9°C|57.0°F]]** "
        "in 1979 to **[[15.0°C|59.0°F]]** in 2025 — an increase of **[[1.1°C|2.0°F]]** over 46 years.",
        [],
        {
            "metric_id": "t2m_yearly_mean_c",
            "start_year": 1979,
            "end_year": 2025,
            "region_ids": ["globe"],
        },
    ),
    "how has the mean temperature in norway changed in recent years?": (
        "The mean temperature in Norway has been increasing in recent years. "
        "In 2025, the mean temperature was **[[2.6°C|36.7°F]]**, which is higher than "
        "the mean temperature in 2000, which was **[[1.4°C|34.5°F]]**.",
        [],
        {
            "metric_id": "t2m_yearly_mean_c",
            "start_year": 2000,
            "end_year": 2025,
            "region_ids": ["country:NO"],
        },
    ),
    "is germany warming faster than france?": (
        "Yes, Germany is warming faster than France. Germany has a warming trend of "
        "**[[0.50°C|0.90°F]] per decade**, compared to France's **[[0.41°C|0.74°F]] per decade**.",
        [],
        {
            "metric_id": "t2m_trend_1979_2025_c_per_decade",
            "region_ids": ["country:DE", "country:FR"],
        },
    ),
    # Disabled — requires continent/region averaging which is not yet supported:
    # "is it getting hotter in europe?": ("...", [], None),
    # Disabled — requires precipitation metrics which are not yet in the catalogue:
    # "has rainfall changed in london over the last 30 years?": ("...", [], None),
    # "which city sees more rain: london or paris?": ("...", [], None),
}

_TOKEN_RE = re.compile(r"\[\[([^\]|]+)\|([^\]]+)\]\]")


def _apply_unit(text: str, unit: str) -> str:
    """Replace [[C_VALUE|F_VALUE]] tokens with the value matching the requested unit."""
    if unit == "F":
        return _TOKEN_RE.sub(r"\2", text)
    return _TOKEN_RE.sub(r"\1", text)


def lookup(question: str) -> tuple[str, list[dict], dict | None] | None:
    """Return (answer, locations, chart_spec) for a question, or None if not found."""
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
        # Region-based chart (continent, ocean, globe, country)
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
        # Point-based chart (lat/lon locations)
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
                    {**entry, "value": _tools._convert_temp(
                        entry["value"], spec, is_delta=is_delta, target="F"
                    )}
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
                    trend_values = [round(float(np.polyval(coeffs, y)), 3) for y in years]
                    series_results.append({
                        "metric_id": metric_id,
                        "unit": result.get("unit", ""),
                        "location": loc["label"],
                        "role": "trend",
                        "data": [{"year": y, "value": v} for y, v in zip(years, trend_values)],
                    })

    return _build_chart_payloads(series_results, tile_store)


def stream_canned(
    answer: str,
    locations: list[dict],
    charts: list[dict] | None = None,
    delay_s: float = 1.5,
    temperature_unit: str = "C",
):
    """
    Yield SSE event dicts that mimic a real orchestrator response.
    Streams the answer word-by-word as chunk events, then emits the
    full answer event at the end for consistency with the live path.
    """
    resolved = _apply_unit(answer, temperature_unit)

    # Short initial delay to simulate model "thinking"
    time.sleep(min(delay_s, 0.3))

    # Stream word-by-word
    words = resolved.split(" ")
    for i, word in enumerate(words):
        chunk = word if i == 0 else " " + word
        yield {"type": "chunk", "text": chunk}
        time.sleep(0.02)  # ~50 words/second

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
    }
