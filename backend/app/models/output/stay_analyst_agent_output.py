"""Structured output models owned by the stay analyst agent."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RankingOutput(BaseModel):
    ranked_indices: list[int] = Field(default_factory=list)
    personalization_reasons: list[str] = Field(default_factory=list)
    rationale: str = ""
