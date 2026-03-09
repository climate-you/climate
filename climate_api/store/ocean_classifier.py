from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import math

import numpy as np


@dataclass(frozen=True)
class OceanHit:
    in_water: bool
    ocean_id: int
    ocean_name: str | None


class OceanClassifier:
    """
    Fast ocean lookup from a precomputed regular-grid mask.

    NPZ requirements:
      - data: 2D integer array, shape (nlat, nlon), 0=land, >0 ocean id
      - deg: float cell size in degrees
      - lat_max: float (typically 90.0)
      - lon_min: float (typically -180.0)
    """

    def __init__(self, mask_npz: Path, names_json: Path | None = None) -> None:
        mask_npz = Path(mask_npz)
        if not mask_npz.exists():
            raise FileNotFoundError(f"Ocean mask NPZ not found: {mask_npz}")

        with np.load(mask_npz, allow_pickle=False) as npz:
            if "data" not in npz:
                raise ValueError(f"Ocean mask missing 'data' array: {mask_npz}")
            self._data = np.asarray(npz["data"])
            self._deg = float(npz["deg"])
            self._lat_max = float(npz["lat_max"])
            self._lon_min = float(npz["lon_min"])

        if self._data.ndim != 2:
            raise ValueError("Ocean mask 'data' must be a 2D array.")
        if self._deg <= 0:
            raise ValueError("Ocean mask 'deg' must be > 0.")

        self._nlat, self._nlon = self._data.shape
        self._names: dict[int, str] = {}
        if names_json is not None:
            names_path = Path(names_json)
            if names_path.exists():
                raw = json.loads(names_path.read_text(encoding="utf-8"))
                for k, v in raw.items():
                    try:
                        self._names[int(k)] = str(v)
                    except (ValueError, TypeError):
                        continue

    def classify(self, lat: float, lon: float) -> OceanHit:
        lat_f = float(lat)
        lon_f = float(lon)

        lon_norm = ((lon_f + 180.0) % 360.0) - 180.0
        lat_clamped = max(-self._lat_max + 1e-12, min(self._lat_max - 1e-12, lat_f))

        i_lon = int(math.floor((lon_norm - self._lon_min) / self._deg))
        i_lat = int(math.floor((self._lat_max - lat_clamped) / self._deg))

        i_lon = max(0, min(self._nlon - 1, i_lon))
        i_lat = max(0, min(self._nlat - 1, i_lat))

        ocean_id = int(self._data[i_lat, i_lon])
        if ocean_id <= 0:
            return OceanHit(in_water=False, ocean_id=0, ocean_name=None)

        return OceanHit(
            in_water=True,
            ocean_id=ocean_id,
            ocean_name=self._names.get(ocean_id),
        )
