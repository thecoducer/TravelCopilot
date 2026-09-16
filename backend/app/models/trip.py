"""Request models for the trip planning API — zero business logic lives here."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PlanRequest(BaseModel):
    query: str = Field(min_length=3, max_length=2000)
    session_id: str | None = None
    username: str | None = None
    mode: str = "new"  # "new" | "followup" — followup preserves prior session state


class ItineraryUpdateRequest(BaseModel):
    trip_days: list[dict[str, Any]] = Field(default_factory=list)


class ClarifyRequest(BaseModel):
    """Structured answers to the clarification prompts.

    Keys correspond to the ``field`` values from the ``needs_clarification`` SSE event.
    Example: ``{"question": "answer"}``
    """

    request_id: str
    answers: dict[str, str]


class FeedbackRequest(BaseModel):
    rating: int = Field(description="1 = positive, -1 = negative")
    comment: str | None = None
