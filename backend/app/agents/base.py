"""Shared agent utilities — logging helpers and token-usage tracking."""

from __future__ import annotations

from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from app.models.clarification import ClarificationPrompt, OptionalClarificationOutput
from app.models.reports import AgentTokenUsage
from app.services.clarification_manager import ClarificationManager

logger = structlog.get_logger(__name__)


class AgentClarificationMixin:
    """Shared optional-clarification capability available to every agent."""

    def request_optional_clarification(
        self,
        prompts: list[ClarificationPrompt],
        *,
        requester: str,
        round_number: int,
    ) -> dict[str, str]:
        """Ask bounded, skippable questions through the central manager."""
        return ClarificationManager.request_optional(
            prompts,
            requester=requester,
            round_number=round_number,
        )

    async def ask_optional_clarification(
        self,
        llm: Any,
        state: dict[str, Any],
        *,
        requester: str,
        round_number: int,
        context: str,
    ) -> dict[str, str]:
        """Let any LLM-backed agent propose and ask bounded optional questions."""
        chain = llm.with_structured_output(OptionalClarificationOutput)
        proposal = await chain.ainvoke(
            [
                SystemMessage(
                    content=(
                        "You may ask up to 3 optional questions to improve the itinerary. "
                        "Use field names beginning with optional_. Ask only for useful, "
                        "trip-scoped preferences. Never ask for required fields, credentials, "
                        "or sensitive personal data. Return an empty prompts list when no "
                        "question is useful. Every prompt must be optional=true."
                    )
                ),
                HumanMessage(content=f"Agent context:\n{context}\nTrip state:\n{state}"),
            ]
        )
        prompts = [prompt for prompt in getattr(proposal, "prompts", []) if prompt.optional]
        if not prompts:
            return {}
        return self.request_optional_clarification(
            prompts,
            requester=requester,
            round_number=round_number,
        )


def request_optional_clarification(
    prompts: list[ClarificationPrompt],
    *,
    requester: str,
    round_number: int,
) -> dict[str, str]:
    """Compatibility helper for agents using function-style access."""
    return ClarificationManager.request_optional(
        prompts, requester=requester, round_number=round_number
    )


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
    response_metadata = getattr(response, "response_metadata", {}) or {}
    latency_ms = response_metadata.get("latency_ms", 0.0)
    return {
        agent_name: AgentTokenUsage(
            agent_name=agent_name,
            latency_ms=float(latency_ms or 0.0),
            **usage,
        )
    }
