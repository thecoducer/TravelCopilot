"""Structured output models owned by the budget planner agent."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DestinationCostEstimate(BaseModel):
    """LLM-estimated daily per-person cost for food and activities."""

    daily_food_per_person: float = Field(
        default=0.0,
        description="Estimated daily food/dining cost per person in local currency.",
    )
    daily_activity_per_person: float = Field(
        default=0.0,
        description="Estimated daily activity/sightseeing cost per person in local currency.",
    )
    rationale: str = Field(
        default="",
        description="Brief explanation of estimate based on destination pricing and budget tier.",
    )


class CostSavingTips(BaseModel):
    """Structured output schema for cost-saving tips."""

    tips: list[str] = Field(default_factory=list)
