from __future__ import annotations

from pathlib import Path
import json
import math

import numpy as np


class CountryClassifier:
    """
    Fast country lookup from a precomputed regular-grid mask.

    NPZ requirements:
      - data: 2D integer array, shape (nlat, nlon), 0=unknown, >0 country id
      - deg: float cell size in degrees
      - lat_max: float (typically 90.0)
      - lon_min: float (typically -180.0)

    Companion JSON maps integer country ids to ISO 3166-1 alpha-2 codes:
      {"1": "FR", "2": "BE", ...}
    """

    def __init__(self, mask_npz: Path, codes_json: Path | None = None) -> None:
        mask_npz = Path(mask_npz)
        if not mask_npz.exists():
            raise FileNotFoundError(f"Country mask NPZ not found: {mask_npz}")

        with np.load(mask_npz, allow_pickle=False) as npz:
            if "data" not in npz:
                raise ValueError(f"Country mask missing 'data' array: {mask_npz}")
            self._data = np.asarray(npz["data"])
            self._deg = float(npz["deg"])
            self._lat_max = float(npz["lat_max"])
            self._lon_min = float(npz["lon_min"])

        if self._data.ndim != 2:
            raise ValueError("Country mask 'data' must be a 2D array.")
        if self._deg <= 0:
            raise ValueError("Country mask 'deg' must be > 0.")

        self._nlat, self._nlon = self._data.shape
        self._codes: dict[int, str] = {}
        if codes_json is not None:
            codes_path = Path(codes_json)
            if codes_path.exists():
                raw = json.loads(codes_path.read_text(encoding="utf-8"))
                for k, v in raw.items():
                    try:
                        self._codes[int(k)] = str(v)
                    except (ValueError, TypeError):
                        continue

    def classify(self, lat: float, lon: float) -> str | None:
        """Return ISO 3166-1 alpha-2 country code, or None if ocean/unknown."""
        lat_f = float(lat)
        lon_f = float(lon)

        lon_norm = ((lon_f + 180.0) % 360.0) - 180.0
        lat_clamped = max(-self._lat_max + 1e-12, min(self._lat_max - 1e-12, lat_f))

        i_lon = int(math.floor((lon_norm - self._lon_min) / self._deg))
        i_lat = int(math.floor((self._lat_max - lat_clamped) / self._deg))

        i_lon = max(0, min(self._nlon - 1, i_lon))
        i_lat = max(0, min(self._nlat - 1, i_lat))

        country_id = int(self._data[i_lat, i_lon])
        if country_id <= 0:
            return None

        return self._codes.get(country_id)
