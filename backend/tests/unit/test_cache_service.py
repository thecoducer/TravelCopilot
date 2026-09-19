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


class FakeRedisPipeline:
    """Minimal pipeline stand-in supporting the hash increment ops we use."""

    def __init__(self, redis: FakeRedis) -> None:
        self._redis = redis
        self._ops: list[tuple[str, ...]] = []

    def hincrbyfloat(self, key: str, field: str, value: float) -> FakeRedisPipeline:
        self._ops.append(("hincrbyfloat", key, field, str(value)))
        return self

    def expire(self, key: str, ttl: int) -> FakeRedisPipeline:
        self._ops.append(("expire", key, str(ttl)))
        return self

    async def execute(self) -> None:
        for op, key, *rest in self._ops:
            if op == "hincrbyfloat":
                field, value = rest
                current = float(self._redis._hashes.setdefault(key, {}).get(field, 0.0))
                self._redis._hashes[key][field] = str(current + float(value))
        self._ops = []


class FakeRedis:
    """Minimal in-memory Redis stand-in for unit tests."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._hashes: dict[str, dict[str, str]] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._store[key] = value

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)
        self._hashes.pop(key, None)

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self._hashes.get(key, {}))

    def pipeline(self) -> FakeRedisPipeline:
        return FakeRedisPipeline(self)

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


class TestCacheServiceHashOps:
    @pytest.mark.asyncio
    async def test_incr_hash_accumulates_across_calls(self, cache: CacheService):
        key = CacheService.run_usage_key("trip-1")
        await cache.incr_hash(key, {"input_tokens": 10, "cost_usd": 0.01}, ttl=60)
        await cache.incr_hash(key, {"input_tokens": 5, "cost_usd": 0.02}, ttl=60)

        stored = await cache.get_hash(key)

        assert stored is not None
        assert stored["input_tokens"] == 15.0
        assert round(stored["cost_usd"], 2) == 0.03

    @pytest.mark.asyncio
    async def test_get_hash_returns_none_when_absent(self, cache: CacheService):
        assert await cache.get_hash("usage:run:missing") is None

    @pytest.mark.asyncio
    async def test_incr_hash_returns_false_when_breaker_open(self, cache: CacheService):
        cache._trip_breaker()
        stored = await cache.incr_hash("usage:run:trip-1", {"input_tokens": 1}, ttl=60)
        assert stored is False


class TestCacheServiceKeyBuilders:
    def test_flights_key(self):
        expected = "flights:KOL:DEL:2026-10-01:INR"
        assert CacheService.flights_key("KOL", "DEL", "2026-10-01", "INR") == expected

    def test_hotels_key(self):
        expected = "hotels:osaka:2026-10-01:2026-10-04:INR"
        assert CacheService.hotels_key("osaka", "2026-10-01", "2026-10-04", "INR") == expected

    def test_priced_keys_are_namespaced_by_currency(self):
        """The same search in two currencies must not share a cache entry."""
        assert CacheService.hotels_key("osaka", "a", "b", "INR") != CacheService.hotels_key(
            "osaka", "a", "b", "USD"
        )
        assert CacheService.flights_key("KOL", "DEL", "d", "INR") != CacheService.flights_key(
            "KOL", "DEL", "d", "USD"
        )

    def test_place_key(self):
        assert CacheService.place_key("ChIJ123") == "place:ChIJ123"

    def test_fx_key(self):
        assert CacheService.fx_key("JPY", "INR") == "fx:JPY:INR"

    def test_run_usage_key(self):
        key = CacheService.run_usage_key("trip_abc")
        assert "trip_abc" in key


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
