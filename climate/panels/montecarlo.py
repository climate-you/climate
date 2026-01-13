from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple, Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from climate.models import StoryContext, StoryFacts
from climate.units import is_fahrenheit, convert_temp, fmt_unit


def _c_to_f(x: np.ndarray) -> np.ndarray:
    return x * 9.0 / 5.0 + 32.0


def _compute_running_means(df_firstn: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Returns (x, mean_past, mean_recent) with x=1..n.
    mean arrays have NaN where that era has no samples yet.
    """
    era_id = df_firstn["era_id"].to_numpy(np.int8)
    t = df_firstn["t_val"].to_numpy(np.float64)

    n = len(df_firstn)
    x = np.arange(1, n + 1, dtype=np.int32)

    # cumulative sums / counts per era at each step
    is_past = (era_id == 0).astype(np.int32)
    is_recent = (era_id == 1).astype(np.int32)

    c_past = np.cumsum(is_past)
    c_recent = np.cumsum(is_recent)

    s_past = np.cumsum(t * (era_id == 0))
    s_recent = np.cumsum(t * (era_id == 1))

    mean_past = np.where(c_past > 0, s_past / c_past, np.nan)
    mean_recent = np.where(c_recent > 0, s_recent / c_recent, np.nan)

    return x, mean_past, mean_recent


# ---------------------------------------------------------------------
# Exported API (3 functions)
# ---------------------------------------------------------------------

def build_montecarlo_data(
    ctx: StoryContext,
    *,
    experiment_id: int = 1,
    data_dir: Path,
) -> Dict:
    """
    Loads a precomputed experiment parquet.

    Returns dict with:
      - df: canonical samples (contains t_c, etc.)
      - meta: meta json dict if present
      - n_total: total rows
      - experiment_id
    """
    p = data_dir / "mc" / f"experiment_{experiment_id:02d}_samples.parquet"
    meta_p = data_dir / "mc" / f"experiment_{experiment_id:02d}_samples.meta.json"

    if not p.exists():
        raise FileNotFoundError(
            f"Missing Monte Carlo samples: {p}. "
            f"Run scripts/make_montecarlo_experiment.py first."
        )

    df = pd.read_parquet(p)

    meta = None
    if meta_p.exists():
        import json
        meta = json.loads(meta_p.read_text(encoding="utf-8"))

    return {
        "experiment_id": experiment_id,
        "df": df,
        "meta": meta,
        "n_total": int(len(df)),
    }


def build_montecarlo_figures(
    ctx: StoryContext,
    facts: StoryFacts,
    data: Dict,
) -> Tuple[go.Figure, go.Figure, go.Figure, str]:
    """
    Expects data to additionally include:
      - n: how many samples to reveal (0..n_total)
      - seed_label (optional): shown in tiny caption
    """
    df = data["df"]
    n_total = int(data["n_total"])
    n = int(data.get("n", 0))
    n = max(0, min(n, n_total))

    unit = fmt_unit(ctx.unit)
    use_f = is_fahrenheit(ctx.unit)

    df_first = df[df["seq"] < n].copy()

    # t_val = display unit
    t_c = df_first["t_c"].to_numpy(np.float64) if len(df_first) else np.array([], dtype=np.float64)
    if use_f:
        df_first["t_val"] = _c_to_f(t_c)
    else:
        df_first["t_val"] = t_c

    # ----------------
    # 1) World map dots
    # ----------------
    fig_map = go.Figure()

    for era_name, era_id, color in (("past", 0, "rgba(70, 110, 200, 0.75)"), ("recent", 1, "rgba(220, 80, 80, 0.75)")):
        dfe = df_first[df_first["era_id"] == era_id]
        if len(dfe) == 0:
            continue

        # preformat hover
        date_str = pd.to_datetime(dfe["time"]).dt.strftime("%Y-%m-%d").to_numpy()
        lat = dfe["lat"].to_numpy()
        lon = dfe["lon"].to_numpy()
        tvals = dfe["t_val"].to_numpy()
        t_str = np.array([f"{v:.2f}{unit}" for v in tvals], dtype=object)

        custom = np.column_stack([date_str, t_str])

        fig_map.add_trace(
            go.Scattergeo(
                lon=lon,
                lat=lat,
                mode="markers",
                name=("Past era" if era_id == 0 else "Recent era"),
                marker=dict(size=4, color=color),
                customdata=custom,
                hovertemplate="%{customdata[0]}<br>Temp: %{customdata[1]}<br>(%{lat:.1f}, %{lon:.1f})<extra></extra>",
            )
        )

    fig_map.update_layout(
        title=dict(text="<b>Random samples across the globe</b>", x=0, xanchor="left"),
        height=300,
        margin=dict(l=10, r=10, t=40, b=10),
        geo=dict(
            projection_type="natural earth",
            showland=True,
            landcolor="rgb(235,235,235)",
            showcountries=False,
            showocean=True,
            oceancolor="rgb(245,245,250)",
            lataxis=dict(showgrid=False),
            lonaxis=dict(showgrid=False),
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )

    # ----------------
    # 2) Timeline scatter
    # ----------------
    fig_time = go.Figure()

    for era_name, era_id, color in (("past", 0, "rgba(70, 110, 200, 0.75)"), ("recent", 1, "rgba(220, 80, 80, 0.75)")):
        dfe = df_first[df_first["era_id"] == era_id]
        if len(dfe) == 0:
            continue

        x = pd.to_datetime(dfe["time"])
        y = dfe["t_val"].to_numpy()

        date_str = x.dt.strftime("%Y-%m-%d").to_numpy()
        t_str = np.array([f"{v:.2f}{unit}" for v in y], dtype=object)
        custom = np.column_stack([date_str, t_str])

        fig_time.add_trace(
            go.Scatter(
                x=x,
                y=y,
                mode="markers",
                name=("Past era" if era_id == 0 else "Recent era"),
                marker=dict(size=5, color=color),
                customdata=custom,
                hovertemplate="%{customdata[0]} %{customdata[1]}<extra></extra>",
            )
        )

    fig_time.update_layout(
        title=dict(text="<b>Random samples across time</b>", x=0, xanchor="left"),
        height=300,
        margin=dict(l=50, r=10, t=40, b=40),
        xaxis_title="Date",
        yaxis_title=f"2m temperature ({unit})",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )

    # ----------------
    # 3) Running means convergence
    # ----------------
    fig_mean = go.Figure()
    if len(df_first) > 0:
        x, mean_past, mean_recent = _compute_running_means(df_first)

        fig_mean.add_trace(go.Scatter(x=x, y=mean_past, mode="lines", name="Past era mean"))
        fig_mean.add_trace(go.Scatter(x=x, y=mean_recent, mode="lines", name="Recent era mean"))

        # current estimate (use last non-nan)
        mp = float(pd.Series(mean_past).dropna().iloc[-1]) if np.isfinite(mean_past).any() else float("nan")
        mr = float(pd.Series(mean_recent).dropna().iloc[-1]) if np.isfinite(mean_recent).any() else float("nan")
        if np.isfinite(mp) and np.isfinite(mr):
            d = mr - mp
            fig_mean.add_annotation(
                x=x[-1],
                y=mr,
                text=f"Δ ≈ {d:+.2f}{unit}",
                showarrow=True,
                arrowhead=2,
                ax=-40,
                ay=-30,
            )

    fig_mean.update_layout(
        title=dict(text="<b>The estimate stabilizes as samples grow</b>", x=0, xanchor="left"),
        height=320,
        margin=dict(l=50, r=10, t=40, b=40),
        xaxis_title="Number of samples revealed",
        yaxis_title=f"Mean 2m temperature ({unit})",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )

    tiny_bits = []
    meta = data.get("meta") or {}
    if meta:
        grid = meta.get("grid_deg")
        if grid is not None:
            tiny_bits.append(f"ERA5 daily mean, grid {grid}°.")
        eras = meta.get("eras")
        if eras and isinstance(eras, list) and len(eras) == 2:
            tiny_bits.append(f"Eras: {eras[0]['start_year']}-{eras[0]['end_year']} vs {eras[1]['start_year']}-{eras[1]['end_year']}.")

    tiny = " ".join(tiny_bits) if tiny_bits else "ERA5 daily mean 2m temperature (precomputed samples)."
    return fig_map, fig_time, fig_mean, tiny


def montecarlo_caption(ctx: StoryContext, facts: StoryFacts, data: Dict) -> str:
    df = data["df"]
    n_total = int(data["n_total"])
    n = int(data.get("n", 0))
    n = max(0, min(n, n_total))

    unit = fmt_unit(ctx.unit)
    use_f = is_fahrenheit(ctx.unit)

    if n <= 0:
        return (
            "We’ll estimate the average warming by sampling random points across the globe and across time. "
            "As we add samples, the average temperature for each era becomes more stable. "
            "We’re estimating the global mean near-surface (2m) air temperature by sampling random points on Earth and random days in each era. "
            "To make it a true global mean, each draw represents an equal patch of Earth’s surface — we sample more often near the equator because grid points there represent larger surface areas, and less often near the poles. "
            "We repeat this for both periods and compare the two running averages; the gap between them is the estimated warming between 1979–1988 and 2016–2025."
        )

    df_first = df[df["seq"] < n].copy()
    t_c = df_first["t_c"].to_numpy(np.float64)
    df_first["t_val"] = _c_to_f(t_c) if use_f else t_c

    # compute current means
    means = df_first.groupby("era_id")["t_val"].mean()
    mp = float(means.get(0, np.nan))
    mr = float(means.get(1, np.nan))

    # counts
    cnts = df_first["era_id"].value_counts()
    cp = int(cnts.get(0, 0))
    cr = int(cnts.get(1, 0))

    if not (np.isfinite(mp) and np.isfinite(mr)):
        return f"Samples so far: {n} (past={cp}, recent={cr})."

    d = mr - mp
    # mild guidance text depending on sample size
    if n < 200:
        stability = "This is still very noisy — expect it to jump around."
    elif n < 2000:
        stability = "The estimate is starting to settle, but it will still wobble."
    else:
        stability = "At this point the estimate changes slowly — you’re seeing convergence."

    return (
        f"Samples: {n} (past={cp}, recent={cr}). "
        f"Current means: past ≈ {mp:.2f}{unit}, recent ≈ {mr:.2f}{unit}, "
        f"difference Δ ≈ {d:+.2f}{unit}. "
        f"{stability}"
    )
