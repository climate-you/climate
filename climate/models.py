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


@dataclass
class StoryContext:
    today: date
    slug: str
    location_label: str
    city_name: str
    location_lat: float
    location_lon: float
    unit: str
    ds: xr.Dataset
