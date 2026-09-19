"""Shared, bounded clarification requests for LangGraph nodes."""

from __future__ import annotations

from uuid import uuid4

from langgraph.types import interrupt

from app.config import settings
from app.models.clarification import ClarificationPrompt


class ClarificationManager:
    """Validate and dispatch user questions through the graph interrupt boundary."""

    @staticmethod
    def request_optional(
        prompts: list[ClarificationPrompt],
        *,
        requester: str,
        round_number: int,
    ) -> dict[str, str]:
        """Ask bounded, skippable questions proposed by any agent node."""
        optional_prompts = [prompt.model_copy(update={"optional": True}) for prompt in prompts]
        return ClarificationManager.request(
            optional_prompts,
            requester=requester,
            round_number=round_number,
        )

    @staticmethod
    def request(
        prompts: list[ClarificationPrompt],
        *,
        requester: str,
        round_number: int,
    ) -> dict[str, str]:
        """Pause the graph with a bounded request and return validated answers."""
        if not prompts:
            raise ValueError("At least one clarification prompt is required")
        if len(prompts) > settings.clarification_max_questions:
            raise ValueError("Clarification request exceeds the configured question limit")
        if (
            sum(prompt.optional for prompt in prompts)
            > settings.clarification_max_optional_questions
        ):
            raise ValueError("Clarification request exceeds the optional question limit")

        allowed_fields = settings.clarification_allowed_field_names
        for prompt in prompts:
            is_llm_optional = prompt.optional and prompt.field.startswith("optional_")
            if prompt.field not in allowed_fields and not is_llm_optional:
                raise ValueError(f"Unsupported clarification field: {prompt.field}")
            if len(prompt.question) > settings.clarification_max_prompt_length:
                raise ValueError(f"Clarification prompt is too long: {prompt.field}")

        request_id = str(uuid4())
        payload = {
            "request_id": request_id,
            "requester": requester,
            "round": round_number,
            "prompts": [prompt.model_dump() for prompt in prompts],
        }
        answers = interrupt(payload)
        if not isinstance(answers, dict):
            raise ValueError("Clarification answers must be an object")
        fields = {prompt.field for prompt in prompts}
        unknown_fields = set(answers) - fields
        if unknown_fields:
            raise ValueError(
                "Unsupported clarification answers: " + ", ".join(sorted(unknown_fields))
            )
        return {str(key): str(value) for key, value in answers.items()}
