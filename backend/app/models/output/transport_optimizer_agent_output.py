"""Structured output models owned by the transport optimizer agent."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.transport import TransportRecommendation


class OptimiserOutput(BaseModel):
    recommended: TransportRecommendation
    alternatives: list[TransportRecommendation] = Field(default_factory=list)


class LegRecommendation(BaseModel):
    leg_id: str
    recommendation: TransportRecommendation | None = None
    no_result: bool = False
