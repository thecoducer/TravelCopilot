"""Shared agent utilities — logging helpers and token-usage tracking."""

from __future__ import annotations

from typing import Any

import structlog

from app.models.reports import AgentTokenUsage

logger = structlog.get_logger(__name__)


def record_token_usage(
    agent_name: str,
    response: Any,
) -> dict[str, AgentTokenUsage]:
    """Extract token counts from a LangChain response and return a usage dict.

    Returns a partial state update suitable for merging into TripState.
    """
    usage: dict[str, int] = {}
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        meta = response.usage_metadata
        usage = {
            "prompt_tokens": meta.get("input_tokens", 0),
            "completion_tokens": meta.get("output_tokens", 0),
            "total_tokens": meta.get("total_tokens", 0),
        }
    return {
        agent_name: AgentTokenUsage(
            agent_name=agent_name,
            **usage,
        )
    }
