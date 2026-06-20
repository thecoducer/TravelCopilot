"""Redis cache service — async wrapper with typed TTL constants."""

from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

# ── TTL constants (seconds) — match plan's Redis Cache TTLs ────────────────
TTL_FLIGHTS = 4 * 3600  # 4 hours
TTL_HOTELS = 2 * 3600  # 2 hours
TTL_TRANSIT = 6 * 3600  # 6 hours
TTL_PLACES = 48 * 3600  # 48 hours
TTL_TAVILY = 24 * 3600  # 24 hours
TTL_FX_RATES = 12 * 3600  # 12 hours
TTL_RENTALS = 12 * 3600  # 12 hours
TTL_USAGE = 7 * 24 * 3600  # 7 days


class CacheService:
    """Async Redis wrapper.

    In unit tests, inject a ``FakeRedis`` or any object with
    ``get``, ``setex``, and ``delete`` coroutines.
    """

    def __init__(self, redis_url: str | None = None) -> None:
        self._url = redis_url or settings.redis_url
        self._client: aioredis.Redis | None = None

    async def _get_client(self) -> aioredis.Redis:
        if self._client is None:
            self._client = aioredis.from_url(self._url, decode_responses=True)
        return self._client

    # ── Public API ──────────────────────────────────────────────────────────

    async def get(self, key: str) -> dict[str, Any] | None:
        """Return the cached value or *None* if not found / expired."""
        try:
            client = await self._get_client()
            raw: str | None = await client.get(key)  # type: ignore[assignment]
            if raw is None:
                return None
            result: dict[str, Any] = json.loads(raw)
            return result
        except Exception:
            logger.exception("cache_get_error", extra={"key": key})
            return None

    async def set(self, key: str, value: dict[str, Any], ttl: int) -> None:
        """Store *value* at *key* with a TTL in seconds."""
        try:
            client = await self._get_client()
            await client.setex(key, ttl, json.dumps(value))
        except Exception:
            logger.exception("cache_set_error", extra={"key": key})

    async def delete(self, key: str) -> None:
        """Remove a key from the cache."""
        try:
            client = await self._get_client()
            await client.delete(key)
        except Exception:
            logger.exception("cache_delete_error", extra={"key": key})

    async def close(self) -> None:
        """Close the Redis connection pool gracefully."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ── Convenience key builders ────────────────────────────────────────────

    @staticmethod
    def flights_key(origin: str, dest: str, date: str) -> str:
        return f"flights:{origin}:{dest}:{date}"

    @staticmethod
    def hotels_key(location: str, checkin: str, checkout: str) -> str:
        return f"hotels:{location}:{checkin}:{checkout}"

    @staticmethod
    def transit_key(origin: str, dest: str, mode: str) -> str:
        return f"transit:{origin}:{dest}:{mode}"

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
    def usage_key(session_id: str, agent_name: str) -> str:
        return f"usage:{session_id}:{agent_name}"


# Module-level default instance — agents import this.
cache_service = CacheService()
