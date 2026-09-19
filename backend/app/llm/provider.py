"""Provider setup and chat-model construction."""

from __future__ import annotations

import os
from typing import Any

import structlog

from app.config import settings
from app.llm.config import llm_settings

logger = structlog.get_logger(__name__)

try:
    from langchain_litellm import ChatLiteLLM
except ImportError:
    ChatLiteLLM = Any  # type: ignore[misc, assignment]


def _sync_api_keys() -> None:
    """Copy configured provider keys into the environment when absent."""
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


def get_llm(agent_name: str, session_id: str = "") -> Any:
    """Return the configured LangChain LiteLLM chat model for an agent."""
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
