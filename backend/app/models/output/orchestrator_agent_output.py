"""Structured query-parsing output models owned by the orchestrator agent."""

from __future__ import annotations

from pydantic import BaseModel, Field


class FieldConfidence(BaseModel):
    value: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ParsedQuery(BaseModel):
    """Structured output from the orchestrator's LLM call."""

    source: FieldConfidence = Field(
        default_factory=lambda: FieldConfidence(value=None, confidence=0.0)
    )
    destination: FieldConfidence = Field(
        default_factory=lambda: FieldConfidence(value=None, confidence=0.0)
    )
    departure_date: str | None = Field(
        default=None, description="ISO-8601 departure date, null if not mentioned"
    )
    return_date: str | None = Field(
        default=None,
        description=("ISO-8601 return/end date if explicitly mentioned, otherwise null"),
    )
    trip_days: int | None = Field(
        default=None,
        ge=1,
        description="Total duration of the trip in days (e.g. 6 for 'for 6 days', 7 for '1 week')",
    )
    trip_days_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    travelers: FieldConfidence = Field(
        default_factory=lambda: FieldConfidence(value=None, confidence=0.0)
    )
    budget_tier: str | None = Field(
        default=None, description="budget | mid | luxury; null if not specified"
    )
    interests: list[str] = Field(default_factory=list)
    is_international: bool | None = Field(
        default=None,
        description=(
            "True for cross-border travel, false for same-country travel, "
            "null when geography is ambiguous"
        ),
    )
    self_drive_intent: bool = False
    dates_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source_country: str | None = Field(
        default=None,
        description="Country of the departure city, null when it cannot be determined",
    )
    destination_country: str | None = Field(
        default=None,
        description="Country of the destination, null when it cannot be determined",
    )
