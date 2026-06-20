"""Unit tests for CacheService with an in-memory fake Redis (no real connection)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.cache_service import (
    TTL_FLIGHTS,
    TTL_FX_RATES,
    TTL_HOTELS,
    TTL_PLACES,
    CacheService,
)


class FakeRedis:
    """Minimal in-memory Redis stand-in for unit tests."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._store[key] = value

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def aclose(self) -> None:
        pass


@pytest.fixture
def cache(monkeypatch) -> CacheService:
    svc = CacheService(redis_url="redis://localhost:6379/0")
    svc._client = FakeRedis()  # type: ignore[assignment]
    return svc


class TestCacheServiceGetSet:
    @pytest.mark.asyncio
    async def test_get_missing_key_returns_none(self, cache: CacheService):
        result = await cache.get("nonexistent:key")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_then_get_round_trip(self, cache: CacheService):
        payload = {"flights": [{"operator": "IndiGo", "cost": 5000}]}
        await cache.set("flights:KOL:DEL:2026-10-01", payload, TTL_FLIGHTS)
        result = await cache.get("flights:KOL:DEL:2026-10-01")
        assert result == payload

    @pytest.mark.asyncio
    async def test_delete_removes_key(self, cache: CacheService):
        await cache.set("hotels:osaka:2026-10-01:2026-10-04", {"hotels": []}, TTL_HOTELS)
        await cache.delete("hotels:osaka:2026-10-01:2026-10-04")
        result = await cache.get("hotels:osaka:2026-10-01:2026-10-04")
        assert result is None

    @pytest.mark.asyncio
    async def test_overwrite_key(self, cache: CacheService):
        await cache.set("fx:JPY:INR", {"rate": 0.55}, TTL_FX_RATES)
        await cache.set("fx:JPY:INR", {"rate": 0.558}, TTL_FX_RATES)
        result = await cache.get("fx:JPY:INR")
        assert result["rate"] == 0.558


class TestCacheServiceKeyBuilders:
    def test_flights_key(self):
        assert CacheService.flights_key("KOL", "DEL", "2026-10-01") == "flights:KOL:DEL:2026-10-01"

    def test_hotels_key(self):
        expected = "hotels:osaka:2026-10-01:2026-10-04"
        assert CacheService.hotels_key("osaka", "2026-10-01", "2026-10-04") == expected

    def test_place_key(self):
        assert CacheService.place_key("ChIJ123") == "place:ChIJ123"

    def test_fx_key(self):
        assert CacheService.fx_key("JPY", "INR") == "fx:JPY:INR"

    def test_usage_key(self):
        key = CacheService.usage_key("sess_abc", "orchestrator")
        assert "sess_abc" in key and "orchestrator" in key


class TestTtlConstants:
    def test_ttl_values_are_positive(self):
        assert TTL_FLIGHTS > 0
        assert TTL_HOTELS > 0
        assert TTL_PLACES > 0
        assert TTL_FX_RATES > 0

    def test_ttl_ordering(self):
        # Hotels expire faster than flights; places expire slowest
        assert TTL_HOTELS < TTL_FLIGHTS
        assert TTL_FLIGHTS < TTL_PLACES


class TestCacheServiceErrorHandling:
    @pytest.mark.asyncio
    async def test_get_exception_returns_none(self):
        svc = CacheService()
        broken_client = MagicMock()
        broken_client.get = AsyncMock(side_effect=ConnectionError("Redis down"))
        svc._client = broken_client
        result = await svc.get("some:key")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_exception_is_swallowed(self):
        svc = CacheService()
        broken_client = MagicMock()
        broken_client.setex = AsyncMock(side_effect=ConnectionError("Redis down"))
        svc._client = broken_client
        # Should not raise — errors are logged and swallowed
        await svc.set("some:key", {"data": 1}, 3600)
