"""Async context for correlating LLM calls with a planning run."""

from __future__ import annotations

from contextvars import ContextVar, Token

_ACTIVE_RUN_ID: ContextVar[str] = ContextVar("active_llm_run_id", default="")


def set_active_llm_run_id(run_id: str) -> Token[str]:
    """Bind a run ID to the current async context."""
    return _ACTIVE_RUN_ID.set(run_id)


def reset_active_llm_run_id(token: Token[str]) -> None:
    """Restore the previous run ID in the current async context."""
    _ACTIVE_RUN_ID.reset(token)


def get_active_llm_run_id() -> str:
    """Return the run ID bound to the current planning run, or an empty string."""
    return _ACTIVE_RUN_ID.get()
