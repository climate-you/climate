import xarray as xr

from climate.models import StoryContext, StoryFacts
from climate.datasets.sources.openmeteo import fetch_current_temp_c
from climate.units import fmt_delta, fmt_temp

# -----------------------------------------------------------
# Compute intro data and captions
# -----------------------------------------------------------


def build_intro_data(ctx: StoryContext) -> dict:
    """
    Prepare the data needed for the 'Intro' panel.

    Uses:
    -
    Returns a dict so it's easy to plug into other front-ends later.
    """
    temp_now_c, temp_now_time = fetch_current_temp_c(ctx.location_lat, ctx.location_lon)

    # Keep global as a placeholder for now (swap later when we have a real global series)
    global_delta = 1.0

    return {
        "temp_now_c": temp_now_c,
        "temp_now_time": temp_now_time,
        "global_delta": global_delta,
    }


def intro_caption(ctx: StoryContext, facts: StoryFacts, data: dict) -> str:
    """
    Web-friendly intro caption: long-term narrative only.
    (The web app renders "It's currently ..." separately from the live proxy.)
    """

    def _warming_phrase(d):
        if d is None:
            return "changed by an unknown amount"
        if d > 0.15:
            return f"warmed by about **{fmt_delta(d, ctx.unit)}**"
        if d < -0.15:
            return f"cooled by about **{fmt_delta(abs(d), ctx.unit, sign=False)}**"
        return "changed very little"

    def _compare_local_global(local_d, global_d):
        # Handle missing gracefully
        if local_d is None or global_d is None:
            return "We don’t have enough data here to compare local and global warming yet."

        # handle negative / near-zero cleanly
        if abs(local_d) < 0.15:
            return "Locally, temperatures have **changed much less** than the global average."
        if local_d < 0:
            return "Locally, it has **cooled slightly**, unlike the world overall which has warmed."
        if local_d > global_d + 0.2:
            return "Locally, warming is happening **faster** than the global average."
        if local_d < global_d - 0.2:
            return (
                "Locally, warming is happening **more slowly** than the global average."
            )
        return "Locally, warming is **broadly similar** to the global average."

    local_delta = facts.total_warming_50y
    global_delta = data.get("global_delta")

    caption = f"""
    Since **{facts.data_start_year}**, the typical yearly temperature **here** has {_warming_phrase(local_delta)}.

    Over the same period, the world has warmed by about **{fmt_delta(global_delta, ctx.unit)}**.
    {_compare_local_global(local_delta, global_delta)}

    On this journey, we'll **zoom out from recent weather to decades of climate**, then see how those long-term shifts show up in your **seasons**.
    """
    return caption
