"""LLM factory — provider-agnostic via LiteLLM.

Any supported LLM can be swapped in with two env-var changes (zero code changes):

    LLM_PROVIDER=openai     LLM_MODEL=gpt-4o               (default)
    LLM_PROVIDER=anthropic  LLM_MODEL=claude-3-5-sonnet-20241022
    LLM_PROVIDER=gemini     LLM_MODEL=gemini-1.5-pro
    LLM_PROVIDER=ollama     LLM_MODEL=llama3               (local, free)
    LLM_PROVIDER=groq       LLM_MODEL=llama3-70b-8192

How it works:
  - ``LiteLLMChatModel`` wraps ``litellm.acompletion()`` as a LangChain
    ``BaseChatModel``.  Supports ``.with_structured_output(PydanticModel)``
    via LiteLLM's JSON-schema tool-call mode.
  - ``UsageLogger(litellm.CustomLogger)`` fires after every completion and
    writes per-agent token counts to Redis.
  - Langfuse tracing is registered globally via ``litellm.success_callback``.
  - ``get_llm(agent_name, session_id)`` is the single entry point.
"""

from __future__ import annotations

import asyncio
import json
import os
from contextvars import ContextVar, Token
from typing import Any

import structlog

from app.config import settings

logger = structlog.get_logger(__name__)

_HEADROOM_IMPORT_FAILED = False
_ACTIVE_SESSION_ID: ContextVar[str] = ContextVar("active_llm_session_id", default="")


def set_active_llm_session_id(session_id: str) -> Token[str]:
    """Bind a session_id to the current async context for LLM usage logging."""
    return _ACTIVE_SESSION_ID.set(session_id)


def reset_active_llm_session_id(token: Token[str]) -> None:
    """Reset the session_id context binding."""
    _ACTIVE_SESSION_ID.reset(token)


def _effective_session_id(metadata: dict[str, Any]) -> str:
    sid = metadata.get("session_id")
    if isinstance(sid, str) and sid:
        return sid
    return _ACTIVE_SESSION_ID.get()


def _extract_text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(item, str):
                parts.append(item)
            else:
                parts.append(str(item))
        return "\n".join(parts)
    if content is None:
        return ""
    return str(content)


def _estimate_chars(messages: list[dict[str, Any]]) -> int:
    return sum(len(_extract_text_content(m.get("content", ""))) for m in messages)


def _maybe_add_terse_system_note(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not (settings.headroom_enabled and settings.headroom_output_terse_enabled):
        return messages

    terse_note = (
        "Answer tersely. Avoid restating prior context. "
        "Focus only on required outputs and key facts."
    )
    updated = list(messages)
    for i in range(len(updated) - 1, -1, -1):
        if updated[i].get("role") == "system":
            content = _extract_text_content(updated[i].get("content", ""))
            updated[i] = {**updated[i], "content": f"{content}\n\n{terse_note}".strip()}
            return updated

    return [{"role": "system", "content": terse_note}, *updated]


def _maybe_compress_messages(
    messages: list[dict[str, Any]],
    *,
    model: str,
    metadata: dict[str, Any],
    structured: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    telemetry = {
        "enabled": settings.headroom_enabled,
        "applied": False,
        "reason": "disabled",
        "tokens_saved": None,
        "compression_ratio": None,
    }
    if not settings.headroom_enabled:
        return messages, telemetry

    msg_count = len(messages)
    char_count = _estimate_chars(messages)
    if msg_count < settings.headroom_min_messages and char_count < settings.headroom_min_chars:
        telemetry["reason"] = "below_threshold"
        return messages, telemetry

    global _HEADROOM_IMPORT_FAILED
    try:
        from headroom import compress  # type: ignore[import]
    except Exception as exc:
        if not _HEADROOM_IMPORT_FAILED:
            logger.warning("headroom_unavailable", error=str(exc))
            _HEADROOM_IMPORT_FAILED = True
        telemetry["reason"] = "import_failed"
        return messages, telemetry

    try:
        result = compress(messages, model=model)
        compressed = getattr(result, "messages", None)
        if not isinstance(compressed, list) or not compressed:
            telemetry["reason"] = "invalid_result"
            return messages, telemetry

        telemetry["applied"] = True
        telemetry["reason"] = "ok"
        telemetry["tokens_saved"] = getattr(result, "tokens_saved", None)
        telemetry["compression_ratio"] = getattr(result, "compression_ratio", None)

        logger.info(
            "headroom_compress",
            agent=metadata.get("agent_name", "unknown"),
            session_id=metadata.get("session_id", ""),
            structured=structured,
            tokens_saved=telemetry["tokens_saved"],
            compression_ratio=telemetry["compression_ratio"],
        )
        return compressed, telemetry
    except Exception as exc:
        logger.warning(
            "headroom_compress_failed",
            agent=metadata.get("agent_name", "unknown"),
            session_id=metadata.get("session_id", ""),
            structured=structured,
            error=str(exc),
        )
        telemetry["reason"] = "compress_failed"
        return messages, telemetry


# ── Sync provider API keys so LiteLLM can find them ──────────────────────────


def _sync_api_keys() -> None:
    key_map = {
        "OPENAI_API_KEY": settings.openai_api_key,
        "ANTHROPIC_API_KEY": settings.anthropic_api_key,
        "GOOGLE_API_KEY": settings.google_api_key,
        "GROQ_API_KEY": settings.groq_api_key,
        # LiteLLM expects OPENROUTER_API_KEY; the .env uses OPEN_ROUTER_API_KEY
        "OPENROUTER_API_KEY": settings.openrouter_api_key,
    }
    for env_var, value in key_map.items():
        if value and not os.environ.get(env_var):
            os.environ[env_var] = value


_sync_api_keys()


def try_enable_litellm_langfuse_callbacks() -> bool:
    """Enable LiteLLM Langfuse callbacks only when SDK compatibility is confirmed.

    Some langfuse/litellm version combinations raise at request time when
    `success_callback=["langfuse"]` is configured. This guard keeps the app
    functional by disabling those callbacks when compatibility checks fail.
    """
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return False

    try:
        import langfuse  # type: ignore[import]
        import litellm

        # LiteLLM integration expects langfuse.version.__version__.
        if not hasattr(langfuse, "version"):
            logger.warning(
                "langfuse_litellm_disabled",
                reason="langfuse.version missing",
                fallback="callbacks_off",
            )
            return False

        litellm.success_callback = ["langfuse"]
        litellm.failure_callback = ["langfuse"]
        os.environ.setdefault("LANGFUSE_PUBLIC_KEY", settings.langfuse_public_key)
        os.environ.setdefault("LANGFUSE_SECRET_KEY", settings.langfuse_secret_key)
        os.environ.setdefault("LANGFUSE_HOST", settings.langfuse_host)
        return True
    except Exception as exc:
        logger.warning(
            "langfuse_litellm_disabled",
            reason=str(exc),
            fallback="callbacks_off",
        )
        return False


# ── LiteLLM CustomLogger — sync, fired after every completion ────────────────

try:
    import litellm

    class UsageLogger(litellm.CustomLogger):  # type: ignore[misc]
        """Write per-agent token counts to Redis after every LiteLLM call."""

        def log_success_event(
            self,
            kwargs: dict[str, Any],
            response_obj: Any,
            start_time: Any,
            end_time: Any,
        ) -> None:
            try:
                metadata: dict[str, Any] = kwargs.get("metadata") or {}
                agent_name: str = metadata.get("agent_name", "unknown")
                session_id = _effective_session_id(metadata)
                usage = getattr(response_obj, "usage", None)
                if not usage:
                    return
                prompt_t: int = getattr(usage, "prompt_tokens", 0) or 0
                completion_t: int = getattr(usage, "completion_tokens", 0) or 0
                total_t: int = getattr(usage, "total_tokens", prompt_t + completion_t) or 0
                if total_t == 0:
                    return

                headroom_applied = bool(metadata.get("headroom_applied", False))
                headroom_tokens_saved = metadata.get("headroom_tokens_saved")
                headroom_ratio = metadata.get("headroom_compression_ratio")
                try:
                    headroom_tokens_saved_i = int(headroom_tokens_saved or 0)
                except (TypeError, ValueError):
                    headroom_tokens_saved_i = 0
                try:
                    headroom_ratio_f = float(headroom_ratio) if headroom_ratio is not None else 0.0
                except (TypeError, ValueError):
                    headroom_ratio_f = 0.0

                # Fire-and-forget Redis write in a daemon thread
                import threading

                def _write() -> None:
                    async def _aw() -> None:
                        try:
                            from app.services.cache_service import CacheService

                            c = CacheService()
                            k = f"usage:{session_id}:{agent_name}"
                            ex: dict[str, Any] = await c.get(k) or {}
                            ex["prompt_tokens"] = ex.get("prompt_tokens", 0) + prompt_t
                            ex["completion_tokens"] = ex.get("completion_tokens", 0) + completion_t
                            ex["total_tokens"] = ex.get("total_tokens", 0) + total_t
                            ex["calls"] = ex.get("calls", 0) + 1
                            ex["headroom_calls"] = ex.get("headroom_calls", 0) + 1
                            ex["headroom_applied_calls"] = ex.get("headroom_applied_calls", 0) + (
                                1 if headroom_applied else 0
                            )
                            ex["headroom_tokens_saved"] = ex.get("headroom_tokens_saved", 0) + (
                                headroom_tokens_saved_i
                            )
                            ex["headroom_ratio_sum"] = ex.get("headroom_ratio_sum", 0.0) + (
                                headroom_ratio_f
                            )
                            ex["headroom_ratio_count"] = ex.get("headroom_ratio_count", 0) + (
                                1 if headroom_ratio is not None else 0
                            )
                            await c.set(k, ex, ttl=604800)
                        except Exception as ce:
                            logger.warning("usage_cache_failed", agent=agent_name, error=str(ce))

                    asyncio.run(_aw())

                threading.Thread(target=_write, daemon=True).start()
            except Exception as exc:
                logger.warning("usage_logger_error", error=str(exc))

    _usage_logger = UsageLogger()
    litellm.callbacks = [_usage_logger]
    try_enable_litellm_langfuse_callbacks()

except ImportError:
    logger.warning("litellm_not_installed")

    class UsageLogger:  # type: ignore[no-redef]
        pass


# ── LangChain BaseChatModel wrapper around litellm.acompletion() ─────────────

try:
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import (
        AIMessage,
        BaseMessage,
        HumanMessage,
        SystemMessage,
        ToolMessage,
    )
    from langchain_core.outputs import ChatGeneration, ChatResult
    from pydantic import Field

    def _lc_to_litellm(messages: list[BaseMessage]) -> list[dict[str, Any]]:
        """Convert LangChain messages to LiteLLM/OpenAI format."""
        result: list[dict[str, Any]] = []
        for m in messages:
            if isinstance(m, SystemMessage):
                result.append({"role": "system", "content": m.content})
            elif isinstance(m, HumanMessage):
                result.append({"role": "user", "content": m.content})
            elif isinstance(m, AIMessage):
                result.append({"role": "assistant", "content": m.content or ""})
            elif isinstance(m, ToolMessage):
                result.append(
                    {"role": "tool", "content": m.content, "tool_call_id": m.tool_call_id}
                )
            else:
                result.append({"role": "user", "content": str(m.content)})
        return result

    class LiteLLMChatModel(BaseChatModel):
        """Provider-agnostic LangChain chat model via LiteLLM.

        Supports ``.with_structured_output(PydanticModel)`` via JSON schema
        tool-call mode (works with GPT-4o, Claude 3, Gemini 1.5, Llama 3, etc.)
        """

        model: str = Field(default="openai/gpt-4o")
        temperature: float = Field(default=0.0)
        max_retries: int = Field(default=2)
        metadata: dict[str, Any] = Field(default_factory=dict)
        api_base: str = Field(default="")

        @property
        def _llm_type(self) -> str:
            return "litellm"

        def _generate(
            self,
            messages: list[BaseMessage],
            stop: list[str] | None = None,
            run_manager: Any = None,
            **kwargs: Any,
        ) -> ChatResult:
            import litellm as _litellm

            raw_messages = _lc_to_litellm(messages)
            compressed_messages, headroom = _maybe_compress_messages(
                raw_messages,
                model=self.model,
                metadata=self.metadata,
                structured=False,
            )
            request_messages = _maybe_add_terse_system_note(compressed_messages)

            req_metadata = {
                **self.metadata,
                "session_id": _effective_session_id(self.metadata),
                "headroom_enabled": headroom["enabled"],
                "headroom_applied": headroom["applied"],
                "headroom_reason": headroom["reason"],
                "headroom_tokens_saved": headroom["tokens_saved"],
                "headroom_compression_ratio": headroom["compression_ratio"],
            }

            kw: dict[str, Any] = {
                "model": self.model,
                "messages": request_messages,
                "temperature": self.temperature,
                "metadata": req_metadata,
                "num_retries": self.max_retries,
            }
            if self.api_base:
                kw["api_base"] = self.api_base
            if stop:
                kw["stop"] = stop
            kw.update(kwargs)

            response = _litellm.completion(**kw)
            content = response.choices[0].message.content or ""
            ai_msg = AIMessage(content=content)
            return ChatResult(generations=[ChatGeneration(message=ai_msg)])

        async def _agenerate(
            self,
            messages: list[BaseMessage],
            stop: list[str] | None = None,
            run_manager: Any = None,
            **kwargs: Any,
        ) -> ChatResult:
            import litellm as _litellm

            raw_messages = _lc_to_litellm(messages)
            compressed_messages, headroom = _maybe_compress_messages(
                raw_messages,
                model=self.model,
                metadata=self.metadata,
                structured=False,
            )
            request_messages = _maybe_add_terse_system_note(compressed_messages)

            req_metadata = {
                **self.metadata,
                "session_id": _effective_session_id(self.metadata),
                "headroom_enabled": headroom["enabled"],
                "headroom_applied": headroom["applied"],
                "headroom_reason": headroom["reason"],
                "headroom_tokens_saved": headroom["tokens_saved"],
                "headroom_compression_ratio": headroom["compression_ratio"],
            }

            kw: dict[str, Any] = {
                "model": self.model,
                "messages": request_messages,
                "temperature": self.temperature,
                "metadata": req_metadata,
                "num_retries": self.max_retries,
            }
            if self.api_base:
                kw["api_base"] = self.api_base
            if stop:
                kw["stop"] = stop
            kw.update(kwargs)

            response = await _litellm.acompletion(**kw)
            content = response.choices[0].message.content or ""
            ai_msg = AIMessage(content=content)
            return ChatResult(generations=[ChatGeneration(message=ai_msg)])

        def with_structured_output(  # type: ignore[override]
            self,
            schema: Any,
            *,
            include_raw: bool = False,
            method: str = "function_calling",
            **kwargs: Any,
        ) -> Any:
            """Return a Runnable chain that parses structured JSON output.

            Uses LiteLLM's tool-calling support which works with all major
            providers that support function/tool calling (OpenAI, Anthropic,
            Gemini, Llama 3, etc.).
            """

            is_pydantic = hasattr(schema, "model_json_schema")
            schema_dict: dict[str, Any] = schema.model_json_schema() if is_pydantic else schema
            schema_name = getattr(schema, "__name__", "output")

            # Remove 'title' from the top-level schema to avoid provider rejections
            schema_dict.pop("title", None)

            tool_def = {
                "type": "function",
                "function": {
                    "name": schema_name,
                    "description": f"Extract {schema_name} fields from the context",
                    "parameters": schema_dict,
                },
            }

            def _invoke_with_tools(messages: list[BaseMessage]) -> Any:
                import litellm as _litellm

                raw_messages = _lc_to_litellm(messages)
                compressed_messages, headroom = _maybe_compress_messages(
                    raw_messages,
                    model=self.model,
                    metadata=self.metadata,
                    structured=True,
                )

                req_metadata = {
                    **self.metadata,
                    "session_id": _effective_session_id(self.metadata),
                    "headroom_enabled": headroom["enabled"],
                    "headroom_applied": headroom["applied"],
                    "headroom_reason": headroom["reason"],
                    "headroom_tokens_saved": headroom["tokens_saved"],
                    "headroom_compression_ratio": headroom["compression_ratio"],
                }

                def _completion(request_messages: list[dict[str, Any]]) -> Any:
                    kw: dict[str, Any] = {
                        "model": self.model,
                        "messages": request_messages,
                        "temperature": self.temperature,
                        "metadata": req_metadata,
                        "tools": [tool_def],
                        "tool_choice": {"type": "function", "function": {"name": schema_name}},
                        "num_retries": self.max_retries,
                    }
                    if self.api_base:
                        kw["api_base"] = self.api_base
                    return _litellm.completion(**kw)

                try:
                    response = _completion(compressed_messages)
                except Exception:
                    if not headroom.get("applied"):
                        raise
                    logger.warning(
                        "headroom_structured_retry_uncompressed",
                        agent=self.metadata.get("agent_name", "unknown"),
                        session_id=self.metadata.get("session_id", ""),
                        reason="completion_failed",
                    )
                    response = _completion(raw_messages)

                choice = response.choices[0]

                # Extract JSON from tool_calls or content
                raw_json: str = ""
                if hasattr(choice.message, "tool_calls") and choice.message.tool_calls:
                    raw_json = choice.message.tool_calls[0].function.arguments
                else:
                    raw_json = choice.message.content or "{}"

                try:
                    parsed: dict[str, Any] = json.loads(raw_json)
                except json.JSONDecodeError:
                    if not headroom.get("applied"):
                        raise
                    logger.warning(
                        "headroom_structured_retry_uncompressed",
                        agent=self.metadata.get("agent_name", "unknown"),
                        session_id=self.metadata.get("session_id", ""),
                        reason="json_decode_failed",
                    )
                    response = _completion(raw_messages)
                    choice = response.choices[0]
                    if hasattr(choice.message, "tool_calls") and choice.message.tool_calls:
                        raw_json = choice.message.tool_calls[0].function.arguments
                    else:
                        raw_json = choice.message.content or "{}"
                    parsed = json.loads(raw_json)

                if is_pydantic:
                    return schema.model_validate(parsed)
                return parsed

            class _StructuredChain:
                def invoke(self, messages: list[BaseMessage]) -> Any:
                    return _invoke_with_tools(messages)

                async def ainvoke(self, messages: list[BaseMessage]) -> Any:
                    # Run the sync version in a thread executor for async contexts
                    loop = asyncio.get_event_loop()
                    return await loop.run_in_executor(None, self.invoke, messages)

            return _StructuredChain()

except ImportError as e:
    logger.warning("langchain_core_missing", error=str(e))

    class LiteLLMChatModel:  # type: ignore[no-redef]
        pass


# ── Public factory ────────────────────────────────────────────────────────────


def get_llm(agent_name: str, session_id: str = "") -> LiteLLMChatModel:
    """Return a provider-agnostic LangChain model via LiteLLM.

    The model string is ``"{llm_provider}/{llm_model}"`` — e.g.:
      - ``"openai/gpt-4o"``
      - ``"anthropic/claude-3-5-sonnet-20241022"``
      - ``"gemini/gemini-1.5-pro"``
      - ``"ollama/llama3"``

    Tests inject a fake LLM directly into agents via ``build_graph(llm=...)``,
    so this function is never called during test execution.
    """
    if not any(
        [
            settings.openai_api_key,
            settings.anthropic_api_key,
            settings.google_api_key,
            settings.groq_api_key,
            settings.llm_api_base,  # local model — no key needed
        ]
    ):
        logger.warning(
            "llm_no_api_key",
            provider=settings.llm_provider,
            agent=agent_name,
            hint="Set the appropriate API key in .env (e.g. OPENAI_API_KEY)",
        )

    model_string = f"{settings.llm_provider}/{settings.llm_model}"

    return LiteLLMChatModel(
        model=model_string,
        temperature=0.0,
        max_retries=2,
        metadata={"agent_name": agent_name, "session_id": session_id},
        api_base=settings.llm_api_base,
    )
