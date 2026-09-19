"""Hardened structured-output invocation shared by every LLM-backed agent.

Previously each agent duplicated ``llm.with_structured_output(X)`` followed by a
bare ``except Exception`` that swallowed the failure and returned an empty
fallback. That made three distinct problems indistinguishable — a truncated
completion, a schema the model cannot satisfy, and a provider error — and gave
the caller no way to tell degraded output from real output.

This module centralises that path so failures are typed, logged and retried once
with the validation error fed back to the model.
"""

from __future__ import annotations

from typing import Any

import structlog
from langchain_core.messages import BaseMessage, HumanMessage
from pydantic import BaseModel

from app.llm import extract_llm_call_usage, get_active_llm_run_id, llm_semaphore, structured_llm
from app.llm.config import llm_settings
from app.models.enums import FinishReason, LogEvent
from app.services.usage_service import record_llm_call_usage

logger = structlog.get_logger(__name__)


# Appended to the conversation when a first attempt fails validation, so the
# model repairs its own output instead of the caller silently degrading.
_REPAIR_INSTRUCTION = (
    "Your previous response did not match the required schema.\n"
    "Validation error:\n{error}\n\n"
    "Return the same information again as a single valid object that satisfies "
    "every required field of the schema. Do not add commentary or code fences."
)

_TRUNCATION_INSTRUCTION = (
    "Your previous response was cut off before it was complete. "
    "Return the same information again, but be more concise in every free-text "
    "field so the whole object fits in the response."
)


class StructuredOutputError(RuntimeError):
    """Raised when structured output could not be obtained after every attempt."""

    def __init__(
        self,
        agent: str,
        schema_name: str,
        *,
        attempts: int,
        truncated: bool,
        cause: BaseException | None = None,
    ) -> None:
        self.agent = agent
        self.schema_name = schema_name
        self.attempts = attempts
        self.truncated = truncated
        reason = "output truncated" if truncated else "schema validation failed"
        super().__init__(f"{agent}: {schema_name} {reason} after {attempts} attempt(s)")
        if cause is not None:
            self.__cause__ = cause


def _finish_reason(raw: Any) -> str | None:
    metadata = getattr(raw, "response_metadata", None) or {}
    if not isinstance(metadata, dict):
        return None
    value = metadata.get("finish_reason") or metadata.get("stop_reason")
    return str(value) if value else None


def _was_truncated(raw: Any) -> bool:
    reason = _finish_reason(raw)
    return reason is not None and reason.lower() == FinishReason.LENGTH


def _bind[SchemaT: BaseModel](llm: Any, schema: type[SchemaT]) -> tuple[Any, bool]:
    """Bind the schema, preferring ``include_raw`` so truncation stays visible.

    Returns ``(chain, raw_included)``. Test doubles and older integrations expose
    only ``with_structured_output(schema)``, so the plain form is the fallback.
    """
    method = llm_settings.structured_output_method.strip()
    if method:
        try:
            return llm.with_structured_output(schema, method=method, include_raw=True), True
        except TypeError:
            pass
    try:
        return llm.with_structured_output(schema, include_raw=True), True
    except TypeError:
        return structured_llm(llm, schema), False


def _unpack[SchemaT: BaseModel](
    result: Any, schema: type[SchemaT]
) -> tuple[SchemaT | None, Exception | None, Any]:
    """Normalise both the ``include_raw`` envelope and a bare parsed model."""
    if isinstance(result, dict) and {"parsed", "raw"} <= result.keys():
        parsed = result.get("parsed")
        error = result.get("parsing_error")
        if parsed is not None and not isinstance(parsed, schema):
            parsed = schema.model_validate(parsed)
        return parsed, error, result.get("raw")
    if isinstance(result, schema):
        return result, None, None
    if isinstance(result, dict):
        return schema.model_validate(result), None, None
    return None, TypeError(f"unexpected structured-output result type: {type(result)!r}"), None


async def _track_usage(raw: Any, llm: Any, agent: str, bound_log: Any) -> None:
    """Extract and record one LLM call's usage; never break the agent on failure."""
    if raw is None:
        return
    run_id = get_active_llm_run_id()
    if not run_id:
        return
    try:
        model = llm_settings.model
        usage = extract_llm_call_usage(raw, model)
        bound_log.info(LogEvent.LLM_USAGE_RECORDED, agent=agent, **usage)
        await record_llm_call_usage(run_id, usage)
    except Exception as exc:
        bound_log.warning(LogEvent.LLM_USAGE_TRACKING_FAILED, agent=agent, error=str(exc))


async def invoke_structured[SchemaT: BaseModel](
    llm: Any,
    schema: type[SchemaT],
    messages: list[BaseMessage],
    *,
    agent: str,
    session_id: str = "",
    max_attempts: int | None = None,
    log: Any | None = None,
) -> SchemaT:
    """Invoke ``llm`` for ``schema``, repairing one failed attempt before giving up.

    Raises:
        StructuredOutputError: every attempt failed validation or was truncated.
    """
    bound_log = log or logger.bind(agent=agent, session_id=session_id)
    schema_name = schema.__name__
    attempts = max(1, max_attempts or llm_settings.structured_max_attempts)
    conversation = list(messages)

    last_error: Exception | None = None
    truncated = False

    for attempt in range(1, attempts + 1):
        chain, _raw_included = _bind(llm, schema)
        bound_log.debug(
            LogEvent.LLM_STRUCTURED_START, schema=schema_name, attempt=attempt, attempts=attempts
        )
        try:
            async with llm_semaphore():
                result = await chain.ainvoke(conversation)
            parsed, parsing_error, raw = _unpack(result, schema)
        except Exception as exc:  # provider error or a parser that raises instead of returning
            parsed, parsing_error, raw = None, exc, None
        await _track_usage(raw, llm, agent, bound_log)

        truncated = _was_truncated(raw)
        if truncated:
            bound_log.warning(
                LogEvent.LLM_OUTPUT_TRUNCATED,
                schema=schema_name,
                attempt=attempt,
                finish_reason=_finish_reason(raw),
                max_tokens=llm_settings.max_tokens_for_agent(agent),
            )

        if parsed is not None and parsing_error is None and not truncated:
            bound_log.debug(LogEvent.LLM_STRUCTURED_DONE, schema=schema_name, attempt=attempt)
            return parsed

        last_error = parsing_error or last_error
        if attempt < attempts:
            bound_log.warning(
                LogEvent.LLM_STRUCTURED_RETRY,
                schema=schema_name,
                attempt=attempt,
                truncated=truncated,
                error=str(parsing_error) if parsing_error else None,
            )
            repair = (
                _TRUNCATION_INSTRUCTION
                if truncated
                else _REPAIR_INSTRUCTION.format(error=str(parsing_error))
            )
            conversation = [*messages, HumanMessage(content=repair)]

    bound_log.error(
        LogEvent.LLM_STRUCTURED_FAILED,
        schema=schema_name,
        attempts=attempts,
        truncated=truncated,
        error=str(last_error) if last_error else None,
    )
    raise StructuredOutputError(
        agent, schema_name, attempts=attempts, truncated=truncated, cause=last_error
    )
