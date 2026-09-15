"""Provider-agnostic LangChain chat model factory and usage telemetry."""

from __future__ import annotations

import asyncio
import os
import queue
import threading
from collections.abc import Mapping
from contextvars import ContextVar, Token
from datetime import datetime
from typing import Any

import structlog

from app.config import settings

logger = structlog.get_logger(__name__)
_ACTIVE_SESSION_ID: ContextVar[str] = ContextVar("active_llm_session_id", default="")
_usage_queue: queue.Queue[tuple[str, str, dict[str, int | float]]] = queue.Queue()
_usage_worker_started = False
_usage_worker_lock = threading.Lock()


def set_active_llm_session_id(session_id: str) -> Token[str]:
    """Bind a session ID to the current async context."""
    return _ACTIVE_SESSION_ID.set(session_id)


def reset_active_llm_session_id(token: Token[str]) -> None:
    """Restore the previous session ID context."""
    _ACTIVE_SESSION_ID.reset(token)


def _effective_session_id(metadata: dict[str, Any]) -> str:
    session_id = metadata.get("session_id")
    if isinstance(session_id, str) and session_id:
        return session_id
    return _ACTIVE_SESSION_ID.get()


def _sync_api_keys() -> None:
    key_map = {
        "OPENAI_API_KEY": settings.openai_api_key,
        "ANTHROPIC_API_KEY": settings.anthropic_api_key,
        "GOOGLE_API_KEY": settings.google_api_key,
        "GROQ_API_KEY": settings.groq_api_key,
        "OPENROUTER_API_KEY": settings.openrouter_api_key,
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


async def _write_usage(agent_name: str, session_id: str, usage: dict[str, int | float]) -> None:
    from app.services.cache_service import CacheService

    cache = CacheService()
    try:
        key = cache.usage_key(session_id, agent_name)
        existing = await cache.get(key) or {}
        for field, value in usage.items():
            existing[field] = existing.get(field, 0) + value
        existing["calls"] = existing.get("calls", 0) + 1
        await cache.set(key, existing, ttl=604800)
    finally:
        await cache.close()


async def _usage_worker() -> None:
    while True:
        agent_name, session_id, usage = await asyncio.to_thread(_usage_queue.get)
        try:
            await _write_usage(agent_name, session_id, usage)
        except Exception as exc:
            logger.warning("usage_cache_failed", agent=agent_name, error=str(exc))
        finally:
            _usage_queue.task_done()


def _ensure_usage_worker() -> None:
    global _usage_worker_started
    with _usage_worker_lock:
        if _usage_worker_started:
            return

        def run() -> None:
            asyncio.run(_usage_worker())

        threading.Thread(target=run, name="llm-usage-worker", daemon=True).start()
        _usage_worker_started = True


def _latency_ms(start_time: Any, end_time: Any) -> float:
    if isinstance(start_time, datetime) and isinstance(end_time, datetime):
        return max((end_time - start_time).total_seconds() * 1000, 0.0)
    return 0.0


def _read_value(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def extract_llm_usage(
    response_obj: Any, kwargs: Mapping[str, Any] | None = None
) -> dict[str, int | float]:
    """Normalize token and cost fields from LiteLLM and LangChain response shapes."""
    metadata = _read_value(response_obj, "response_metadata", {}) or {}
    hidden_params = _read_value(response_obj, "_hidden_params", {}) or {}
    callback_kwargs = kwargs or {}
    usage_candidates = (
        _read_value(response_obj, "usage"),
        _read_value(response_obj, "usage_metadata"),
        _read_value(metadata, "token_usage"),
        _read_value(metadata, "usage"),
    )
    prompt_tokens = completion_tokens = total_tokens = 0
    for candidate in usage_candidates:
        if not candidate:
            continue
        prompt_tokens = int(
            _read_value(candidate, "prompt_tokens", _read_value(candidate, "input_tokens", 0)) or 0
        )
        completion_tokens = int(
            _read_value(candidate, "completion_tokens", _read_value(candidate, "output_tokens", 0))
            or 0
        )
        total_tokens = int(
            _read_value(candidate, "total_tokens", prompt_tokens + completion_tokens)
            or prompt_tokens + completion_tokens
        )
        if prompt_tokens or completion_tokens or total_tokens:
            break

    cost = 0.0
    for source in (hidden_params, metadata, callback_kwargs):
        for key in ("response_cost", "cost_usd", "total_cost"):
            value = _read_value(source, key)
            if value is not None:
                cost = float(value or 0.0)
                break
        if cost:
            break

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "cost_usd": cost,
    }


async def flush_usage_events() -> None:
    """Wait for callback events already queued by LiteLLM to reach Redis."""
    try:
        await asyncio.wait_for(asyncio.to_thread(_usage_queue.join), timeout=2.0)
    except TimeoutError:
        logger.warning("usage_queue_flush_timeout")


try:
    import litellm

    class UsageLogger(litellm.CustomLogger):  # type: ignore[name-defined, misc]
        """Aggregate provider usage by session and agent in Redis."""

        def log_success_event(
            self,
            kwargs: dict[str, Any],
            response_obj: Any,
            start_time: Any,
            end_time: Any,
        ) -> None:
            metadata = kwargs.get("metadata") or {}
            agent_name = str(metadata.get("agent_name", "unknown"))
            session_id = _effective_session_id(metadata)
            if not session_id:
                return
            usage = extract_llm_usage(response_obj, kwargs)
            _ensure_usage_worker()
            _usage_queue.put(
                (
                    agent_name,
                    session_id,
                    {
                        "prompt_tokens": int(usage["prompt_tokens"]),
                        "completion_tokens": int(usage["completion_tokens"]),
                        "total_tokens": int(usage["total_tokens"]),
                        "cost_usd": float(usage["cost_usd"]),
                        "latency_ms": _latency_ms(start_time, end_time),
                    },
                )
            )

    _usage_logger = UsageLogger()
except ImportError:
    logger.warning("litellm_not_installed")

    class UsageLogger:  # type: ignore[no-redef]
        """Fallback marker when LiteLLM is unavailable."""


def init_llm() -> None:
    """Initialize provider credentials and optional global callbacks."""
    _sync_api_keys()
    try:
        import litellm

        litellm.callbacks = [_usage_logger]
        litellm.set_verbose = False  # type: ignore[attr-defined]
    except (ImportError, NameError):
        return
    if try_enable_litellm_langfuse_callbacks():
        logger.info("litellm_langfuse_registered")


try:
    from langchain_litellm import ChatLiteLLM
except ImportError:
    ChatLiteLLM = Any  # type: ignore[misc, assignment]


def get_llm(agent_name: str, session_id: str = "") -> Any:
    """Return the official LangChain LiteLLM chat model."""
    model_string = f"{settings.llm_provider}/{settings.llm_model}"
    kwargs: dict[str, Any] = {
        "model": model_string,
        "temperature": 0.0,
        "metadata": {"agent_name": agent_name, "session_id": session_id},
    }
    if settings.llm_api_base:
        kwargs["api_base"] = settings.llm_api_base
    return ChatLiteLLM(**kwargs)
