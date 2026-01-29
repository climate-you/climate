from __future__ import annotations
from dataclasses import dataclass
import numpy as np

@dataclass(frozen=True)
class TrendResult:
    yhat: np.ndarray
    delta: float  # delta over the fitted period (same unit as y)

def linear_trend(y: np.ndarray) -> TrendResult:
    """
    Fit y ~ a + b*t, with t=0..N-1 (no need for actual year spacing if yearly regular).
    Returns yhat and delta over the period (yhat[-1] - yhat[0]).
    """
    y = np.asarray(y, dtype=float)
    n = y.size
    t = np.arange(n, dtype=float)

    mask = np.isfinite(y)
    if mask.sum() < 2:
        return TrendResult(yhat=np.full(n, np.nan), delta=float("nan"))

    t2 = t[mask]
    y2 = y[mask]
    b, a = np.polyfit(t2, y2, 1)  # y = a + b*t
    yhat = a + b * t

    delta = float(yhat[mask][-1] - yhat[mask][0])
    return TrendResult(yhat=yhat, delta=delta)
