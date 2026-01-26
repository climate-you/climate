import pandas as pd


def annual_group(s: pd.Series, how: str) -> pd.Series:
    y = s.index.year
    if how == "mean":
        return s.groupby(y).mean()
    if how == "sum":
        return s.groupby(y).sum()
    if how == "max":
        return s.groupby(y).max()
    raise ValueError(how)
