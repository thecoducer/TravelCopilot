"""Clarification interaction models.

These models represent the transient question-answer exchange between the
Orchestrator and the client during trip-planning — they are *not* persistent
user data and therefore live separately from ``user_profile``.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ClarificationPrompt(BaseModel):
    """One question the Orchestrator needs answered before planning."""

    field: str  # e.g. "dates"
    question: str  # e.g. "What dates are you travelling?"
    reason: str  # e.g. "Needed to check availability and prices"
    input_type: str = "text"  # "text" | "date" | "number" | "select"
    options: list[str] = Field(default_factory=list)  # for "select" only
    extracted_value: str | None = None  # LLM's low-confidence guess (shown as placeholder)
