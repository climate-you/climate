from __future__ import annotations
from pydantic import BaseModel
from typing import Any, Dict, List, Optional


class SeriesPayload(BaseModel):
    x: List[Any]
    y: List[float | None]
    unit: Optional[str] = None
    style: Optional[Dict[str, Any]] = None


class GraphAnnotation(BaseModel):
    series_key: str
    text: str


class GraphPayload(BaseModel):
    id: str
    title: str
    series_keys: List[str]
    annotations: List[GraphAnnotation] = []
    caption: Optional[str] = None
    error: Optional[str] = None
    x_axis_label: Optional[str] = None
    y_axis_label: Optional[str] = None


class PanelPayload(BaseModel):
    id: str
    title: str
    graphs: List[GraphPayload]
    text_md: Optional[str] = None


class LocationInfo(BaseModel):
    query: QueryPoint
    place: PlaceInfo
    data_cells: list[DataCell]


class PanelResponse(BaseModel):
    release: str
    unit: str
    location: LocationInfo
    panel: PanelPayload
    series: Dict[str, SeriesPayload]


class GraphListResponse(BaseModel):
    release: str
    unit: str
    location: LocationInfo
    panel_id: str
    graph_ids: List[str]


class QueryPoint(BaseModel):
    lat: float
    lon: float


class PlaceInfo(BaseModel):
    slug: str
    label: str | None = None
    lat: float
    lon: float
    distance_km: float


class DataCell(BaseModel):
    grid: str  # e.g. "era5_025", "oisst_025", "crw_005"

    # Cell index in the grid
    i_lat: int
    i_lon: int

    # Cell geometry
    deg: float
    lat_center: float
    lon_center: float
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float

    # Optional: tile debug (useful for troubleshooting / cache keys)
    tile_r: Optional[int] = None
    tile_c: Optional[int] = None
    o_lat: Optional[int] = None
    o_lon: Optional[int] = None
