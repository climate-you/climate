# -----------------------------------------------------------
# 1. Fake data generator (we'll later replace with real data)
# -----------------------------------------------------------

def make_fake_daily_series(
    years: int = 50,
    baseline: float = 23.0,
    trend_per_decade: float = 0.3,
    noise: float = 1.0,
) -> pd.Series:
    """
    Return a DAILY time series over `years` with:
    - a simple seasonal cycle
    - a linear warming trend
    """
    days = years * 365
    start_date = datetime(1975, 1, 1)
    time = pd.date_range(start_date, periods=days, freq="D")
    t = np.arange(days)

    # Seasonal cycle
    seasonal = 5.0 * np.sin(2 * np.pi * t / 365.0 - 0.5)

    # Linear warming trend (°C per decade)
    trend = trend_per_decade / 10.0 * (t / 365.0)

    data = baseline + seasonal + trend + np.random.normal(0.0, noise, size=days)
    return pd.Series(data, index=time, name="temp")

def make_fake_hourly_from_daily(daily: pd.Series) -> pd.Series:
    """
    Build a HOURLY series from a daily mean series, adding a diurnal cycle.

    This is just for demo purposes. For real data we would query hourly ERA5
    directly and derive daily means/min/max.
    """
    # Hourly index spanning the same date range
    start = daily.index[0]
    end = daily.index[-1] + pd.Timedelta(days=1) - pd.Timedelta(hours=1)
    hourly_index = pd.date_range(start, end, freq="h")

    # Interpolate daily mean onto hourly grid
    x_daily = daily.index.view("int64")
    x_hourly = hourly_index.view("int64")
    base = np.interp(x_hourly, x_daily, daily.values)

    # Add a simple diurnal cycle (max mid-afternoon, min pre-dawn)
    hours = np.arange(len(hourly_index))
    hour_of_day = hours % 24
    diurnal = 4.0 * np.sin(2 * np.pi * (hour_of_day - 15) / 24.0)  # peak ~15:00

    # Small extra noise
    noise = np.random.normal(0.0, 0.5, size=len(hourly_index))

    data = base + diurnal + noise
    return pd.Series(data, index=hourly_index, name="temp_hourly")

def fake_local_and_global(location: str = "mauritius"):
    """
    Provide fake 'local' and 'global' daily series,
    plus precomputed annual & monthly means and anomalies.
    """
    if location == "mauritius":
        baseline = 24.0
        trend = 0.35  # °C / decade
    else:  # london
        baseline = 11.0
        trend = 0.25

    # Local daily series
    local_daily = make_fake_daily_series(baseline=baseline, trend_per_decade=trend)

    # A fake global series with smaller warming
    global_daily = make_fake_daily_series(
        baseline=14.0, trend_per_decade=0.2, noise=0.7
    )

    # Local hourly series for recent weeks/months
    local_hourly = make_fake_hourly_from_daily(local_daily)

    # Aggregate to monthly and yearly means
    local_monthly = local_daily.resample("MS").mean()
    global_monthly = global_daily.resample("MS").mean()

    local_yearly = local_daily.resample("YS").mean()
    global_yearly = global_daily.resample("YS").mean()

    # anomalies vs 1979–1990 mean (roughly a "pre-warming" baseline)
    ref_period = slice("1979-01-01", "1990-12-31")
    local_ref = local_monthly[ref_period].mean()
    global_ref = global_monthly[ref_period].mean()

    local_anom = local_monthly - local_ref
    global_anom = global_monthly - global_ref

    return {
        "local_daily": local_daily,
        "local_hourly": local_hourly,
        "global_daily": global_daily,
        "local_monthly": local_monthly,
        "global_monthly": global_monthly,
        "local_yearly": local_yearly,
        "global_yearly": global_yearly,
        "local_anom": local_anom,
        "global_anom": global_anom,
        "local_ref": float(local_ref),
        "global_ref": float(global_ref),
    }
