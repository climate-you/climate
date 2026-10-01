from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import csv
import unicodedata
import re
from typing import List, Dict, Optional, Tuple

from climate_api.store.sovereignty import is_sovereign

# Kinds of index entry, mirroring the `kind` column written by
# scripts/build/build_locations.py. Everything that is not a city is an area
# and carries a bounding box.
KIND_CITY = "city"

KIND_COUNTRY = "country"
KIND_STATE = "state"

# Autocomplete match ranks, best first. See `LocationIndex._match_rank`.
_RANK_AREA_NAMED = 0
_RANK_AREA_PARTIAL = 1
_RANK_WORD_START = 2
_RANK_MID_WORD = 3
_RANK_LABEL_ONLY = 4

# A city at least this populous can outrank a sea or lake that the query has
# only partly named. "san francis" should mean San Francisco (827 k) before its
# bay, and "rio de" Rio de Janeiro before the Río de la Plata — but "north s"
# should still mean the North Sea, not North Stamford (121 k). Any cut-off
# between those two keeps all three right; this is a round "major city".
_MAJOR_CITY_POPULATION = 500_000


def _starts_a_word(q: str, name: str) -> bool:
    """Whether `q` begins one of the words of `name`: "fran" in "san francisco"."""
    return name.startswith(q) or f" {q}" in name


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
    kind: str = KIND_CITY
    # (west, south, east, north) for area entries; None for cities. `east` may
    # exceed 180 for a box that straddles the antimeridian.
    bbox: Optional[Tuple[float, float, float, float]] = None
    # Key into the release's regional aggregates ("country:FR"), or None
    # for a place that has no region. Whether the region actually has data
    # is a per-release question the API answers, not the index.
    region_id: Optional[str] = None


def _parse_bbox(raw: Optional[str]) -> Optional[Tuple[float, float, float, float]]:
    """Parse a "west,south,east,north" index cell; empty for city entries."""
    if not raw:
        return None
    parts = raw.split(",")
    if len(parts) != 4:
        return None
    try:
        west, south, east, north = (float(p) for p in parts)
    except ValueError:
        return None
    return (west, south, east, north)


def _without_article(norm: str) -> str:
    """A normalised name without a leading "the".

    GeoNames spells one country "The Netherlands", and a reader may type "the
    United Kingdom" as readily as "United Kingdom". The article belongs to the
    name only in running text, so matching ignores it on both sides.
    """
    return norm[4:] if norm.startswith("the ") else norm


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
        self._kinds: List[str] = []
        self._bboxes: List[Optional[Tuple[float, float, float, float]]] = []
        self._region_ids: List[Optional[str]] = []
        self._by_id: Dict[int, int] = {}
        self._by_region_id: Dict[str, int] = {}
        self._prefix_map: Dict[str, List[int]] = {}
        self._name_to_idx: Dict[str, int] = {}
        # Only names shared by more than one place ("Cologne" → Köln and Cologne
        # IT), so they can be disambiguated by country. Names with a single
        # owner are served from _name_to_idx instead: holding a list for all
        # ~800k names costs ~100 MB for the ~6% that actually need it.
        self._name_collisions: Dict[str, List[int]] = {}
        # Largest city population per country code; see `_sort_population`.
        self._largest_city_population: Dict[str, int] = {}

        self._load()
        for i, kind in enumerate(self._kinds):
            if kind != KIND_CITY:
                continue
            cc = self._country_codes[i]
            if self._populations[i] > self._largest_city_population.get(cc, 0):
                self._largest_city_population[cc] = self._populations[i]

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
                kind = (row.get("kind") or "").strip().lower() or KIND_CITY
                bbox = _parse_bbox(row.get("bbox"))
                region_id = (row.get("region_id") or "").strip() or None

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
                self._kinds.append(kind)
                self._bboxes.append(bbox)
                self._region_ids.append(region_id)

                if geonameid:
                    self._by_id[geonameid] = i
                if region_id:
                    self._by_region_id[region_id] = i

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
                    if self._name_owner_rank(kind, pop) < self._name_owner_rank(
                        self._kinds[existing], self._populations[existing]
                    ):
                        self._name_to_idx[norm_name] = i
                    if existing == i:
                        continue
                    # Second owner of this name — start tracking the homonyms.
                    bucket = self._name_collisions.get(norm_name)
                    if bucket is None:
                        bucket = self._name_collisions[norm_name] = [existing]
                    if i not in bucket:
                        bucket.append(i)

    @staticmethod
    def _name_owner_rank(kind: str, population: int) -> tuple[int, int]:
        """
        Ordering for which entry owns a name outright — lower wins.

        A city always beats an area of the same name, so that resolving
        "Mexico" keeps landing on Mexico City rather than jumping to the
        country's label point.
        """
        return (0 if kind == KIND_CITY else 1, -population)

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
            kind=self._kinds[i] if i < len(self._kinds) else KIND_CITY,
            bbox=self._bboxes[i] if i < len(self._bboxes) else None,
            region_id=(self._region_ids[i] if i < len(self._region_ids) else None),
        )

    def _match_rank(self, i: int, q: str) -> int:
        """
        How well entry `i` answers query `q` — lower is better.

        Naming an area outright, or typing enough words to be clearly after one,
        promotes it above everything: the North Sea, not the Long Island village
        of the same name.

        Otherwise, people type the start of a word, so the rest is graded by
        where the query lands in the place's *own* name: at the start of a word
        ("ger" → Germany), inside one ("ger" → Nigeria), or nowhere in the name
        at all but in the region or country a city's label carries ("ger" →
        "Lagos, Nigeria"). Without that grading "fran" buried France under every
        French city, and "ger" listed Nigerian cities before Germany.
        """
        own = self._norm_cities[i]
        own_names = (own, _without_article(own))
        if self._kinds[i] == KIND_CITY:
            if (
                " " in q
                and self._populations[i] >= _MAJOR_CITY_POPULATION
                and any(name.startswith(q) for name in own_names)
            ):
                # A major city the reader may still be typing competes with a
                # partly named sea on equal terms, and wins on population.
                return _RANK_AREA_PARTIAL
            if any(_starts_a_word(q, name) for name in own_names):
                return _RANK_WORD_START
            if any(q in name for name in own_names):
                return _RANK_MID_WORD
            return _RANK_LABEL_ONLY
        names = {
            name
            for norm in (self._norm_labels[i], self._norm_cities[i])
            for name in (norm, _without_article(norm))
        }
        if q in names:
            return _RANK_AREA_NAMED
        if " " in q and any(name.startswith(q) for name in names):
            return _RANK_AREA_PARTIAL
        if any(_starts_a_word(q, name) for name in names):
            return _RANK_WORD_START
        return _RANK_MID_WORD

    def _sort_population(self, i: int) -> int:
        """Population used to order matches of the same rank.

        A city ranks by its own population. A country ranks as prominently as
        its largest city: its own population would put it above almost every
        city sharing its first letters — Paraguay above Paris for "par",
        Madagascar above Madrid for "mad" — while zero would drop it out of the
        list entirely. A state (Alaska) carries its largest town's population,
        set at build time, where towns' states are known. Seas and lakes have
        no population to borrow, and are found by naming them.
        """
        kind = self._kinds[i]
        if kind in (KIND_CITY, KIND_STATE):
            return self._populations[i]
        if kind == KIND_COUNTRY:
            return self._largest_city_population.get(self._country_codes[i], 0)
        return 0

    def autocomplete(self, query: str, *, limit: int = 10) -> List[LocationHit]:
        q = _norm(query)
        # "the north sea" should find the North Sea; keep the query as typed
        # when the article is all there is, so "the" still finds The Hague.
        if len(_without_article(q)) >= self.min_query_len:
            q = _without_article(q)
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

        hits.sort(
            key=lambda i: (
                self._match_rank(i, q),
                -self._sort_population(i),
                self._labels[i],
            )
        )
        return [self._hit(i) for i in hits[:limit]]

    def resolve_by_id(self, geonameid: int) -> Optional[LocationHit]:
        idx = self._by_id.get(int(geonameid))
        if idx is None:
            return None
        return self._hit(idx)

    def resolve_by_region_id(self, region_id: str) -> Optional[LocationHit]:
        """The index entry for an aggregate region, e.g. ``country:FR``."""
        idx = self._by_region_id.get(region_id)
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

        Cities first, then by descending population. Unlike
        `resolve_by_any_name`, this keeps the less-populous homonyms so callers
        can disambiguate them by country — "Cologne" matches both Köln (DE) and
        Cologne (IT).
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
            key=lambda h: self._name_owner_rank(h.kind, h.population) + (h.label,),
        )

    def iter_all(
        self, *, min_population: int = 0, capitals_only: bool = False
    ) -> List[LocationHit]:
        """
        Return all cities matching the given filters, sorted by population descending.

        Cities only: callers rank populated places against each other, and the
        index also holds countries, seas and lakes, whose populations are either
        absent or count a whole nation.

        `capitals_only` keeps capitals of sovereign states only. The stored
        capital flag comes from the GeoNames PPLC feature code, which also
        marks the capitals of dependencies such as Greenland or Svalbard;
        see `climate_api.store.sovereignty` for why those are excluded.
        """
        result = []
        for i in range(len(self._labels)):
            if self._kinds[i] != KIND_CITY:
                continue
            if min_population > 0 and self._populations[i] < min_population:
                continue
            if capitals_only and not (
                self._capitals[i] and is_sovereign(self._country_codes[i])
            ):
                continue
            result.append(self._hit(i))
        result.sort(key=lambda h: -h.population)
        return result
