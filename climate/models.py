from dataclasses import dataclass
from typing import Optional
import xarray as xr
from datetime import date

@dataclass
class StoryFacts:
    data_start_year: int
    data_end_year: int
    total_warming_50y: Optional[float]
    recent_warming_10y: Optional[float]
    last_year_anomaly: Optional[float]
    hemisphere: str
    # coldest_month_trend_50y: float | None = None
    # warmest_month_trend_50y: float | None = None

@dataclass
class StoryContext:
    today: date
    slug: str
    location_label: str
    location_lat: float
    location_lon: float
    unit: str
    ds: xr.Dataset
