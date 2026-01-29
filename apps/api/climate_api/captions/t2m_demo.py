from __future__ import annotations

from typing import Any


def _last_finite(vals: list[float | None]) -> float | None:
    for v in reversed(vals):
        if v is not None:
            return float(v)
    return None


def _first_finite(vals: list[float | None]) -> float | None:
    for v in vals:
        if v is not None:
            return float(v)
    return None


def _format_delta(delta: float, unit: str) -> str:
    # delta is already in requested unit if you computed trend series in that unit;
    # if you computed trends in C and converted series later, keep that consistent.
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta:.1f}°{unit}"


def caption_t2m_demo(
    *, unit: str, series: dict[str, Any], place_label: str | None
) -> str | None:
    """
    Minimal caption for the t2m demo panel.
    Expects series keys:
      - t2m_yearly_mean_c (or _f depending on unit conversion strategy)
      - t2m_yearly_mean_trend_c
    but we’ll just read whatever you actually return in `series`.
    """
    # Use the yearly trend series to compute start/end delta (more robust than relying on annotations for now)
    key_trend = "t2m_yearly_mean_trend_c"
    if key_trend not in series:
        return None

    y = series[key_trend]["y"]
    x = series[key_trend]["x"]
    if not x or not y:
        return None

    y0 = _first_finite(y)
    y1 = _last_finite(y)
    if y0 is None or y1 is None:
        return None

    delta = y1 - y0

    # infer number of years from x (yearly points); x might be YYYY-MM-DD strings
    n_years = max(0, len(x) - 1)

    loc = place_label or "This location"
    return (
        f"**{loc}** has warmed by **{_format_delta(delta, unit)}** over the last **{n_years} years** "
        f"(based on the linear trend of yearly mean temperature)."
    )
