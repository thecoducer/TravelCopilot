"""Structured output models owned by the reviews agent."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.enums import Sentiment


class PlaceSummary(BaseModel):
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)
    sentiment: Sentiment = Sentiment.UNKNOWN
