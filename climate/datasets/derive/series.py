import numpy as np


def c_to_f(x: np.ndarray) -> np.ndarray:
    return x * (9.0 / 5.0) + 32.0


def rolling_mean_centered(y: np.ndarray, window: int) -> np.ndarray:
    """
    Centered rolling mean with NaN-aware behavior.
    Returns array same length, with NaN at edges where window doesn't fit
    or where all values in window are NaN.
    """
    n = int(y.size)
    w = int(window)
    out = np.full(n, np.nan, dtype=np.float32)
    if w <= 1 or n == 0:
        return y.astype(np.float32, copy=False)

    half = w // 2
    for i in range(n):
        lo = i - half
        hi = i + half + 1
        if lo < 0 or hi > n:
            continue
        seg = y[lo:hi]
        if np.all(np.isnan(seg)):
            continue
        out[i] = float(np.nanmean(seg))
    return out


def linear_trend_line(x_years: np.ndarray, y: np.ndarray) -> np.ndarray:
    """
    Fit y ~ a*x + b using valid (non-NaN) y points.
    Returns y_hat for all x_years (NaNs if not enough points).
    """
    x = x_years.astype(np.float64)
    yy = y.astype(np.float64)

    mask = np.isfinite(yy)
    if int(mask.sum()) < 2:
        return np.full_like(y, np.nan, dtype=np.float32)

    a, b = np.polyfit(x[mask], yy[mask], deg=1)
    yhat = a * x + b
    return yhat.astype(np.float32)
