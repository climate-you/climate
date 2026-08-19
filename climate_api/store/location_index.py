from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import csv
import unicodedata
import re
from typing import List, Dict, Optional

from climate_api.store.sovereignty import is_sovereign


@dataclass(frozen=True)
class LocationHit:
    geonameid: int
    label: str
    lat: float
    lon: float
    country_code: str
    population: int
    capital: bool = False
    alt_names: str = ""


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
        min_query_len: int = 3,
        prefix_len: int = 3,
    ) -> None:
        self.index_csv = Path(index_csv)
        self.min_query_len = int(min_query_len)
        self.prefix_len = int(prefix_len)

        self._labels: List[str] = []
        self._norm_labels: List[str] = []
        self._norm_cities: List[str] = []
        self._ids: List[int] = []
        self._lats: List[float] = []
        self._lons: List[float] = []
        self._country_codes: List[str] = []
        self._populations: List[int] = []
        self._capitals: List[bool] = []
        self._alt_names: List[str] = []
        self._by_id: Dict[int, int] = {}
        self._prefix_map: Dict[str, List[int]] = {}
        self._name_to_idx: Dict[str, int] = {}
        # Only names shared by more than one place ("Cologne" → Köln and Cologne
        # IT), so they can be disambiguated by country. Names with a single
        # owner are served from _name_to_idx instead: holding a list for all
        # ~800k names costs ~100 MB for the ~6% that actually need it.
        self._name_collisions: Dict[str, List[int]] = {}

        self._load()

    def _load(self) -> None:
        if not self.index_csv.exists():
            raise FileNotFoundError(f"Location index not found: {self.index_csv}")

        with open(self.index_csv, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                geonameid = int(row.get("geonameid") or 0)
                label = (row.get("label") or "").strip()
                lat = float(row.get("lat") or 0.0)
                lon = float(row.get("lon") or 0.0)
                cc = (row.get("country_code") or "").strip()
                pop = int(float(row.get("population") or 0))
                capital = (row.get("capital") or "").strip().lower() == "true"
                norm_label = row.get("norm_label") or _norm(label)
                norm_city = row.get("norm_city") or _norm(row.get("city_name") or "")
                alt_names = (row.get("alt_names") or "").strip()

                i = len(self._labels)
                self._labels.append(label)
                self._norm_labels.append(norm_label)
                self._norm_cities.append(norm_city)
                self._ids.append(geonameid)
                self._lats.append(lat)
                self._lons.append(lon)
                self._country_codes.append(cc)
                self._populations.append(pop)
                self._capitals.append(capital)
                self._alt_names.append(alt_names)

                if geonameid:
                    self._by_id[geonameid] = i

                self._add_prefixes(i, norm_label)
                self._add_prefixes(i, norm_city)

                # Build name→index hash map (highest population wins per name)
                names = [norm_label, norm_city]
                names += [_norm(raw_alt) for raw_alt in alt_names.split(",")]
                for norm_name in names:
                    if not norm_name or len(norm_name) < self.min_query_len:
                        continue
                    existing = self._name_to_idx.get(norm_name)
                    if existing is None:
                        self._name_to_idx[norm_name] = i
                        continue
                    if pop > self._populations[existing]:
                        self._name_to_idx[norm_name] = i
                    if existing == i:
                        continue
                    # Second owner of this name — start tracking the homonyms.
                    bucket = self._name_collisions.get(norm_name)
                    if bucket is None:
                        bucket = self._name_collisions[norm_name] = [existing]
                    if i not in bucket:
                        bucket.append(i)

    def _add_prefixes(self, i: int, s: str) -> None:
        if not s:
            return
        seen_keys: set[str] = set()
        for start in range(len(s) - self.prefix_len + 1):
            key = s[start : start + self.prefix_len]
            if key not in seen_keys:
                seen_keys.add(key)
                self._prefix_map.setdefault(key, []).append(i)

    def _hit(self, i: int) -> LocationHit:
        return LocationHit(
            geonameid=self._ids[i],
            label=self._labels[i],
            lat=self._lats[i],
            lon=self._lons[i],
            country_code=self._country_codes[i],
            population=self._populations[i],
            capital=self._capitals[i],
            alt_names=self._alt_names[i] if i < len(self._alt_names) else "",
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
            if q in self._norm_labels[i] or q in self._norm_cities[i]:
                seen.add(i)
                hits.append(i)

        hits.sort(key=lambda i: (-self._populations[i], self._labels[i]))
        return [self._hit(i) for i in hits[:limit]]

    def resolve_by_id(self, geonameid: int) -> Optional[LocationHit]:
        idx = self._by_id.get(int(geonameid))
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

    def resolve_by_any_name(self, name: str) -> Optional[LocationHit]:
        """Resolve a city name by checking label, city_name, and alt_names.

        Returns the highest-population match, or None if not found.
        Uses a pre-built hash map for O(1) lookup.
        """
        q = _norm(name)
        if not q or len(q) < self.min_query_len:
            return None
        i = self._name_to_idx.get(q)
        return self._hit(i) if i is not None else None

    def resolve_all_by_any_name(self, name: str) -> List[LocationHit]:
        """Every place matching `name` exactly (label, city name, or alt name).

        Sorted by descending population. Unlike `resolve_by_any_name`, this
        keeps the less-populous homonyms so callers can disambiguate them by
        country — "Cologne" matches both Köln (DE) and Cologne (IT).
        """
        q = _norm(name)
        if not q or len(q) < self.min_query_len:
            return []
        idxs = self._name_collisions.get(q)
        if idxs is None:
            single = self._name_to_idx.get(q)
            return [self._hit(single)] if single is not None else []
        return sorted(
            (self._hit(i) for i in idxs),
            key=lambda h: (-h.population, h.label),
        )

    def iter_all(
        self, *, min_population: int = 0, capitals_only: bool = False
    ) -> List[LocationHit]:
        """
        Return all locations matching the given filters, sorted by population descending.

        `capitals_only` keeps capitals of sovereign states only. The stored
        capital flag comes from the GeoNames PPLC feature code, which also
        marks the capitals of dependencies such as Greenland or Svalbard;
        see `climate_api.store.sovereignty` for why those are excluded.
        """
        result = []
        for i in range(len(self._labels)):
            if min_population > 0 and self._populations[i] < min_population:
                continue
            if capitals_only and not (
                self._capitals[i] and is_sovereign(self._country_codes[i])
            ):
                continue
            result.append(self._hit(i))
        result.sort(key=lambda h: -h.population)
        return result
