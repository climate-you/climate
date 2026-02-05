from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import csv
import unicodedata
import re
from typing import List, Dict, Optional, Iterable


@dataclass(frozen=True)
class LocationHit:
    geonameid: int
    slug: str
    label: str
    lat: float
    lon: float
    country_code: str
    population: int


def _norm(s: str) -> str:
    s = (s or "").strip()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.casefold()
    s = re.sub(r"[^a-z0-9\\s]+", " ", s)
    s = re.sub(r"\\s+", " ", s)
    return s.strip()


class LocationIndex:
    def __init__(
        self,
        index_csv: Path,
        *,
        min_query_len: int = 2,
        prefix_len: int = 2,
    ) -> None:
        self.index_csv = Path(index_csv)
        self.min_query_len = int(min_query_len)
        self.prefix_len = int(prefix_len)

        self._labels: List[str] = []
        self._norm_labels: List[str] = []
        self._norm_cities: List[str] = []
        self._slugs: List[str] = []
        self._ids: List[int] = []
        self._lats: List[float] = []
        self._lons: List[float] = []
        self._country_codes: List[str] = []
        self._populations: List[int] = []
        self._by_id: Dict[int, int] = {}
        self._by_slug: Dict[str, int] = {}
        self._prefix_map: Dict[str, List[int]] = {}

        self._load()

    def _load(self) -> None:
        if not self.index_csv.exists():
            raise FileNotFoundError(f"Location index not found: {self.index_csv}")

        with open(self.index_csv, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                geonameid = int(row.get("geonameid") or 0)
                slug = (row.get("slug") or "").strip()
                label = (row.get("label") or "").strip()
                lat = float(row.get("lat") or 0.0)
                lon = float(row.get("lon") or 0.0)
                cc = (row.get("country_code") or "").strip()
                pop = int(float(row.get("population") or 0))
                norm_label = row.get("norm_label") or _norm(label)
                norm_city = row.get("norm_city") or _norm(row.get("city_name") or "")

                i = len(self._labels)
                self._labels.append(label)
                self._norm_labels.append(norm_label)
                self._norm_cities.append(norm_city)
                self._slugs.append(slug)
                self._ids.append(geonameid)
                self._lats.append(lat)
                self._lons.append(lon)
                self._country_codes.append(cc)
                self._populations.append(pop)

                if geonameid:
                    self._by_id[geonameid] = i
                if slug:
                    self._by_slug[slug] = i

                self._add_prefixes(i, norm_label)
                self._add_prefixes(i, norm_city)

    def _add_prefixes(self, i: int, s: str) -> None:
        if not s:
            return
        key = s[: self.prefix_len]
        if len(key) < self.prefix_len:
            return
        self._prefix_map.setdefault(key, []).append(i)

    def _hit(self, i: int) -> LocationHit:
        return LocationHit(
            geonameid=self._ids[i],
            slug=self._slugs[i],
            label=self._labels[i],
            lat=self._lats[i],
            lon=self._lons[i],
            country_code=self._country_codes[i],
            population=self._populations[i],
        )

    def autocomplete(self, query: str, *, limit: int = 10) -> List[LocationHit]:
        q = _norm(query)
        if len(q) < self.min_query_len:
            return []

        key = q[: self.prefix_len] if len(q) >= self.prefix_len else q
        candidates = self._prefix_map.get(key, [])
        if not candidates:
            return []

        hits: List[int] = []
        seen: set[int] = set()
        for i in candidates:
            if i in seen:
                continue
            if self._norm_labels[i].startswith(q) or self._norm_cities[i].startswith(q):
                seen.add(i)
                hits.append(i)

        hits.sort(key=lambda i: (-self._populations[i], self._labels[i]))
        return [self._hit(i) for i in hits[:limit]]

    def resolve_by_id(self, geonameid: int) -> Optional[LocationHit]:
        idx = self._by_id.get(int(geonameid))
        if idx is None:
            return None
        return self._hit(idx)

    def resolve_by_slug(self, slug: str) -> Optional[LocationHit]:
        idx = self._by_slug.get(slug)
        if idx is None:
            return None
        return self._hit(idx)

    def resolve_by_label(self, label: str) -> Optional[LocationHit]:
        q = _norm(label)
        if not q:
            return None
        # Prefer exact label match
        for i, nl in enumerate(self._norm_labels):
            if nl == q:
                return self._hit(i)
        return None
