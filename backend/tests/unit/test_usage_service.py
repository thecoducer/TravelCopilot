"""Unit tests for per-run usage aggregation (Redis path + in-process fallback)."""

from __future__ import annotations

import pytest

from app.services import usage_service
from app.services.cache_service import CacheService


class _AlwaysFailingCache:
    """Stand-in for CacheService when Redis is unavailable in this test."""

    async def incr_hash(self, key: str, increments: dict[str, float], ttl: int) -> bool:
        return False

    async def get_hash(self, key: str) -> dict[str, float] | None:
        return None

    async def delete(self, key: str) -> None:
        return None

    async def close(self) -> None:
        return None


class _FakeRedisCache:
    """Stand-in for CacheService backed by an in-memory hash store."""

    def __init__(self) -> None:
        self._hashes: dict[str, dict[str, float]] = {}

    async def incr_hash(self, key: str, increments: dict[str, float], ttl: int) -> bool:
        hash_ = self._hashes.setdefault(key, {})
        for field, value in increments.items():
            hash_[field] = hash_.get(field, 0.0) + value
        return True

    async def get_hash(self, key: str) -> dict[str, float] | None:
        return dict(self._hashes[key]) if key in self._hashes else None

    async def delete(self, key: str) -> None:
        self._hashes.pop(key, None)

    async def close(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _clear_fallback_store():
    usage_service._fallback_totals.clear()
    yield
    usage_service._fallback_totals.clear()


@pytest.mark.asyncio
async def test_record_and_read_usage_via_redis(monkeypatch):
    fake_cache = _FakeRedisCache()
    monkeypatch.setattr(usage_service, "_new_cache", lambda: fake_cache)

    await usage_service.record_llm_call_usage(
        "trip-1", {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15, "cost_usd": 0.01}
    )
    await usage_service.record_llm_call_usage(
        "trip-1", {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30, "cost_usd": 0.02}
    )

    usage = await usage_service.get_run_usage("trip-1")

    assert usage.input_tokens == 30
    assert usage.output_tokens == 15
    assert usage.total_tokens == 45
    assert round(usage.cost_usd, 2) == 0.03
    assert usage.llm_calls == 2


@pytest.mark.asyncio
async def test_falls_back_to_in_process_accumulator_when_redis_unavailable(monkeypatch):
    monkeypatch.setattr(usage_service, "_new_cache", _AlwaysFailingCache)

    await usage_service.record_llm_call_usage("trip-2", {"input_tokens": 7, "output_tokens": 3})

    usage = await usage_service.get_run_usage("trip-2")

    assert usage.input_tokens == 7
    assert usage.output_tokens == 3
    assert usage.llm_calls == 1


@pytest.mark.asyncio
async def test_get_run_usage_returns_zeros_for_unknown_run():
    usage = await usage_service.get_run_usage("never-seen")
    assert usage.total_tokens == 0
    assert usage.cost_usd == 0.0


@pytest.mark.asyncio
async def test_record_llm_call_usage_noop_without_run_id():
    # Must not raise even though no run_id is bound.
    await usage_service.record_llm_call_usage("", {"input_tokens": 5})


@pytest.mark.asyncio
async def test_clear_run_usage_removes_fallback_entry(monkeypatch):
    monkeypatch.setattr(usage_service, "_new_cache", _AlwaysFailingCache)
    await usage_service.record_llm_call_usage("trip-3", {"input_tokens": 1})

    await usage_service.clear_run_usage("trip-3")

    usage = await usage_service.get_run_usage("trip-3")
    assert usage.input_tokens == 0


def test_run_usage_key_is_namespaced():
    assert CacheService.run_usage_key("trip-1") == "usage:run:trip-1"
