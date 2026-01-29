from __future__ import annotations
from typing import Protocol, Tuple
import xarray as xr


class Store(Protocol):
    """Storage adapter interface. Implemented by NcPointsStore now, and later TileStore."""

    def resolve_place(self, lat: float, lon: float) -> tuple[str, float]:
        """Return (place_slug, distance_km). (Place is nearest city/admin point.)"""
        raise NotImplementedError

    def location_meta(self, slug: str) -> dict:
        raise NotImplementedError

    def load_location_dataset(self, slug: str) -> xr.Dataset:
        """Return merged dataset for that slug (climatology + ocean if present)."""
        raise NotImplementedError
