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
    time_range: Optional[Dict[str, Any]] = None
    animation: Optional[Dict[str, Any]] = None


class PanelPayload(BaseModel):
    id: str
    title: str
    graphs: List[GraphPayload]
    text_md: Optional[str] = None


class HeadlinePayload(BaseModel):
    key: str
    label: str
    value: float | None = None
    unit: str
    baseline: Optional[str] = None
    period: Optional[str] = None
    method: Optional[str] = None


class LocationInfo(BaseModel):
    query: QueryPoint
    place: PlaceInfo
    data_cells: list[DataCell]
    panel_valid_bbox: Optional["PanelValidBBox"] = None
    panel_cell_indices: Optional[list["PanelCellIndex"]] = None


class PanelResponse(BaseModel):
    release: str
    unit: str
    location: LocationInfo
    panel: PanelPayload
    series: Dict[str, SeriesPayload]
    headlines: List[HeadlinePayload] = []


class ScoredPanelPayload(BaseModel):
    score: int
    panel: PanelPayload


class PanelListResponse(BaseModel):
    release: str
    unit: str
    location: LocationInfo
    panels: List[ScoredPanelPayload]
    series: Dict[str, SeriesPayload]
    headlines: List[HeadlinePayload] = []


class GraphListResponse(BaseModel):
    release: str
    unit: str
    location: LocationInfo
    panel_id: str
    graph_ids: List[str]


class LayerDescriptor(BaseModel):
    id: str
    label: str
    map_id: str
    asset_path: str
    description: Optional[str] = None
    icon: Optional[str] = None
    opacity: Optional[float] = None
    legend: Optional[Dict[str, Any]] = None


class ReleaseResolveResponse(BaseModel):
    requested_release: str
    release: str
    layers: List[LayerDescriptor] = []


class QueryPoint(BaseModel):
    lat: float
    lon: float


class PlaceInfo(BaseModel):
    geonameid: int
    label: str | None = None
    lat: float
    lon: float
    distance_km: float
    country_code: str | None = None
    population: int | None = None


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


class PanelValidBBox(BaseModel):
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float


class PanelCellIndex(BaseModel):
    grid: str
    i_lat: int
    i_lon: int


class LocationAutocompleteItem(BaseModel):
    geonameid: int
    label: str
    lat: float
    lon: float
    country_code: str
    population: int


class LocationAutocompleteResponse(BaseModel):
    query: str
    results: List[LocationAutocompleteItem]


class LocationResolveResponse(BaseModel):
    query: str
    result: Optional[LocationAutocompleteItem] = None


class LocationNearestResponse(BaseModel):
    query: QueryPoint
    result: PlaceInfo
