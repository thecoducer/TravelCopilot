"""Redis cache service — async wrapper with typed TTL constants."""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

import redis.asyncio as aioredis
import structlog

from app.config import settings

logger = structlog.get_logger(__name__)

# ── TTL constants (seconds) — match plan's Redis Cache TTLs ────────────────
TTL_FLIGHTS = 4 * 3600  # 4 hours
TTL_HOTELS = 2 * 3600  # 2 hours
TTL_TRANSIT = 6 * 3600  # 6 hours
TTL_PLACES = 48 * 3600  # 48 hours
TTL_TAVILY = 24 * 3600  # 24 hours
TTL_FX_RATES = 12 * 3600  # 12 hours
TTL_RENTALS = 12 * 3600  # 12 hours
TTL_RUN_USAGE = 3600  # 1 hour — only needs to outlive one planning run

# Fail fast when Redis is unreachable (e.g. local dev/tests without Docker) instead
# of paying the default multi-second TCP connect timeout on every cache access.
_CONNECT_TIMEOUT_SECONDS = 0.5
# After a connection failure, skip Redis entirely for this long before retrying,
# so one outage doesn't cost every subsequent cache call its own connect attempt.
_BREAKER_COOLDOWN_SECONDS = 30.0


class CacheService:
    """Async Redis wrapper.

    In unit tests, inject a ``FakeRedis`` or any object with
    ``get``, ``setex``, and ``delete`` coroutines.
    """

    def __init__(self, redis_url: str | None = None) -> None:
        self._url = redis_url or settings.redis_url
        self._client: aioredis.Redis | None = None
        self._unavailable_until: float = 0.0

    async def _get_client(self) -> aioredis.Redis:
        if self._client is None:
            self._client = aioredis.from_url(
                self._url,
                decode_responses=True,
                socket_connect_timeout=_CONNECT_TIMEOUT_SECONDS,
                socket_timeout=_CONNECT_TIMEOUT_SECONDS,
            )
        return self._client

    def _breaker_open(self) -> bool:
        return time.monotonic() < self._unavailable_until

    def _trip_breaker(self) -> None:
        self._unavailable_until = time.monotonic() + _BREAKER_COOLDOWN_SECONDS

    # ── Public API ──────────────────────────────────────────────────────────

    async def get(self, key: str) -> dict[str, Any] | None:
        """Return the cached value or *None* if not found / expired."""
        if self._breaker_open():
            return None
        try:
            client = await self._get_client()
            raw: str | None = await client.get(key)  # type: ignore[assignment]
            if raw is None:
                return None
            result: dict[str, Any] = json.loads(raw)
            return result
        except Exception:
            logger.exception("cache_get_error", key=key)
            self._trip_breaker()
            return None

    async def set(self, key: str, value: dict[str, Any], ttl: int) -> None:
        """Store *value* at *key* with a TTL in seconds."""
        if self._breaker_open():
            return
        try:
            client = await self._get_client()
            await client.setex(key, ttl, json.dumps(value))
        except Exception:
            logger.exception("cache_set_error", key=key)
            self._trip_breaker()

    async def delete(self, key: str) -> None:
        """Remove a key from the cache."""
        if self._breaker_open():
            return
        try:
            client = await self._get_client()
            await client.delete(key)
        except Exception:
            logger.exception("cache_delete_error", key=key)
            self._trip_breaker()

    async def get_or_set(
        self, key: str, ttl: int, fetch: Callable[[], Awaitable[dict[str, Any]]]
    ) -> dict[str, Any]:
        """Return the cached value for *key*, calling *fetch* once on a cache miss."""
        cached = await self.get(key)
        if cached is not None:
            return cached
        value = await fetch()
        await self.set(key, value, ttl)
        return value

    async def incr_hash(self, key: str, increments: dict[str, float], ttl: int) -> bool:
        """Atomically add *increments* to a Redis hash and refresh its TTL.

        Returns ``False`` (without partial writes) when Redis is unavailable, so
        callers can fall back to an in-process accumulator instead of losing data.
        """
        if self._breaker_open():
            return False
        try:
            client = await self._get_client()
            pipe = client.pipeline()
            for field, value in increments.items():
                pipe.hincrbyfloat(key, field, value)
            pipe.expire(key, ttl)
            await pipe.execute()
            return True
        except Exception:
            logger.exception("cache_incr_hash_error", key=key)
            self._trip_breaker()
            return False

    async def get_hash(self, key: str) -> dict[str, float] | None:
        """Return a Redis hash as floats, or *None* if absent/unavailable."""
        if self._breaker_open():
            return None
        try:
            client = await self._get_client()
            raw: dict[str, str] = await client.hgetall(key)  # type: ignore[assignment]
            if not raw:
                return None
            return {field: float(value) for field, value in raw.items()}
        except Exception:
            logger.exception("cache_get_hash_error", key=key)
            self._trip_breaker()
            return None

    async def close(self) -> None:
        """Close the Redis connection pool gracefully."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ── Convenience key builders ────────────────────────────────────────────
    # Priced lookups are namespaced by currency: the same search in INR and USD
    # returns different payloads and must never share a cache entry.

    @staticmethod
    def flights_key(origin: str, dest: str, date: str, currency: str) -> str:
        return f"flights:{origin}:{dest}:{date}:{currency}"

    @staticmethod
    def hotels_key(location: str, checkin: str, checkout: str, currency: str) -> str:
        return f"hotels:{location}:{checkin}:{checkout}:{currency}"

    @staticmethod
    def transit_key(origin: str, dest: str, mode: str, date: str) -> str:
        return f"transit:{origin}:{dest}:{mode}:{date}"

    @staticmethod
    def place_key(place_id: str) -> str:
        return f"place:{place_id}"

    @staticmethod
    def tavily_key(dest: str, month: str, query_hash: str) -> str:
        return f"tavily:{dest}:{month}:{query_hash}"

    @staticmethod
    def fx_key(base: str, quote: str) -> str:
        return f"fx:{base}:{quote}"

    @staticmethod
    def rentals_key(destination: str) -> str:
        return f"rentals:{destination}"

    @staticmethod
    def run_usage_key(run_id: str) -> str:
        return f"usage:run:{run_id}"


# Module-level default instance — agents import this.
cache_service = CacheService()
