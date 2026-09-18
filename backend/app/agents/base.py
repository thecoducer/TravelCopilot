"""Shared agent utilities — logging helpers and clarification support."""

from __future__ import annotations

from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.structured_output import StructuredOutputError, invoke_structured
from app.models.clarification import ClarificationPrompt, OptionalClarificationOutput
from app.models.enums import LogEvent
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
        try:
            proposal = await invoke_structured(
                llm,
                OptionalClarificationOutput,
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
                ],
                agent=requester,
            )
        except StructuredOutputError as exc:
            # An optional question is never worth failing the graph for.
            logger.warning(LogEvent.AGENT_DEGRADED, requester=requester, error=str(exc))
            return {}

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
