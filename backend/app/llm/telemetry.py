"""LLM response usage and cost normalization."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


def _read_value(value: Any, key: str, default: Any = None) -> Any:
    """Read a field from either a mapping-style or attribute-style response."""
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _fallback_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate USD cost when the provider omits it from the response."""
    try:
        import litellm

        prompt_cost, completion_cost = litellm.cost_per_token(
            model=model, prompt_tokens=input_tokens, completion_tokens=output_tokens
        )
        return float(prompt_cost + completion_cost)
    except Exception as exc:
        logger.debug("llm_cost_fallback_failed", model=model, error=str(exc))
        return 0.0


def extract_llm_call_usage(response: Any, model: str) -> dict[str, int | float]:
    """Normalize token, cost, reasoning, and cache details from one response."""
    usage_metadata = _read_value(response, "usage_metadata") or {}
    response_metadata = _read_value(response, "response_metadata") or {}
    raw_usage = (
        _read_value(response_metadata, "token_usage")
        or _read_value(response_metadata, "usage")
        or {}
    )
    input_tokens = int(
        _read_value(usage_metadata, "input_tokens") or _read_value(raw_usage, "prompt_tokens") or 0
    )
    output_tokens = int(
        _read_value(usage_metadata, "output_tokens")
        or _read_value(raw_usage, "completion_tokens")
        or 0
    )
    total_tokens = int(
        _read_value(usage_metadata, "total_tokens")
        or _read_value(raw_usage, "total_tokens")
        or (input_tokens + output_tokens)
    )
    output_token_details = _read_value(usage_metadata, "output_token_details") or {}
    completion_tokens_details = _read_value(raw_usage, "completion_tokens_details") or {}
    reasoning_tokens = int(
        _read_value(output_token_details, "reasoning")
        or _read_value(completion_tokens_details, "reasoning_tokens")
        or 0
    )
    input_token_details = _read_value(usage_metadata, "input_token_details") or {}
    prompt_tokens_details = _read_value(raw_usage, "prompt_tokens_details") or {}
    cached_tokens = int(
        _read_value(input_token_details, "cache_read")
        or _read_value(prompt_tokens_details, "cached_tokens")
        or 0
    )
    cost = _read_value(raw_usage, "cost")
    if cost is None:
        hidden_params = _read_value(response, "_hidden_params") or {}
        cost = _read_value(hidden_params, "response_cost") or _read_value(
            response_metadata, "response_cost"
        )
    cost_usd = (
        float(cost) if cost is not None else _fallback_cost_usd(model, input_tokens, output_tokens)
    )
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "cached_tokens": cached_tokens,
        "total_tokens": total_tokens,
        "cost_usd": cost_usd,
    }
