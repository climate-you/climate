import pandas as pd

from ..time_agg import annual_group


def compute_annual_metrics(
    dhw_daily: pd.Series,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    dhw_max = annual_group(dhw_daily, how="max").rename("dhw_max_year")
    ge4 = annual_group((dhw_daily >= 4.0).astype("float64"), how="sum").rename(
        "dhw_ge4_days_year"
    )
    ge8 = annual_group((dhw_daily >= 8.0).astype("float64"), how="sum").rename(
        "dhw_ge8_days_year"
    )
    return dhw_max, ge4, ge8
