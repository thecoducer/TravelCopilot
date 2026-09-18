"""Per-run LLM usage aggregation.

Redis (an atomic hash keyed by run id) is the primary store so concurrent
``asyncio.gather`` agent branches in the same run never race each other. An
in-process accumulator is the fallback when Redis's circuit breaker is open,
so usage tracking degrades instead of silently disappearing.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Final

import structlog

from app.models.reports import RunUsage
from app.services.cache_service import TTL_RUN_USAGE, CacheService

logger = structlog.get_logger(__name__)

_NUMERIC_FIELDS: Final[tuple[str, ...]] = (
    "input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "cached_tokens",
    "total_tokens",
    "cost_usd",
)

_fallback_lock = asyncio.Lock()
_fallback_totals: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))


def _new_cache() -> CacheService:
    """Factory seam so tests can stub the Redis client without touching
    ``CacheService.run_usage_key``, the pure static key builder used below."""
    return CacheService()


async def record_llm_call_usage(run_id: str, usage: dict[str, float]) -> None:
    """Add one LLM call's usage to the running total for *run_id*."""
    if not run_id:
        return
    increments = {field: float(usage.get(field, 0.0)) for field in _NUMERIC_FIELDS}
    increments["llm_calls"] = 1.0

    cache = _new_cache()
    try:
        key = CacheService.run_usage_key(run_id)
        stored = await cache.incr_hash(key, increments, TTL_RUN_USAGE)
    finally:
        await cache.close()

    if stored:
        return

    async with _fallback_lock:
        totals = _fallback_totals[run_id]
        for field, value in increments.items():
            totals[field] += value


async def get_run_usage(run_id: str) -> RunUsage:
    """Return the aggregated usage totals for *run_id*."""
    if not run_id:
        return RunUsage()

    cache = _new_cache()
    try:
        stored = await cache.get_hash(CacheService.run_usage_key(run_id))
    finally:
        await cache.close()

    if stored is None:
        async with _fallback_lock:
            stored = dict(_fallback_totals.get(run_id, {}))

    return RunUsage(
        input_tokens=int(stored.get("input_tokens", 0)),
        output_tokens=int(stored.get("output_tokens", 0)),
        reasoning_tokens=int(stored.get("reasoning_tokens", 0)),
        cached_tokens=int(stored.get("cached_tokens", 0)),
        total_tokens=int(stored.get("total_tokens", 0)),
        cost_usd=float(stored.get("cost_usd", 0.0)),
        llm_calls=int(stored.get("llm_calls", 0)),
    )


async def clear_run_usage(run_id: str) -> None:
    """Drop tracked usage for a finished run (Redis TTL would expire it anyway)."""
    if not run_id:
        return
    cache = _new_cache()
    try:
        await cache.delete(CacheService.run_usage_key(run_id))
    finally:
        await cache.close()
    async with _fallback_lock:
        _fallback_totals.pop(run_id, None)
