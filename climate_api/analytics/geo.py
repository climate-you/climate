from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

_IPAPICOM_URL = "http://ip-api.com/json/{ip}?fields=status,countryCode,lat,lon"
_TIMEOUT_S = 3

GeoResult = tuple[str | None, float | None, float | None]


class GeoIPCache:
    """ip-api.com lookup with an in-process TTL cache keyed by IP."""

    def __init__(self, ttl_s: int = 3600) -> None:
        self._ttl_s = ttl_s
        self._cache: dict[str, tuple[GeoResult, float]] = {}

    def lookup(self, ip: str) -> GeoResult:
        now = time.time()
        entry = self._cache.get(ip)
        if entry is not None:
            result, expiry = entry
            if now < expiry:
                return result
        result = self._fetch(ip)
        self._cache[ip] = (result, now + self._ttl_s)
        return result

    def _fetch(self, ip: str) -> GeoResult:
        try:
            url = _IPAPICOM_URL.format(ip=urllib.parse.quote(ip, safe=""))
            req = urllib.request.Request(
                url, headers={"User-Agent": "climate-analytics/1.0"}
            )
            with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
                data = json.loads(resp.read())
            if data.get("status") != "success":
                return (None, None, None)
            country = data.get("countryCode") or None
            lat = data.get("lat")
            lon = data.get("lon")
            if lat is None or lon is None:
                return (country, None, None)
            return (country, float(lat), float(lon))
        except Exception:
            logger.debug("GeoIP lookup failed for %s", ip, exc_info=True)
            return (None, None, None)
