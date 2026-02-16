from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Optional

try:
    from redis import Redis
except Exception:  # pragma: no cover
    Redis = None  # type: ignore


@dataclass
class Cache:
    redis: Optional["Redis"] = None
    prefix: str = "climate_api"

    # simple in-process fallback
    _mem: dict[str, tuple[float, bytes]] = None  # type: ignore

    def __post_init__(self) -> None:
        if self._mem is None:
            self._mem = {}

    def _k(self, key: str) -> str:
        return f"{self.prefix}:{key}"

    def get_json(self, key: str) -> Any | None:
        k = self._k(key)
        if self.redis is not None:
            b = self.redis.get(k)
            if b is None:
                return None
            return json.loads(b)

        # in-memory fallback (TTL stored alongside)
        item = self._mem.get(k)
        if item is None:
            return None
        expires_at, b = item
        if expires_at and time.time() > expires_at:
            self._mem.pop(k, None)
            return None
        return json.loads(b)

    def set_json(self, key: str, obj: Any, ttl_s: int) -> None:
        k = self._k(key)
        b = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if self.redis is not None:
            self.redis.setex(k, ttl_s, b)
            return
        self._mem[k] = (time.time() + ttl_s, b)


def make_redis_client(redis_url: str) -> "Redis":
    if Redis is None:
        raise RuntimeError("redis package not installed; pip install redis")
    r = Redis.from_url(redis_url, decode_responses=False)
    # fail fast if misconfigured
    r.ping()
    return r
