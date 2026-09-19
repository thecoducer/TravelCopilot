"""Provider-agnostic LangChain chat model factory and usage telemetry."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from contextvars import ContextVar, Token
from typing import Any

import structlog

from app.config import settings
from app.llm.config import llm_settings

logger = structlog.get_logger(__name__)

_ACTIVE_RUN_ID: ContextVar[str] = ContextVar("active_llm_run_id", default="")


def set_active_llm_run_id(run_id: str) -> Token[str]:
    """Bind a run ID to the current async context."""
    return _ACTIVE_RUN_ID.set(run_id)


def reset_active_llm_run_id(token: Token[str]) -> None:
    """Restore the previous run ID context."""
    _ACTIVE_RUN_ID.reset(token)


def get_active_llm_run_id() -> str:
    """Return the run ID bound for the current planning run, or ``""``."""
    return _ACTIVE_RUN_ID.get()


def _sync_api_keys() -> None:
    key_map = {
        "OPENAI_API_KEY": llm_settings.openai_api_key,
        "ANTHROPIC_API_KEY": llm_settings.anthropic_api_key,
        "GOOGLE_API_KEY": llm_settings.google_api_key,
        "GROQ_API_KEY": llm_settings.groq_api_key,
        "OPENROUTER_API_KEY": llm_settings.openrouter_api_key,
    }
    for env_var, value in key_map.items():
        if value and not os.environ.get(env_var):
            os.environ[env_var] = value


def try_enable_litellm_langfuse_callbacks() -> bool:
    """Enable Langfuse callbacks when the installed SDKs are compatible."""
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return False

    try:
        import langfuse
        import litellm

        if not hasattr(langfuse, "version"):
            logger.warning("langfuse_litellm_disabled", reason="langfuse.version missing")
            return False
        litellm.success_callback = ["langfuse"]
        litellm.failure_callback = ["langfuse"]
        os.environ.setdefault("LANGFUSE_PUBLIC_KEY", settings.langfuse_public_key)
        os.environ.setdefault("LANGFUSE_SECRET_KEY", settings.langfuse_secret_key)
        os.environ.setdefault("LANGFUSE_HOST", settings.langfuse_host)
        return True
    except Exception as exc:
        logger.warning("langfuse_litellm_disabled", reason=str(exc))
        return False


def _read_value(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _fallback_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost when a provider reports none."""
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
    """Normalize token, cost, and reasoning/cache detail for one response."""
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


def init_llm() -> None:
    """Initialize provider credentials and optional observability callbacks."""
    _sync_api_keys()
    try:
        import litellm

        litellm.set_verbose = False  # type: ignore[attr-defined]
    except ImportError:
        return
    if try_enable_litellm_langfuse_callbacks():
        logger.info("litellm_langfuse_registered")


try:
    from langchain_litellm import ChatLiteLLM
except ImportError:
    ChatLiteLLM = Any  # type: ignore[misc, assignment]


def get_llm(agent_name: str, session_id: str = "") -> Any:
    """Return the official LangChain LiteLLM chat model."""
    model_string = f"{llm_settings.provider}/{llm_settings.model}"
    model_kwargs: dict[str, Any] = {
        "timeout": llm_settings.timeout_seconds,
        "num_retries": llm_settings.num_retries,
    }
    if llm_settings.provider == "openrouter":
        model_kwargs["extra_body"] = {"usage": {"include": True}}
    kwargs: dict[str, Any] = {
        "model": model_string,
        "temperature": 0.0,
        "max_tokens": llm_settings.max_tokens_for_agent(agent_name),
        "max_retries": llm_settings.max_retries,
        "model_kwargs": model_kwargs,
        "metadata": {"agent_name": agent_name, "session_id": session_id},
    }
    if llm_settings.api_base:
        kwargs["api_base"] = llm_settings.api_base
    return ChatLiteLLM(**kwargs)


def structured_llm(llm: Any, schema: type) -> Any:
    """Bind a Pydantic schema using the configured structured-output method."""
    method = llm_settings.structured_output_method.strip()
    if not method:
        return llm.with_structured_output(schema)
    try:
        return llm.with_structured_output(schema, method=method)
    except TypeError:
        return llm.with_structured_output(schema)


_llm_semaphore: asyncio.Semaphore | None = None
_llm_semaphore_loop: asyncio.AbstractEventLoop | None = None


def llm_semaphore() -> asyncio.Semaphore:
    """Cap concurrent LLM calls across agent fan-outs."""
    global _llm_semaphore, _llm_semaphore_loop
    running_loop = asyncio.get_running_loop()
    if _llm_semaphore is None or _llm_semaphore_loop is not running_loop:
        _llm_semaphore = asyncio.Semaphore(llm_settings.concurrency)
        _llm_semaphore_loop = running_loop
    return _llm_semaphore
