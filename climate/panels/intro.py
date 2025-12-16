import xarray as xr

from climate.models import StoryContext, StoryFacts
from climate.openmeteo import fetch_openmeteo_current_temp_c
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
    temp_now_c, temp_now_time = fetch_openmeteo_current_temp_c(ctx.location_lat, ctx.location_lon)

    # Keep global as a placeholder for now (swap later when we have a real global series)
    global_delta = 1.0

    return {
        "temp_now_c" : temp_now_c,
        "temp_now_time" : temp_now_time,
        "global_delta" : global_delta,
    }

def intro_caption(ctx: StoryContext, facts: StoryFacts, data:dict) -> str:
    """
    Generate the markdown caption for the intro panel
    using StoryFacts (so it's easy to reuse elsewhere).
    """
    def _warming_phrase(d):
        if d > 0.15:
            return f"warmed by about **{fmt_delta(d, ctx.unit)}**"
        if d < -0.15:
            return f"cooled by about **{fmt_delta(abs(d), sign=False)}**"
        return "changed very little"

    def _compare_local_global(local_d, global_d):
        # handle negative / near-zero cleanly
        if abs(local_d) < 0.15:
            return "Your local climate is changing **much more slowly** than the global average."
        if local_d < 0:
            return "Your local climate has **cooled slightly**, unlike the world overall which has warmed."
        if local_d > global_d + 0.2:
            return "Your local climate is warming **faster** than the global average."
        if local_d < global_d - 0.2:
            return "Your local climate is warming **more slowly** than the global average."
        return "Your local warming is **broadly similar** to the global average."

    temp_now_c = data["temp_now_c"]
    temp_now_time = data["temp_now_time"]
    local_delta = facts.total_warming_50y
    global_delta = data["global_delta"]

    now_line = ""
    if temp_now_c is not None:
        now_line = f"It is currently **{fmt_temp(temp_now_c, ctx.unit)}** in {ctx.location_label} (latest reading: {temp_now_time})."
    else:
        now_line = f"Current temperature is temporarily unavailable for {ctx.location_label} (rate limited or network issue)."

    caption = (f"""
        {now_line}

        Since **{facts.data_start_year}**, the typical yearly temperature in **{ctx.location_label}** has {_warming_phrase(local_delta)}.

        Globally, the average warming over the same period is around **{fmt_delta(global_delta, ctx.unit)}**.
        {_compare_local_global(local_delta, global_delta)}

        Use the steps in the sidebar to **zoom out from last week’s weather to decades of climate**, then see how those long-term shifts show up in your **seasons**.
        """)
    
    return caption