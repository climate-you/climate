import xarray as xr
import plotly.graph_objs as go
import pandas as pd
import numpy as np

from climate.models import StoryFacts, StoryContext
from climate.units import fmt_delta, convert_temp, convert_delta

# -----------------------------------------------------------
# Compute seasons data, graph and captions
# -----------------------------------------------------------

def build_seasons_then_now_data(ctx: StoryContext) -> dict:
    """
    Prepare data for the 'How your seasons have shifted' panel AND the side-by-side
    monthly min/mean/max envelope figures.

    Method:
      - Take the monthly time series from the precomputed file:
          time_monthly:
            * t2m_monthly_mean_c
            * t2m_monthly_min_c
            * t2m_monthly_max_c

      - For each month (1..12), fit a linear trend across available years for that month,
        then evaluate at an "early" and "recent" reference year for *that month*.

      - Shift months so the warmest RECENT month sits in the middle (index 6).
    """
    required = ["t2m_monthly_mean_c", "t2m_monthly_min_c", "t2m_monthly_max_c"]
    if not all(v in ctx.ds for v in required):
        return {}

    # Convert to pandas series indexed by timestamps
    s_mean = ctx.ds["t2m_monthly_mean_c"].to_series()
    s_min  = ctx.ds["t2m_monthly_min_c"].to_series()
    s_max  = ctx.ds["t2m_monthly_max_c"].to_series()

    # Ensure datetime index
    s_mean.index = pd.to_datetime(s_mean.index)
    s_min.index  = pd.to_datetime(s_min.index)
    s_max.index  = pd.to_datetime(s_max.index)

    month_names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

    def _eval_month_trend(series: pd.Series, month: int):
        """
        Fit y = a*year + b for this month across all available years.
        Evaluate at early_year = first_year + 4.5, recent_year = last_year - 4.5
        (per-month, using available coverage for that month).
        """
        sm = series[series.index.month == month].dropna()
        if sm.empty:
            return np.nan, np.nan, np.nan, np.nan  # early, recent, early_year, recent_year

        years = sm.index.year.astype(float).to_numpy()
        vals  = sm.to_numpy(dtype="float64")

        # Need at least a few points to fit
        if len(vals) < 8:
            # fallback: use simple mean of first/last up to 10 values
            order = np.argsort(years)
            years_s = years[order]
            vals_s  = vals[order]
            k = min(10, len(vals_s))
            early = float(np.nanmean(vals_s[:k]))
            recent = float(np.nanmean(vals_s[-k:]))
            return early, recent, float(years_s[0]), float(years_s[-1])

        y0 = float(np.nanmin(years))
        y1 = float(np.nanmax(years))
        early_year = y0 + 4.5
        recent_year = y1 - 4.5
        if recent_year <= early_year:  # extremely short record
            early_year = y0
            recent_year = y1

        a, b = np.polyfit(years, vals, 1)
        early = float(a * early_year + b)
        recent = float(a * recent_year + b)
        return early, recent, early_year, recent_year

    # Trend-evaluated seasons for each month
    past_mean = np.full(12, np.nan)
    recent_mean = np.full(12, np.nan)
    past_min = np.full(12, np.nan)
    recent_min = np.full(12, np.nan)
    past_max = np.full(12, np.nan)
    recent_max = np.full(12, np.nan)

    early_years = []
    recent_years = []

    for m in range(1, 13):
        em, rm, ey, ry = _eval_month_trend(s_mean, m)
        emin, rmin, _, _ = _eval_month_trend(s_min, m)
        emax, rmax, _, _ = _eval_month_trend(s_max, m)

        past_mean[m-1] = em
        recent_mean[m-1] = rm
        past_min[m-1] = emin
        recent_min[m-1] = rmin
        past_max[m-1] = emax
        recent_max[m-1] = rmax
        early_years.append(ey)
        recent_years.append(ry)

    # If everything is NaN, bail
    if np.all(np.isnan(past_mean)) or np.all(np.isnan(recent_mean)):
        return {}

    # Shift so warmest recent month is centered
    ihot = int(np.nanargmax(recent_mean))
    center_pos = 6
    shift = center_pos - ihot

    def roll(a):
        return np.roll(a, shift)

    x = np.arange(12)
    month_labels_shifted = [month_names[(i - shift) % 12] for i in range(12)]

    past_mean_r = roll(past_mean)
    recent_mean_r = roll(recent_mean)
    past_min_r = roll(past_min)
    recent_min_r = roll(recent_min)
    past_max_r = roll(past_max)
    recent_max_r = roll(recent_max)

    delta_mean_r = recent_mean_r - past_mean_r
    
    # Pre-format the delta as a STRING so Plotly doesn’t fight formatting
    delta_str = np.array([fmt_delta(v, ctx.unit, decimals=2) for v in delta_mean_r], dtype=object)

    # customdata per point: [past, recent, delta_numeric, delta_string]
    past_mean_r_local = np.asarray([convert_temp(v, ctx.unit) for v in past_mean_r], dtype="float64")
    recent_mean_r_local = np.asarray([convert_temp(v, ctx.unit) for v in recent_mean_r], dtype="float64")
    delta_mean_r_local = np.asarray([convert_temp(v, ctx.unit) for v in delta_mean_r], dtype="float64")
    custom_overlay = np.column_stack([past_mean_r_local, recent_mean_r_local, delta_mean_r_local, delta_str]).tolist() # (12,4)

    return {
        "x": x,
        "month_labels": month_labels_shifted,
        "shift": shift,
        "ihot": ihot,

        # mean overlay (trend-evaluated)
        "past_mean": past_mean_r,
        "recent_mean": recent_mean_r,
        "delta_mean": delta_mean_r,
        "custom_overlay": custom_overlay,

        # envelopes (trend-evaluated)
        "past_min": past_min_r,
        "past_max": past_max_r,
        "recent_min": recent_min_r,
        "recent_max": recent_max_r,

        # optional metadata if you want it later
        "early_years_by_month": early_years,
        "recent_years_by_month": recent_years,
    }

def build_seasons_then_now_figure(ctx: StoryContext, facts: StoryFacts, data: dict) -> go.Figure:
    """
    Overlay: earlier vs recent monthly mean climatology (trend-evaluated),
    already rotated so warmest recent month is centered.
    """
    x = data["x"]
    labels = data["month_labels"]
    past_r = data["past_mean"]
    recent_r = data["recent_mean"]
    custom = data["custom_overlay"]

    fig = go.Figure()

    # Earlier climate – blue
    past_r_local = np.asarray([convert_temp(v, ctx.unit) for v in past_r], dtype="float64")
    fig.add_trace(
        go.Scatter(
            x=x,
            y=past_r_local,
            mode="lines+markers",
            name="Earlier climate",
            line=dict(color="rgba(38,139,210,0.9)", width=2, shape="spline"),
            marker=dict(size=6),
            customdata=custom,
            text=labels,
            hovertemplate=(
                "%{text}: %{customdata[3]}<br>"
                "Earlier: %{customdata[0]:.1f}" + ctx.unit + "<br>"
                "Recent: %{customdata[1]:.1f}" + ctx.unit + ""
                "<extra></extra>"
            ),
        )
    )

    # Recent climate – red
    recent_r_local = np.asarray([convert_temp(v, ctx.unit) for v in recent_r], dtype="float64")
    fig.add_trace(
        go.Scatter(
            x=x,
            y=recent_r_local,
            mode="lines+markers",
            name="Recent climate",
            line=dict(color="rgba(217,95,2,0.9)", width=2, shape="spline"),
            marker=dict(size=6),
            customdata=custom,
            text=labels,
            hovertemplate=(
                "%{text}: %{customdata[3]}<br>"
                "Earlier: %{customdata[0]:.1f}" + ctx.unit + "<br>"
                "Recent: %{customdata[1]:.1f}" + ctx.unit + "<extra></extra>"
            ),
        )
    )

    y_all = np.concatenate([past_r_local, recent_r_local])
    y_min = float(np.nanmin(y_all))
    y_max = float(np.nanmax(y_all))
    span = max(y_max - y_min, convert_delta(5.0, ctx.unit))
    pad = span * 0.1
    y_center = 0.5 * (y_min + y_max)
    y0 = y_center - span / 2.0 - pad
    y1 = y_center + span / 2.0 + pad

    fig.update_layout(
        title=f"How your seasons have shifted – {ctx.location_label}",
        xaxis=dict(
            title="Month",
            tickmode="array",
            tickvals=x,
            ticktext=labels,
            showgrid=True,
            gridcolor="rgba(220,220,220,0.3)",
        ),
        yaxis=dict(
            title=f"Typical monthly temperature (%s)" % ctx.unit,
            range=[y0, y1],
        ),
        margin=dict(l=40, r=160, t=60, b=40),
        legend=dict(
            orientation="v",
            x=1.02,
            xanchor="left",
            y=1.0,
        ),
    )

    label_early = data.get("early_label", f"{facts.data_start_year}–{facts.data_start_year + 9}")
    label_recent = data.get("recent_label", f"{facts.data_end_year - 9}–{facts.data_end_year}")
    caption = (
        f"Earlier climate: {label_early}, recent climate: {label_recent} "
        "(based on ERA5 2m temperature via Open-Meteo)."
    )

    return fig, caption

def build_seasons_then_now_separate_figures(ctx: StoryContext, facts: StoryFacts, data: dict) -> tuple[go.Figure, go.Figure]:
    """
    Returns (fig_env_past, fig_env_recent) for min/mean/max monthly envelopes,
    using the SAME shifted month axis as the overlay figure.
    """
    months = data["x"]
    labels = data["month_labels"]

    past_min = data["past_min"]
    past_mean = data["past_mean"]
    past_max = data["past_max"]

    recent_min = data["recent_min"]
    recent_mean = data["recent_mean"]
    recent_max = data["recent_max"]

    def _env_figure(title: str, mmin, mmean, mmax) -> go.Figure:
        fig = go.Figure()

        # 1) Min line
        mmin_local = np.asarray([convert_temp(v, ctx.unit) for v in mmin], dtype="float64")
        fig.add_trace(
            go.Scatter(
                x=months,
                y=mmin_local,
                mode="lines",
                name="Monthly min",
                line=dict(color="rgba(38,139,210,1.0)", width=2, shape="spline"),
                hovertemplate="%{x}<br>Minimum: %{y:.1f}" + ctx.unit + "<extra></extra>"
            )
        )
        # 2) Mean line (grey), fill between min and mean in blue
        mmean_local = np.asarray([convert_temp(v, ctx.unit) for v in mmean], dtype="float64")
        fig.add_trace(
            go.Scatter(
                x=months,
                y=mmean_local,
                mode="lines",
                name="Monthly mean",
                line=dict(color="rgba(120,120,120,1.0)", width=2, shape="spline"),
                fill="tonexty",
                fillcolor="rgba(158,202,225,0.3)",
                hovertemplate="%{x}<br>Mean: %{y:.1f}" + ctx.unit + "<extra></extra>"
            )
        )
        # 3) Max line, fill between mean and max in red
        mmax_local = np.asarray([convert_temp(v, ctx.unit) for v in mmax], dtype="float64")
        fig.add_trace(
            go.Scatter(
                x=months,
                y=mmax_local,
                mode="lines",
                name="Monthly max",
                line=dict(color="rgba(220,50,47,1.0)", width=2, shape="spline"),
                fill="tonexty",
                fillcolor="rgba(244,165,130,0.3)",
                hovertemplate="%{x}<br>Maximum: %{y:.1f}" + ctx.unit + "<extra></extra>"
            )
        )

        fig.update_layout(
            height=280,
            margin=dict(l=40, r=20, t=48, b=40),
            yaxis_title=f"Daily temperature (%s)" % ctx.unit,
            xaxis_title="Month",
            xaxis=dict(
                tickmode="array",
                tickvals=months,
                ticktext=labels,
                showgrid=True,
                gridcolor="rgba(220,220,220,0.25)",
            ),
            title=title,
            showlegend=False,
        )
        return fig

    fig_env_past = _env_figure("Earlier climate (monthly min–mean–max)", past_min, past_mean, past_max)
    fig_env_recent = _env_figure("Recent climate (monthly min–mean–max)", recent_min, recent_mean, recent_max)

    return fig_env_past, fig_env_recent


def seasons_then_now_caption(ctx: StoryContext, facts: StoryFacts, data: dict) -> str:
    """
    Caption for the 'Seasons then vs now' overlay (mean curves).
    Uses shifted month axis + trend-evaluated deltas from build_seasons_then_now_data().
    """
    base = (
        "Here we compare a **typical year in the earlier climate** (blue) to a "
        "**typical year in the recent climate** (orange)."
    )

    if not data:
        return base

    delta = np.asarray(data["delta_mean"], dtype="float64")
    recent = np.asarray(data["recent_mean"], dtype="float64")
    month_names = list(data["month_labels"])

    mean_delta = float(np.nanmean(delta))
    max_delta = float(np.nanmax(delta))
    min_delta = float(np.nanmin(delta))

    # Month with strongest warming
    imax = int(np.nanargmax(delta))
    warmest_shift_month = month_names[imax]
    warmest_shift_value = float(delta[imax])

    # Month with strongest cooling (if any)
    imin = int(np.nanargmin(delta))
    coolest_shift_month = month_names[imin]
    coolest_shift_value = float(delta[imin])

    # Hottest month in the recent climate – “summer”
    ihot = int(np.nanargmax(recent))
    summer_month = month_names[ihot]
    summer_delta = float(delta[ihot])

    extra_parts: list[str] = []

    # Overall offset
    if mean_delta > 0.8:
        extra_parts.append(
            f" On average, the recent climate is about **{fmt_delta(mean_delta, ctx.unit)} warmer** "
            "throughout the year."
        )
    elif mean_delta > 0.3:
        extra_parts.append(
            f" Overall, the recent climate runs about **{fmt_delta(mean_delta, ctx.unit)} warmer** "
            "than the earlier period."
        )
    elif mean_delta < -0.8:
        extra_parts.append(
            f" Surprisingly, the recent climate here is about "
            f"**{fmt_delta(abs(mean_delta), ctx.unit, sign=False)} cooler** on average than the earlier period."
        )
    elif mean_delta < -0.3:
        extra_parts.append(
            f" On average, the recent climate is about **{fmt_delta(abs(mean_delta), ctx.unit, sign=False)} cooler** "
            "than it used to be."
        )
    else:
        extra_parts.append(
            " Overall, the **seasonal pattern hasn't changed much** – any differences "
            "are small compared with year-to-year weather noise."
        )

    # Always say something season-specific
    if abs(summer_delta) >= 0.3:
        if summer_delta > 0:
            extra_parts.append(
                f" In **{summer_month}**, typically one of the warmest months, "
                f"the recent climate is about **{fmt_delta(summer_delta, ctx.unit)} warmer** than before."
            )
        else:
            extra_parts.append(
                f" In **{summer_month}**, one of the warmest months, the recent climate is "
                f"about **{fmt_delta(abs(summer_delta), ctx.unit, sign=False)} cooler** than the earlier period."
            )
    else:
        max_abs = max(abs(max_delta), abs(min_delta))
        if max_abs >= 0.3:
            if abs(max_delta) >= abs(min_delta):
                m, v = warmest_shift_month, warmest_shift_value
            else:
                m, v = coolest_shift_month, coolest_shift_value
            extra_parts.append(
                f" The largest monthly shift is in **{m}**, at about **{fmt_delta(v, ctx.unit)}** "
                "compared to the earlier climate."
            )
        else:
            extra_parts.append(
                " Month by month, the earlier and recent curves sit almost on top of each other "
                "(differences are within a few tenths of a degree)."
            )

    # Tie back to long-term warming if available
    if facts.total_warming_50y is not None and abs(facts.total_warming_50y) > 0.3:
        extra_parts.append(
            f" These seasonal changes are one way that the roughly "
            f"**{fmt_delta(facts.total_warming_50y, ctx.unit)}** long-term warming at this location "
            "shows up in everyday weather."
        )
    elif facts.total_warming_50y is not None and abs(facts.total_warming_50y) <= 0.3:
        extra_parts.append(
            " The long-term trend we saw in the 50-year graph is very small here, so it's "
            "not surprising that the typical seasons look almost unchanged."
        )

    return base + " " + " ".join(extra_parts)

EPS = 0.05  # treat anything smaller than 0.05°C as “no change”

def clean_zero(x: float) -> float:
    # Avoid printing “-0.0”
    if abs(x) < 0.0005:
        return 0.0
    return x

def describe_change(ctx: StoryContext, x: float) -> str:
    x = clean_zero(x)
    if abs(x) < EPS:
        return "about the same (≈0.0°C)"
    return f"{fmt_delta(abs(x), ctx.unit, sign=False)} {'warmer' if x > 0 else 'cooler'}"

def seasons_then_now_separate_caption(ctx: StoryContext, facts: StoryFacts, data: dict) -> str:
    labels = list(data["month_labels"])

    past_mean = np.asarray(data["past_mean"], dtype="float64")
    recent_mean = np.asarray(data["recent_mean"], dtype="float64")
    delta_mean = np.asarray(data["delta_mean"], dtype="float64")

    past_range = np.asarray(data["past_max"], dtype="float64") - np.asarray(data["past_min"], dtype="float64")
    recent_range = np.asarray(data["recent_max"], dtype="float64") - np.asarray(data["recent_min"], dtype="float64")
    delta_range = recent_range - past_range

    # Summer = warmest 3 months in the RECENT climate (robust across hemispheres)
    order_hot = np.argsort(recent_mean)  # ascending
    hot_idx = order_hot[-3:]
    cool_idx = order_hot[:3]

    summer_delta = float(np.nanmean(delta_mean[hot_idx]))
    cool_delta = float(np.nanmean(delta_mean[cool_idx]))

    # biggest widening/narrowing month for the envelope range
    i_wide = int(np.nanargmax(delta_range))
    i_narr = int(np.nanargmin(delta_range))
    wide = float(delta_range[i_wide])
    narr = float(delta_range[i_narr])
    avg_change = float(np.nanmean(delta_range))

    # Always include the “summer vs cooler months” bullets
    summer_desc = describe_change(ctx, summer_delta)
    cool_desc = describe_change(ctx, cool_delta)
    bullets = (
        f"- Summer months are **{summer_desc}** compared with the earlier period.\n"
        f"- Cooler months are **{cool_desc}**.\n"
    )

    tail = (
        "The envelopes above show how the **range** of daily temperatures within each month has changed: "
        "not just the average, but also the typical **coldest** and **hottest** days of each month."
    )

    return (
        f"In **{ctx.location_label}**, the typical year has shifted:\n\n"
        f"{bullets}\n"
        f"{tail}"
    )

