from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple
import json

import numpy as np
import pandas as pd
import plotly.graph_objs as go
from plotly.subplots import make_subplots

from climate.models import StoryContext, StoryFacts
from climate.units import is_fahrenheit, fmt_unit

BASELINE_START = 1979
BASELINE_END = 1990

WORLD_DATA_DIR = Path("data/world")


def _load_global_series_meta() -> dict:
    p = WORLD_DATA_DIR / "global_series.meta.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def build_you_vs_world_data(ctx: StoryContext) -> dict:
    # Local: monthly mean temperature from precomputed city dataset
    t = pd.to_datetime(ctx.ds["time_monthly"].values)
    y = ctx.ds["t2m_monthly_mean_c"].values.astype("float64")
    local_monthly = pd.Series(y, index=t).sort_index()

    # Local anomalies: month-of-year baseline climatology (removes seasonal cycle)
    local_anom = _anom_from_baseline_monthly_clim(
        local_monthly, BASELINE_START, BASELINE_END
    )

    # Global: load anomaly series produced by scripts/make_global_series.py
    global_series = WORLD_DATA_DIR / "global_series.csv"
    global_raw = _load_global_series(global_series)
    global_anom = _rebase_anomaly_series(global_raw, BASELINE_START, BASELINE_END)

    # Align time range so plots cover same span
    t0 = max(local_anom.index.min(), global_anom.index.min())
    t1 = min(local_anom.index.max(), global_anom.index.max())
    local_anom = local_anom[(local_anom.index >= t0) & (local_anom.index <= t1)]
    global_anom = global_anom[(global_anom.index >= t0) & (global_anom.index <= t1)]

    # Unit conversion for display only
    if is_fahrenheit(ctx.unit):
        local_anom = local_anom * 9.0 / 5.0
        global_anom = global_anom * 9.0 / 5.0

    return dict(
        baseline=(BASELINE_START, BASELINE_END),
        local_anom=local_anom,
        global_anom=global_anom,
    )


def _anomaly_bars(
    ctx: StoryContext, series: pd.Series, *, title: str, yaxis_title: str
) -> go.Figure:
    # Force datetime index -> python datetimes
    x = pd.to_datetime(series.index, errors="coerce")
    mask = x.notna()
    x = x[mask].to_pydatetime()
    y = np.asarray(series.values, dtype="float64")[mask]

    date_str = pd.Series(pd.to_datetime(x)).dt.strftime("%Y %B").to_numpy()
    val_str = pd.Series(y).map(lambda v: f"{v:+.2f}{fmt_unit(ctx.unit)}").to_numpy()
    customdata = np.column_stack([date_str, val_str])

    fig = go.Figure()

    # Visual bars (no hover)
    fig.add_trace(
        go.Bar(
            x=x,
            y=y,
            marker=dict(
                color=np.where(y >= 0, "rgba(180, 0, 120, 0.8)", "rgba(0, 130, 0, 0.8)")
            ),
            hoverinfo="skip",
            showlegend=False,
        )
    )

    # Invisible markers purely to make hover easy at full zoom
    fig.add_trace(
        go.Scatter(
            x=x,
            y=y,
            mode="markers",
            marker=dict(size=12, opacity=0.0),
            customdata=customdata,
            hovertemplate="%{customdata[0]} %{customdata[1]}<extra></extra>",
            showlegend=False,
        )
    )

    fig.update_layout(
        hovermode="closest",
        hoverdistance=50,  # px radius for finding points
    )

    fig.update_xaxes(title_text="Year", tickformat="%Y", type="date")  # <-- key line
    fig.update_layout(
        title=dict(text=title, x=0, xanchor="left"),
        height=260,
        margin=dict(l=40, r=20, t=48, b=40),
    )
    fig.update_yaxes(title_text=yaxis_title)
    fig.update_xaxes(title_text="Year", tickformat="%Y")
    return fig


def build_you_vs_world_figures(ctx, facts, data) -> (go.Figure, go.Figure, str):
    y0, y1 = data["baseline"]
    unit = ctx.unit

    fig_local = _anomaly_bars(
        ctx,
        data["local_anom"],
        title=f"<b>{ctx.location_label} — monthly anomalies</b>",
        yaxis_title=f"Anomaly vs {y0}–{y1} ({fmt_unit(unit)})",
    )
    fig_global = _anomaly_bars(
        ctx,
        data["global_anom"],
        title="<b>Global average — monthly anomalies</b>",
        yaxis_title=f"Anomaly vs {y0}–{y1} ({fmt_unit(unit)})",
    )

    meta = _load_global_series_meta()
    src = meta.get("source_name") or "global temperature anomaly series"
    tiny = (
        f"Local: ERA5 (Open-Meteo) monthly means. Global: {src}. Baseline: {y0}–{y1}."
    )
    return fig_local, fig_global, tiny


def _trend_per_decade(s: pd.Series) -> float:
    """Linear trend in units/decade."""
    s = s.dropna()
    if len(s) < 24:
        return float("nan")
    # convert datetime to fractional year
    x = s.index.year + (s.index.dayofyear - 1) / 365.25
    y = s.values.astype("float64")
    slope_per_year = np.polyfit(x, y, 1)[0]
    return float(slope_per_year * 10.0)


def _fmt(v: float, unit: str) -> str:
    if not np.isfinite(v):
        return "n/a"
    return f"{v:+.2f}{fmt_unit(unit)}"


def you_vs_world_caption(ctx, facts, data) -> str:
    local: pd.Series = data["local_anom"].dropna()
    global_: pd.Series = data["global_anom"].dropna()
    (y0, y1) = data["baseline"]
    unit = ctx.unit

    # Align on common monthly timestamps
    df = pd.concat([local.rename("local"), global_.rename("global")], axis=1).dropna()
    if df.empty:
        return (
            "We couldn’t compute a local-vs-global comparison for this location yet "
            "(missing overlapping data)."
        )

    # Use a “recent climate” window: last 30 years if possible, else whatever we have
    end = df.index.max()
    start = max(df.index.min(), end - pd.DateOffset(years=30))
    dfr = df[df.index >= start]
    if len(dfr) < 60:  # if too short, fall back to full overlap
        dfr = df

    corr = float(dfr["local"].corr(dfr["global"]))
    tr_local = _trend_per_decade(dfr["local"])
    tr_global = _trend_per_decade(dfr["global"])

    # Simple classification
    tracks = corr >= 0.70
    diverges = corr <= 0.35

    # Compare trends (avoid division; use absolute thresholds)
    # “Similar rate” means within ~0.05 units/decade (tweakable)
    rate_delta = tr_local - tr_global
    same_direction = (
        np.isfinite(tr_local)
        and np.isfinite(tr_global)
        and (
            np.sign(tr_local) == np.sign(tr_global)
            or abs(tr_local) < 1e-6
            or abs(tr_global) < 1e-6
        )
    )

    if diverges:
        headline = "Your local swings don’t line up closely with the global pattern."
    elif tracks:
        headline = "Your local pattern tracks the global ups-and-downs closely."
    else:
        headline = "Your local pattern partly tracks the global pattern, but with noticeable differences."

    if np.isfinite(tr_local) and np.isfinite(tr_global):
        if (not same_direction) and (abs(tr_local) > 0.05) and (abs(tr_global) > 0.05):
            trend_line = (
                f"Recent trend differs in direction: local **{_fmt(tr_local, unit)}/decade** "
                f"vs global **{_fmt(tr_global, unit)}/decade**."
            )
        else:
            if abs(rate_delta) <= 0.05:
                trend_line = (
                    f"Recent warming rate is similar: local **{_fmt(tr_local, unit)}/decade** "
                    f"vs global **{_fmt(tr_global, unit)}/decade**."
                )
            elif rate_delta > 0:
                trend_line = (
                    f"Local warming is faster: local **{_fmt(tr_local, unit)}/decade** "
                    f"vs global **{_fmt(tr_global, unit)}/decade**."
                )
            else:
                trend_line = (
                    f"Local warming is slower: local **{_fmt(tr_local, unit)}/decade** "
                    f"vs global **{_fmt(tr_global, unit)}/decade**."
                )
    else:
        trend_line = "Not enough overlapping data to estimate a stable recent trend."

    # Correlation line (keep it simple and human-readable)
    corr_line = f"How closely they track (correlation over the comparison window): **{corr:.2f}**."

    meta = _load_global_series_meta()
    src = meta.get("source_name") or "a global temperature anomaly series"

    return (
        f"{headline}\n\n"
        f"- {trend_line}\n"
        f"- {corr_line}\n\n"
        f"Both charts are anomalies relative to **{y0}–{y1}** (local from the city ERA5 series; "
        f"global from {src})."
    )


# ---------- helpers ----------


def _anom_from_baseline_monthly_clim(s: pd.Series, y0: int, y1: int) -> pd.Series:
    base = s[(s.index.year >= y0) & (s.index.year <= y1)]
    if base.empty:
        raise RuntimeError(f"No baseline data available for {y0}–{y1}")
    clim = base.groupby(base.index.month).mean()  # 1..12
    return s - s.index.month.map(clim).to_numpy()


def _rebase_anomaly_series(s: pd.Series, y0: int, y1: int) -> pd.Series:
    base = s[(s.index.year >= y0) & (s.index.year <= y1)]
    if base.empty:
        raise RuntimeError(f"No baseline data available for {y0}–{y1}")
    return s - float(base.mean())


def _load_global_series(path_csv: Path) -> pd.Series:
    df = pd.read_csv(path_csv)
    if "date" not in df.columns:
        raise RuntimeError(
            f"global_series.csv missing 'date' column. cols={list(df.columns)}"
        )
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df[df["date"].notna()].sort_values("date")

    # choose anomaly column robustly
    candidates = [
        c
        for c in df.columns
        if c.lower() in ("anomaly_c", "anom_c", "ano_91-20", "ano_pi", "anomaly")
    ]
    if not candidates:
        # fallback: first numeric column that isn't year/month
        candidates = [
            c
            for c in df.columns
            if c not in ("date", "year", "month", "month_num")
            and pd.api.types.is_numeric_dtype(df[c])
        ]
    if not candidates:
        raise RuntimeError(
            f"Couldn't find anomaly column in global_series.csv. cols={list(df.columns)}"
        )

    return pd.Series(df[candidates[0]].astype("float64").values, index=df["date"])
