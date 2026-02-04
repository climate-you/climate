import pandas as pd


def drop_feb29(s: pd.Series) -> pd.Series:
    idx = pd.DatetimeIndex(s.index)
    mask = ~((idx.month == 2) & (idx.day == 29))
    return s.loc[mask]
