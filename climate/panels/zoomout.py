import xarray as xr
import plotly.graph_objs as go
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

from climate.models import StoryFacts, StoryContext
from climate.panels.helpers import add_trace, add_mean_trace, annotate_minmax_on_series
from climate.openmeteo import fetch_recent_7d, fetch_recent_30d
from climate.units import fmt_temp, fmt_delta, convert_temp, convert_delta
from climate.analytics import estimate_30d_trend, season_phrase
from climate.io import dataset_coverage_text

# -----------------------------------------------------------
# Compute last week data, graph and captions
# -----------------------------------------------------------

def build_last_week_data(ctx: StoryContext) -> dict:
    """
    Prepare the data needed for the 'Last week' panel.

    Uses:
      - time_hourly
      - t_hourly
      - time_daily
      - t_daily_mean
    Returns a dict so it's easy to plug into other front-ends later.
    """
    # Use last full day as the endpoint (yesterday)
    end_7d = ctx.today - timedelta(days=1)

    ds_7d = fetch_recent_7d(ctx.slug, ctx.location_lat, ctx.location_lon, end_7d)
    if ds_7d is None:
        return None

    t_hourly = pd.to_datetime(ds_7d["time_hourly"].values)
    temp_hourly = ds_7d["t_hourly"].values

    t_daily_mid = pd.to_datetime(ds_7d["time_daily"].values) + pd.Timedelta(hours=12)
    temp_daily = ds_7d["t_daily_mean"].values

    range = ds_7d.attrs.get('range', end_7d.isoformat())

    return {
        "time_hourly" : t_hourly,
        "temp_hourly" : temp_hourly,
        "time_daily" : t_daily_mid,
        "temp_daily" : temp_daily,
        "range" : range,
    }

def build_last_week_figure(ctx: StoryContext, facts: StoryFacts, data: dict) -> (go.Figure, str):
    """
    Build the Plotly figure for the last-week.

    Styling is consistent with other panels:
      - grey noisy curve (daily)
      - blue smooth curve (7-day mean)
      - min/max annotations via annotate_minmax_on_series()
    """
    fig = go.Figure()

    # Hourly temp (light grey)
    temp_hourly_local = np.asarray([convert_temp(v, ctx.unit) for v in data["temp_hourly"]], dtype="float64")
    add_trace(fig, data["time_hourly"], temp_hourly_local, "Hourly", hovertemplate="%{x|%Y-%m-%d %H:%M}<br>%{y:.1f}" + ctx.unit + "<extra></extra>")

    # Daily mean (blue-ish)
    temp_daily_local = np.asarray([convert_temp(v, ctx.unit) for v in data["temp_daily"]], dtype="float64")
    add_mean_trace(fig, data["time_daily"], temp_daily_local, "Daily mean", showmarkers=True, hovertemplate="%{x|%Y-%m-%d}<br>Daily mean: %{y:.1f}" + ctx.unit + "<extra></extra>")

    annotate_minmax_on_series(fig, data["time_hourly"], temp_hourly_local, ctx.unit, label_prefix="")

    fig.update_layout(
        margin=dict(l=0, r=0, t=10, b=40),
        height=320,
        showlegend=True,
        legend=dict(
            orientation="v",
            yanchor="top",
            y=1.0,
            xanchor="left",
            x=1.02,
        ),
        xaxis=dict(
            title="Date",
            showgrid=True,
            gridcolor="rgba(200,200,200,0.3)",
        ),
        yaxis=dict(
            title=f"Temperature (%s)" % ctx.unit,
            showgrid=True,
            gridcolor="rgba(200,200,200,0.3)",
        ),
    )

    range = data["range"]
    caption = f"Range: {range}"

    return fig, caption


def last_week_caption(ctx: StoryContext, facts: StoryFacts, data: dict) -> str:
    """
    Generate the markdown caption for the last-week panel
    using StoryFacts (so it's easy to reuse elsewhere).
    """
    return """
    Over a single week you can see the **heartbeat of days and nights**: temperatures
    rise during the day, fall at night, and swing with passing weather systems.
    """

# -----------------------------------------------------------
# Compute last month data, graph and captions
# -----------------------------------------------------------

def build_last_month_data(ctx: StoryContext) -> dict:
    """
    Prepare the data needed for the 'Last month' panel.

    Uses:
      - time-daily
      - t_daily_mean
    Returns a dict so it's easy to plug into other front-ends later.
    """
    end_30d = ctx.today - timedelta(days=1)

    ds_30d = fetch_recent_30d(ctx.slug, ctx.location_lat, ctx.location_lon, end_30d)
    if ds_30d is None:
        return None

    t_daily_30 = pd.to_datetime(ds_30d["time_daily"].values)
    tmean_30 = ds_30d["t_daily_mean"].values

    trend_30d = estimate_30d_trend(t_daily_30, tmean_30)
    trend_sentence = ""

    if not np.isnan(trend_30d) and abs(trend_30d) >= 0.5:
        # threshold: ≈ ±0.5°C over 30 days to be "noticeable"
        direction = "rising" if trend_30d > 0 else "falling"
        sign_word = "warmer" if trend_30d > 0 else "cooler"
        season = season_phrase(ctx.location_lat, t_daily_30[-1])
        trend_sentence = (
            f" Over this 30-day window, daily averages have been **{direction}** "
            f"by about {fmt_delta(trend_30d, ctx.unit)}, consistent with {season}."
        )

    # 3-day rolling mean
    mean_3d = pd.Series(tmean_30, index=t_daily_30).rolling(window=3, center=True).mean().values

    return {
        "time_daily" : t_daily_30,
        "temp_daily" : tmean_30,
        "temp_3d_mean" : mean_3d,
        "trend_sentence" : trend_sentence,
        "range" : ds_30d.attrs.get('range', end_30d.isoformat()),
    }

def build_last_month_figure(ctx: StoryContext, facts: StoryFacts, data: dict) -> (go.Figure, str):
    """
    Build the Plotly figure for the last-month seasonal cycle.

    Styling is consistent with other panels:
      - grey noisy curve (daily)
      - blue smooth curve (7-day mean)
      - min/max annotations via annotate_minmax_on_series()
    """
    fig = go.Figure()

    temp_daily_local = np.asarray([convert_temp(v, ctx.unit) for v in data["temp_daily"]], dtype="float64")
    add_trace(fig, data["time_daily"], temp_daily_local, "Daily mean", "%{x|%Y-%m-%d}<br>Daily mean: %{y:.1f}" + ctx.unit + "<extra></extra>")

    # 3-day mean (blue)
    temp_3d_mean_local = np.asarray([convert_temp(v, ctx.unit) for v in data["temp_3d_mean"]], dtype="float64")
    add_mean_trace(fig, data["time_daily"], temp_3d_mean_local, "3-day mean", hovertemplate="%{x|%Y-%m-%d}<br>3-day mean: %{y:.1f}" + ctx.unit + "<extra></extra>")

    annotate_minmax_on_series(fig, data["time_daily"], temp_daily_local, ctx.unit, label_prefix="")

    fig.update_layout(
        margin=dict(l=0, r=0, t=10, b=40),
        height=320,
        showlegend=True,
        legend=dict(
            orientation="v",
            yanchor="top",
            y=1.0,
            xanchor="left",
            x=1.02,
        ),
        xaxis=dict(
            title="Date",
            showgrid=True,
            gridcolor="rgba(200,200,200,0.3)",
        ),
        yaxis=dict(
            title=f"Temperature (%s)" % ctx.unit,
            showgrid=True,
            gridcolor="rgba(200,200,200,0.3)",
        ),
    )

    range = data["range"]
    caption = f"Range: {range}"
    return fig, caption

def last_month_caption(ctx: StoryContext, facts: StoryFacts, data: dict) -> str:
    """
    Generate the markdown caption for the last-month panel
    using StoryFacts (so it's easy to reuse elsewhere).
    """
    trend_sentence = data["trend_sentence"]
    base_text = """
    Here we’re looking at **daily averages**, not the full day–night cycle.
    Over a month, the jagged ups and downs reflect **passing weather systems**:
    short warm spells, cooler snaps, and the background shift between seasons.
    """

    return base_text + ("" if not trend_sentence else "\n\n" + trend_sentence)

# -----------------------------------------------------------
# Compute last year data, graph and captions
# -----------------------------------------------------------

def build_last_year_data(ctx: StoryContext) -> dict:
    """
    Prepare the data needed for the 'Last year — the seasonal cycle' panel.

    Uses:
      - time_daily
      - t2m_daily_mean_c
    Returns a dict so it's easy to plug into other front-ends later.
    """
    t_daily = ctx.ds["t2m_daily_mean_c"]  # (time)
    time_all = pd.to_datetime(t_daily["time"].values)
    temp_all = t_daily.values

    # Take the last 12 FULL calendar months in the dataset
    last_day = time_all.max()
    if pd.Timestamp(ctx.today) < last_day:
        last_day = pd.Timestamp(ctx.today)

    # First day of last month in dataset
    end_month_start = last_day.replace(day=1)
    # First day 11 months earlier (gives 12 months total)
    start_month_start = (end_month_start - pd.DateOffset(months=11)).normalize()

    mask = (time_all >= start_month_start) & (time_all <= last_day)
    time_last = time_all[mask]
    temp_last = temp_all[mask]

    s_daily = pd.Series(temp_last, index=time_last)
    s_smooth = s_daily.rolling(window=7, center=True, min_periods=2).mean()

    # --- 3. Find min / max over this last year ---
    imax = int(np.nanargmax(s_daily.values))
    imin = int(np.nanargmin(s_daily.values))
    t_max = s_daily.index[imax]
    t_min = s_daily.index[imin]
    v_max = float(s_daily.values[imax])
    v_min = float(s_daily.values[imin])

    return {
        "time_daily": time_last,
        "temp_daily_mean": s_daily.values,
        "temp_7d": s_smooth.values,
        "last_day": last_day,
        "start_month": start_month_start,
    }


def build_last_year_figure(ctx: StoryContext, facts: StoryFacts, data: dict) -> (go.Figure, str):
    """
    Build the Plotly figure for the last-year seasonal cycle.

    Styling is consistent with other panels:
      - grey noisy curve (daily)
      - blue smooth curve (7-day mean)
      - min/max annotations via annotate_minmax_on_series()
    """
    fig = go.Figure()

    time_daily = data["time_daily"]

    # Noisy base curve
    t_daily_local = np.asarray([convert_temp(v, ctx.unit) for v in data["temp_daily_mean"]], dtype="float64")
    add_trace(
        fig,
        x=time_daily,
        y=t_daily_local,
        name="Daily mean",
        hovertemplate="%{x|%d %b %Y}<br>Daily mean: %{y:.1f}" + ctx.unit + "<extra></extra>",
    )

    # Smooth curve
    t_7d_local = np.asarray([convert_temp(v, ctx.unit) for v in data["temp_7d"]], dtype="float64")
    add_mean_trace(
        fig,
        x=time_daily,
        y=t_7d_local,
        name="7-day mean",
        showmarkers=False,
        hovertemplate="%{x|%d %b %Y}<br>7-day mean: %{y:.1f}" + ctx.unit + "<extra></extra>",
    )

    # Min/max annotations on the smooth curve
    annotate_minmax_on_series(fig, time_daily, t_daily_local, ctx.unit, label_prefix="")

    fig.update_layout(
        height=400,
        xaxis=dict(
            title="Date",
            showgrid=True,
            gridcolor="rgba(200,200,200,0.3)",
        ),
        yaxis=dict(
            title=f"Temperature (%s)" % ctx.unit,
            zeroline=False,
        ),
        margin=dict(l=40, r=20, t=30, b=40),
        showlegend=True,
    )

    start_label = data["start_month"].strftime("%b %Y")
    end_label = data["last_day"].strftime("%b %Y")
    caption = f"Source: OpenMeteo | Range: last 12 months in dataset ({start_label} – {end_label})"

    return fig, caption

def last_year_caption(ctx: StoryContext,facts: StoryFacts, data: dict) -> str:
    """
    Generate the markdown caption for the last-year panel
    using StoryFacts (so it's easy to reuse elsewhere).
    """
    mean7 = np.asarray(data["temp_7d"], dtype="float64")
    amp = float(np.nanmax(mean7) - np.nanmin(mean7))
    
    if amp >= 8.0:
        # strong winters/summers – classic temperate
        base_text = (
            "Over a full year you can clearly see the **seasonal cycle**: the rise into the "
            "hottest months and the slide back down into the coolest ones. Climate change adds a slow upward "
            "shift on top of this familiar pattern."
        )
    elif amp >= 4.0:
        # moderate seasons
        base_text = (
            "Here the seasonal cycle is visible but fairly gentle: the 7-day mean temperature "
            "nudges up into a warmer part of the year, then back down again, without dramatic swings. "
            "Climate change adds a slow upward shift on top of this pattern."
        )
    else:
        # almost flat year-round (e.g. Singapore)
        base_text = (
            "Over a full year the 7-day mean stays in a narrow band – **seasons are weak** here. "
            "Rather than sharp winters and summers, most days sit in roughly the same temperature range. "
            "Climate change adds a slow upward shift on top of this pattern."
        )
    
    extra = ""
    if facts.last_year_anomaly is not None:
        anom = facts.last_year_anomaly
        if anom > 0.8:
            extra = (
                f" This particular year was about **{fmt_delta(anom, ctx.unit)} warmer** than the "
                "long-term average for this location."
            )
        elif anom > 0.3:
            extra = (
                f" This particular year was **slightly warmer than usual**, roughly "
                f"{fmt_delta(anom, ctx.unit)} above the long-term average."
            )
        elif anom < -0.8:
            extra = (
                f" This particular year was about **{fmt_delta(abs(anom), ctx.unit, sign=False)} cooler** than the "
                "long-term average here."
            )
        elif anom < -0.3:
            extra = (
                f" This particular year ran **a bit cooler than usual**, around "
                f"{fmt_delta(abs(anom), ctx.unit)} below the long-term average."
            )

    return base_text + "\n" + extra

# -----------------------------------------------------------
# Compute last five year data, graph and captions
# -----------------------------------------------------------

def build_five_year_data(ctx: StoryContext) -> dict:
    """
    Prepare the data needed for the 'Last 5 years — zoom from seasons to climate' panel.

    Uses:
      - time_daily
      - t2m_daily_mean_c
      - t2m_monthly_mean_c
    Returns a dict so it's easy to plug into other front-ends later.
    """

    # Daily mean temperature (precomputed), with explicit 'time' coord
    da_daily = ctx.ds["t2m_daily_mean_c"]
    time_daily = pd.to_datetime(da_daily["time"].values)

    # End of record = last timestamp in daily series
    end_date = time_daily[-1].normalize()
    if pd.Timestamp(ctx.today) < end_date:
        end_date = pd.Timestamp(ctx.today)

    # Start 5 years earlier
    start_5y = end_date - pd.DateOffset(years=5)

    # If the record is shorter than 5 years for some reason, just use full range
    if time_daily[0] > start_5y:
        start_5y = time_daily[0]

    # Slice daily data to last ~5 years
    daily_5y = da_daily.sel(time=slice(start_5y, end_date))

    # 7-day rolling mean (centered)
    weekly_5y = daily_5y.rolling(time=7, center=True).mean()

    # Monthly mean series (precomputed, but we don't assume coord is named 'time')
    da_mon = ctx.ds["t2m_monthly_mean_c"]

    # Use first dimension and its coord as the monthly time axis, whatever it's called
    mon_dim = da_mon.dims[0]                      # e.g. "time" or "valid_time" or "month"
    mon_coord = pd.to_datetime(da_mon[mon_dim].values)

    # Mask to last ~5 years
    mon_mask = (mon_coord >= start_5y) & (mon_coord <= end_date)
    monthly_5y = da_mon.isel({mon_dim: mon_mask})
    x_month = mon_coord[mon_mask]

    return {
        "time_weekly": pd.to_datetime(weekly_5y.time.values),
        "temp_weekly": weekly_5y.values,
        "time_monthly": x_month,
        "temp_monthly": monthly_5y.values,
    }

def build_five_year_figure(ctx: StoryContext, facts: StoryFacts, data: dict) -> (go.Figure, str):
    """
    Build the Plotly figure for the last-five-year seasonal cycle.

    Styling is consistent with other panels:
      - grey noisy curve (daily)
      - blue smooth curve (7-day mean)
      - min/max annotations via annotate_minmax_on_series()
    """
    fig = go.Figure()

    # 7-day mean (grey, light)
    temp_weekly_local = np.asarray([convert_temp(v, ctx.unit) for v in data["temp_weekly"]], dtype="float64")
    add_trace(
        fig,
        data["time_weekly"],
        temp_weekly_local,
        "7-day mean",
        hovertemplate="%{x|%Y-%m-%d}<br>7-day mean: %{y:.1f}" + ctx.unit + "<extra></extra>"
    )

    # Monthly mean (warmer color, thicker)
    temp_monthly_local = np.asarray([convert_temp(v, ctx.unit) for v in data["temp_monthly"]], dtype="float64")
    add_mean_trace(fig, data["time_monthly"], temp_monthly_local, "Monthly mean", hovertemplate="%{x|%Y-%m}<br>Monthly mean: %{y:.1f}" + ctx.unit + "<extra></extra>")

    fig.update_layout(
        margin=dict(l=0, r=0, t=10, b=40),
        height=320,
        showlegend=True,
        xaxis=dict(
            title="Year",
            showgrid=True,
            gridcolor="rgba(200,200,200,0.3)",
        ),
        yaxis=dict(
            title=f"Temperature (%s)" % ctx.unit,
            showgrid=True,
            gridcolor="rgba(200,200,200,0.3)",
        ),
    )

    caption = "Source: OpenMeteo"
    cov = dataset_coverage_text(ctx.ds)
    if cov:
        caption += f" | {cov}"

    return fig, caption

def five_year_caption(ctx: StoryContext, facts: StoryFacts, data: dict) -> str:
    """
    Generate the markdown caption for the last-five-year panel
    using StoryFacts (so it's easy to reuse elsewhere).
    """
    base_5y = (
        "Over the last five years, the shorter-term wiggles (the 7-day mean) sit on top of a smoother monthly pattern. "
        "As you zoom out, weather becomes noise and you start to see the underlying climate: which seasons are warming "
        "the most, and how often the line pushes into new territory."
    )

    extra_5y = ""
    if facts.recent_warming_10y is not None and facts.total_warming_50y is not None:
        short = facts.recent_warming_10y
        long_ = facts.total_warming_50y

        if abs(short) < 0.3 and abs(long_) > 0.8:
            # Short-term trend is subtle, but long-term is clear
            extra_5y = (
                "At this scale, the warming is **subtle** – these recent years only hint "
                "at a change. The bigger shift really jumps out when you zoom all the way "
                "out to the full record below."
            )
        elif abs(short) >= 0.3:
            direction = "warmer" if short >= 0 else "cooler"
            extra_5y = (
                f"Even over just these recent years, the smoothed curve points to a change "
                f"equivalent to about {fmt_delta(short, ctx.unit)} per decade. That trend connects directly "
                "to the longer-term shift you’ll see in the 50-year view."
        )

    return base_5y + " " + extra_5y

# -----------------------------------------------------------
# Compute fifty year data, graph and captions
# -----------------------------------------------------------

def build_fifty_year_data(ctx: StoryContext) -> dict:
    """
    Prepare the data needed for the 'Last 50 years — monthly averages and trend' panel.

    Uses:
      - time_monthly
      - t2m_monthly_mean_c
      - time_yearly
      - t2m_yearly_mean_c
    Returns a dict so it's easy to plug into other front-ends later.
    """
    # --- 1. Load real data for this location ---
    da_mon = ctx.ds["t2m_monthly_mean_c"]  # (time_monthly)
    time_mon = pd.to_datetime(da_mon["time_monthly"].values)
    temp_mon = da_mon.values

    # --- 2. Yearly mean and 5-year running mean (from the monthly series) ---
    monthly_da = xr.DataArray(
        temp_mon,
        coords={"time_monthly": time_mon},
        dims=["time_monthly"],
        name="t2m_monthly_mean_c",
    )

    yearly_mean = monthly_da.groupby("time_monthly.year").mean("time_monthly")
    years = yearly_mean["year"].values.astype(float)
    t_year = yearly_mean.values

    # 5-year running mean on yearly series
    da_year = ctx.ds["t2m_yearly_mean_c"]
    time_year = pd.to_datetime(ctx.ds["time_yearly"].values)
    temps_year = np.asarray(da_year.values, dtype="float64")

    # --- 3. Coldest & warmest months per year and their linear trends ---
    cold_by_year = monthly_da.groupby("time_monthly.year").min("time_monthly")
    warm_by_year = monthly_da.groupby("time_monthly.year").max("time_monthly")

    cold_years = cold_by_year["year"].values.astype(float)
    warm_years = warm_by_year["year"].values.astype(float)
    cold_vals = cold_by_year.values
    warm_vals = warm_by_year.values

    cold_trend = warm_trend = None
    if len(cold_years) >= 2:
        coef_cold = np.polyfit(cold_years, cold_vals, 1)
        cold_trend = np.polyval(coef_cold, cold_years)
    if len(warm_years) >= 2:
        coef_warm = np.polyfit(warm_years, warm_vals, 1)
        warm_trend = np.polyval(coef_warm, warm_years)

    coldest_month_trend_50y = float(cold_trend[-1] - cold_trend[0])
    warmest_month_trend_50y = float(warm_trend[-1] - warm_trend[0])

    # Linear trend
    mask = np.isfinite(temps_year)
    if mask.sum() >= 5:
        x = years[mask]
        y = temps_year[mask]
        # Linear trend on yearly means (red) – as a true straight line in time
        slope, intercept = np.polyfit(x, y, 1)

        # Continuous year grid
        trend_years = np.linspace(x.min(), x.max(), 200)
        # Map fractional years -> datetimes (approximate using 365.25 days per year)
        ref_start = pd.Timestamp(f"{int(x.min())}-01-01")
        trend_dates = ref_start + pd.to_timedelta((trend_years - x.min()) * 365.25, unit="D")
        trend_vals = intercept + slope * trend_years
        
        # For caption later
        total_span_years = int(x.max() - x.min())
        total_warming = float(trend_vals[-1] - trend_vals[0])
    else:
        trend_dates = None
        trend_vals = None
        total_span_years = None
        total_warming = None

    return {
        "time_monthly" : time_mon,
        "temp_monthly" : temp_mon,
        "time_yearly" : time_year,
        "temp_yearly" : temps_year,
        "cold_years" : cold_years,
        "cold_trend" : cold_trend,
        "warm_years" : warm_years,
        "warm_trend" : warm_trend,
        "time_trend" : trend_dates,
        "temp_trend" : trend_vals,
        "total_span_years" : total_span_years,
        "total_warming" : total_warming,
        "coldest_month_trend_50y" : coldest_month_trend_50y,
        "warmest_month_trend_50y" : warmest_month_trend_50y,
    }


def build_fifty_year_figure(ctx: StoryContext, facts: StoryFacts, data: dict) -> (go.Figure, str):
    """
    Build the Plotly figure for the last-fifty-years cycle.

    Styling is consistent with other panels:
      - grey noisy curve (daily)
      - blue smooth curve (7-day mean)
      - min/max annotations via annotate_minmax_on_series()
    """
    # --- 4. Build the figure using your original styling ---
    fig = go.Figure()

    # Monthly mean (thin grey spline)
    temp_monthly_local = np.asarray([convert_temp(v, ctx.unit) for v in data["temp_monthly"]], dtype="float64")
    add_trace(fig, data["time_monthly"], temp_monthly_local, "Monthly mean")

    temp_yearly_local = np.asarray([convert_temp(v, ctx.unit) for v in data["temp_yearly"]], dtype="float64")
    add_mean_trace(
        fig,
        x=data["time_yearly"],
        y=temp_yearly_local,
        name="Yearly mean",
        showmarkers=True,
        hovertemplate="Year %{x|%Y}<br>%{y:.1f}" + ctx.unit + "<extra></extra>",
    )

    # Linear trend
    if data["temp_trend"] is not None:
        temp_trend_local = np.asarray([convert_temp(v, ctx.unit) for v in data["temp_trend"]], dtype="float64")
        fig.add_trace(
            go.Scatter(
                x=data["time_trend"],
                y=temp_trend_local,
                mode="lines",
                name="Trend (yearly mean)",
                line=dict(color="rgba(220,50,47,0.9)", width=3, shape="linear"),
                hovertemplate="Trend %{x|%Y}<br>%{y:.1f}" + ctx.unit + "<extra></extra>",
            )
        )

    # Coldest-month trend (blue dotted spline)
    if data["cold_trend"] is not None:
        x_cold = [datetime(int(y), 1, 1) for y in data["cold_years"]]
        cold_trend_local = np.asarray([convert_temp(v, ctx.unit) for v in data["cold_trend"]], dtype="float64")
        fig.add_trace(
            go.Scatter(
                x=x_cold,
                y=cold_trend_local,
                mode="lines",
                name="Coldest-month trend",
                line=dict(
                    color="rgba(38,139,210,0.9)",
                    width=2,
                    dash="dot",
                    shape="spline",
                ),
            )
        )
        fig.add_annotation(
            x=x_cold[-1], y=float(cold_trend_local[-1]),
            showarrow=False,
            text=f"{fmt_delta(data['coldest_month_trend_50y'], ctx.unit)} over {facts.data_end_year - facts.data_start_year}y",
            font=dict(color="rgba(38,139,210,0.9)", size=11),
            xanchor="left",
            yanchor="top",
        )

    # Warmest-month trend (red dotted spline)
    if data["warm_trend"] is not None:
        x_warm = [datetime(int(y), 7, 1) for y in data["warm_years"]]
        warm_trend_local = np.asarray([convert_temp(v, ctx.unit) for v in data["warm_trend"]], dtype="float64")
        fig.add_trace(
            go.Scatter(
                x=x_warm,
                y=warm_trend_local,
                mode="lines",
                name="Warmest-month trend",
                line=dict(
                    color="rgba(220,50,47,0.9)",
                    width=2,
                    dash="dot",
                    shape="spline",
                ),
            )
        )
        fig.add_annotation(
            x=x_warm[-1], y=float(warm_trend_local[-1]),
            showarrow=False,
            text=f"{fmt_delta(data['warmest_month_trend_50y'], ctx.unit)} over {facts.data_end_year - facts.data_start_year}y",
            font=dict(color="rgba(220,50,47,0.9)", size=11),
            xanchor="left",
            yanchor="bottom",
        )
    
    fig.update_layout(
        height=400,
        margin=dict(l=40, r=20, t=30, b=40),
        xaxis_title="Year",
        yaxis_title="Temperature (%s)" % ctx.unit,
        showlegend=True,
    )

    caption = "Source: OpenMeteo"
    cov = dataset_coverage_text(ctx.ds)
    if cov:
        caption += f" | {cov}"

    return fig, caption

def fifty_year_caption(ctx: StoryContext, facts: StoryFacts, data: dict) -> str:
    """
    Generate the markdown caption for the last-fifty-year panel
    using StoryFacts (so it's easy to reuse elsewhere).
    """
    total_span_years = data["total_span_years"]
    total_warming = data["total_warming"]
    if total_span_years is not None and total_span_years > 0:
        extra = ""
        if abs(total_warming) < 0.15:
            # ~flat
            total_warming_sign = "+" if total_warming>0 else "-"
            change_text = (
                f"has changed very little **({fmt_delta(total_warming, ctx.unit)})** — the long-term average is almost the same "
                f"now as it was at the start of the record."
            )
        elif total_warming > 0:
            # warmer
            change_text = (
                f"is now roughly **{fmt_delta(total_warming, ctx.unit)} warmer on average** than it was "
                f"at the start of the record."
            )
        else:
            # cooler
            change_text = (
                f"is now roughly **{fmt_delta(abs(total_warming), ctx.unit)} cooler on average** than it was "
                f"at the start of the record — a smaller change than in many places."
            )

        extra = ""
        if data["coldest_month_trend_50y"] is not None and data["warmest_month_trend_50y"] is not None:
            cold = data["coldest_month_trend_50y"]
            warm = data["warmest_month_trend_50y"]

            extra += " The dashed lines show how the **coldest** and **warmest** typical months behave:"

            def describe(label: str, val: float) -> str:
                if val > 0.3:
                    return f" the {label} month is about **{fmt_delta(val, ctx.unit)} warmer**."
                if val < -0.3:
                    return f" the {label} month is about **{fmt_delta(abs(val), ctx.unit, sign=False)} cooler**."
                return f" the {label} month has changed by only about **{fmt_delta(val, ctx.unit)}**."

            extra += describe("coldest", cold)
            extra += describe("warmest", warm)

        caption = f"""
    When you zoom out over about **{total_span_years} years**, the year-to-year noise
    fades and a clear pattern emerges. In **{ctx.city_name}**, the climate {change_text}
            """ + " " + extra
    else:
        caption = f"""
    When you zoom out over about **{total_span_years} years**, the year-to-year noise
    fades and a clearer pattern would normally emerge — but here the data window is too short
    to say much yet for **{ctx.city_name}**.
        """
    
    return caption

# -----------------------------------------------------------
# Compute XXX data, graph and captions
# -----------------------------------------------------------

def build_twenty_five_years_data(ctx: StoryContext) -> dict:
    """
    Prepare the data needed for the '25 years ahead' panel.

    Uses:
      - time_yearly
      - t2m_yearly_mean_c
    Returns a dict so it's easy to plug into other front-ends later.
    """
    da_year = ctx.ds["t2m_yearly_mean_c"]
    time_yearly = pd.to_datetime(ctx.ds["time_yearly"].values)

    years = time_yearly.year.astype(float)
    temps = np.asarray(da_year.values, dtype="float64")

    mask = np.isfinite(temps)
    if mask.sum() < 5:
        return None

    df_year = pd.DataFrame({"year": years, "temp": temps}).set_index("year")
    smooth5 = (
        df_year["temp"].rolling(window=5, center=True, min_periods=3).mean().values
    )

    # Linear trend on yearly means
    x = years[mask]
    y = temps[mask]
    slope, intercept = np.polyfit(x, y, 1)

    first_year = float(x.min())
    last_year = float(x.max())
    horizon = 25.0

    # Build a continuous year axis from first year through future
    full_years = np.linspace(first_year, last_year + horizon, 300)
    trend_vals_full = intercept + slope * full_years

    # Map fractional years to datetimes
    ref_start = pd.Timestamp(f"{int(first_year)}-01-01")
    full_dates = ref_start + pd.to_timedelta((full_years - first_year) * 365.25, unit="D")

    # Split into historical vs future segments
    past_mask = full_years <= (last_year + 1e-6)
    future_mask = full_years > (last_year + 1e-6)

    # #################################################################
    # Story numbers
    years = ctx.ds["time_yearly"].dt.year.values.astype(int)
    year_mean = ctx.ds["t2m_yearly_mean_c"].values.astype(float)

    x1 = years
    y1 = year_mean

    # simple linear regression
    slope1, intercept1 = np.polyfit(x1, y1, 1)
    trend_all = intercept1 + slope1 * x1

    last_year = int(x1[-1])
    target_year = last_year + 25
    x_future = np.arange(last_year, target_year + 1)
    trend_future = intercept1 + slope1 * x_future

    current_level = float(trend_all[-1])
    future_level = float(trend_future[-1])
    # #################################################################

    return {
        "time_yearly" : time_yearly,
        "temp_yearly" : temps,
        "temp_5_yearly": smooth5,
        "time_past_trend" : full_dates[past_mask],
        "temp_past_trend" : trend_vals_full[past_mask],
        "time_future_trend" : full_dates[future_mask],
        "temp_future_trend" : trend_vals_full[future_mask],
        "last_year" : float(x.max()),
        "current_level": current_level,
        "future_level": future_level,
        "last_year": last_year,
        "target_year": target_year,
    }

def build_twenty_five_years_figure(ctx: StoryContext, facts: StoryFacts, data: dict) -> (go.Figure, str):
    """
    Build the Plotly figure for the 25 years ahead trend.

    Styling is consistent with other panels:
      - grey noisy curve (daily)
      - blue smooth curve (7-day mean)
      - min/max annotations via annotate_minmax_on_series()
    """
    # Base: yearly mean
    fig = go.Figure()

    temp_yearly_local = np.asarray([convert_temp(v, ctx.unit) for v in data["temp_yearly"]], dtype="float64")
    add_trace(
        fig,
        x=data["time_yearly"],
        y=temp_yearly_local,
        name="Yearly mean",
        hovertemplate="Year %{x|%Y}<br>%{y:.1f}" + ctx.unit + "<extra></extra>",
    )

    temp_5_yearly_local = np.asarray([convert_temp(v, ctx.unit) for v in data["temp_5_yearly"]], dtype="float64")
    add_mean_trace(
        fig,
        x=data["time_yearly"],
        y=temp_5_yearly_local,
        name="5-year mean",
        showmarkers=False,
        hovertemplate="Year %{x|%Y}<br>%{y:.1f}" + ctx.unit + "<extra></extra>",
    )
        
    # Plot past trend (solid red)
    temp_past_trend_local = np.asarray([convert_temp(v, ctx.unit) for v in data["temp_past_trend"]], dtype="float64")
    fig.add_trace(
        go.Scatter(
            x=data["time_past_trend"],
            y=temp_past_trend_local,
            mode="lines",
            name="Trend (yearly mean)",
            line=dict(color="rgba(220,50,47,0.9)", width=3, shape="linear"),
            hovertemplate="Trend %{x|%Y}<br>%{y:.1f}" + ctx.unit + "<extra></extra>",
        )
    )

    # Plot future extension (dashed red)
    temp_future_trend_local = np.asarray([convert_temp(v, ctx.unit) for v in data["temp_future_trend"]], dtype="float64")
    fig.add_trace(
        go.Scatter(
            x=data["time_future_trend"],
            y=temp_future_trend_local,
            mode="lines",
            name="Straight-line extension",
            line=dict(
                color="rgba(220,50,47,0.9)", width=3, dash="dash", shape="linear"
            ),
            hovertemplate="Extension %{x|%Y}<br>%{y:.1f}" + ctx.unit + "<extra></extra>",
        )
    )

    # Shade future region based on last_year
    horizon = 25.0
    last_year = data["last_year"]
    last_year_int = int(round(last_year))
    future_end_year_int = int(round(last_year + horizon))
    fig.add_vrect(
        x0=pd.Timestamp(f"{last_year_int+1}-01-01"),
        x1=pd.Timestamp(f"{future_end_year_int}-12-31"),
        fillcolor="rgba(220,50,47,0.06)",
        line_width=0,
        layer="below",
    )

    # --- Choose a sane y-axis range so year-to-year bumps aren't exaggerated ---
    y_all = np.concatenate([np.asarray(temp_yearly_local, dtype="float64"),
                            np.asarray(temp_past_trend_local, dtype="float64"),
                            np.asarray(temp_future_trend_local, dtype="float64")])

    y_min = float(np.nanmin(y_all))
    y_max = float(np.nanmax(y_all))

    # Enforce at least ~2°C span
    span = max(y_max - y_min, convert_delta(2.0, ctx.unit))
    pad = span * 0.1  # 10% padding top/bottom

    y_center = 0.5 * (y_min + y_max)
    y0 = y_center - span / 2.0 - pad
    y1 = y_center + span / 2.0 + pad

    fig.update_layout(
        margin=dict(l=0, r=0, t=10, b=40),
        height=320,
        showlegend=True,
        xaxis=dict(
            title="Year",
            showgrid=True,
            gridcolor="rgba(200,200,200,0.3)",
        ),
        yaxis=dict(
            title=f"Temperature (%s)" % ctx.unit,
            showgrid=True,
            gridcolor="rgba(200,200,200,0.3)",
            range=[y0, y1],
        ),
    )

    caption = ""
    return fig, caption

def twenty_five_years_caption(ctx: StoryContext, facts: StoryFacts, data: dict) -> str:
    curr = data["current_level"]
    fut = data["future_level"]
    last_year = data["last_year"]
    target_year = data["target_year"]

    delta = fut - curr

    base = (
        f"This panel takes the long-term trend from the last few decades and extends it "
        f"forward by 25 years."
    )

    if abs(delta) < 0.2:
        change_txt = (
            f" If that trend held steady, the yearly mean temperature would still hover "
            f"around **{fmt_temp(curr, ctx.unit)}** in {target_year}, not very different from today "
            f"({last_year})."
        )
    else:
        direction = "warmer" if delta > 0 else "cooler"
        change_txt = (
            f" In the historical data, the yearly mean oscillates around "
            f"**{fmt_temp(curr, ctx.unit)}** in {last_year}. If the same linear trend continues, it would "
            f"oscillate around **{fmt_temp(fut, ctx.unit)}** by {target_year} – about "
            f"**{fmt_delta(abs(delta), ctx.unit, sign=False)} {direction}**."
        )

    segue = (
        " Of course, people experience this not as a single number but as changing "
        "seasons and extremes. In the next section we zoom back in to see how those "
        "shifts show up month by month."
    )

    return base + change_txt + segue
