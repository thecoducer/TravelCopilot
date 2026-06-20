"""StayAnalystAgent — Layer 3: budget-filtered accommodation shortlist.

Applies a price-tier pre-filter before LLM ranking.  Produces a shortlist of
3–5 options each with ``personalization_reason`` and ``price_disclaimer``,
plus a ``stays_pick`` (the top recommended option).
"""

from __future__ import annotations

import json
from statistics import mean
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.llm import get_llm
from app.models.transport import StayOption
from app.models.user_profile import BudgetTier

logger = structlog.get_logger(__name__)

# Multiplier thresholds relative to the average price
_BUDGET_MAX_MULTIPLIER = 0.85  # budget: at most 85% of average price
_MID_MAX_MULTIPLIER = 1.6  # mid: at most 160% of average price

_PRICE_DISCLAIMER = "Price per night is indicative — confirm on booking platform before reserving."

_SYSTEM_PROMPT = """\
You are a hotel selection expert. Given the pre-filtered hotel list, rank the top 3–5 options
and explain your reasoning for each.

Output:
- ``ranked_indices``: ordered list of 0-based indices (best first, max 5)
- ``personalization_reasons``: parallel list — one sentence per hotel explaining alignment with
  the traveller's preferences; must reference at least one specific preference
- ``rationale``: 2–4 sentence summary of why the top pick was chosen

Rules:
- Budget tier "budget": prioritise price/value ratio
- Budget tier "luxury": prioritise rating, brand, amenities
- Budget tier "mid": balance price, rating, location
"""


class _RankingOutput(BaseModel):
    ranked_indices: list[int] = Field(default_factory=list)
    personalization_reasons: list[str] = Field(default_factory=list)
    rationale: str = ""


def _budget_filter(stays: list[StayOption], budget_tier: str) -> list[StayOption]:
    """Remove hotels incompatible with the budget tier."""
    if not stays:
        return stays
    prices = [s.price_per_night for s in stays if s.price_per_night > 0]
    if not prices:
        return stays
    avg = mean(prices)
    if budget_tier == BudgetTier.budget:
        return [s for s in stays if s.price_per_night <= avg * _BUDGET_MAX_MULTIPLIER] or stays
    if budget_tier == BudgetTier.mid:
        return [s for s in stays if s.price_per_night <= avg * _MID_MAX_MULTIPLIER] or stays
    # luxury — no upper cap; exclude very cheap options
    return [s for s in stays if s.price_per_night >= avg * 0.5] or stays


class StayAnalystAgent:
    """Layer 3 — Budget-filtered hotel ranking with shortlist + personalization."""

    def __init__(self, llm: object | None = None) -> None:
        self._llm = llm or get_llm("stay_analyst")

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        stays_raw: list[StayOption] = state.get("stays_raw", [])
        user_profile = state.get("user_profile")
        budget = state.get("budget")
        session_id: str = state.get("session_id", "")

        log = logger.bind(agent="stay_analyst", session_id=session_id)
        log.info("agent_start", candidates=len(stays_raw))

        if not stays_raw:
            log.warning("no_stays_raw")
            return {
                "stays_shortlist": [],
                "stays_pick": None,
                "stays_rationale": "No accommodation options found.",
            }

        budget_tier = str(budget.tier) if budget else "mid"
        hotel_style = user_profile.hotel_style if user_profile else None
        interests = user_profile.interests if user_profile else []

        # ── Budget pre-filter ────────────────────────────────────────────
        filtered = _budget_filter(stays_raw, budget_tier)
        # Keep at most 10 for LLM context
        candidates = filtered[:10]

        stays_summary = [
            {
                "index": i,
                "name": s.name,
                "price_per_night": s.price_per_night,
                "currency": s.currency_code,
                "rating": s.rating,
                "reviews": s.review_count,
                "amenities": s.amenities[:6],
                "address": s.address,
            }
            for i, s in enumerate(candidates)
        ]

        chain = self._llm.with_structured_output(_RankingOutput)  # type: ignore[union-attr]
        try:
            ranking: _RankingOutput = chain.invoke(
                [
                    SystemMessage(content=_SYSTEM_PROMPT),
                    HumanMessage(
                        content=(
                            f"Budget tier: {budget_tier}\n"
                            f"Preferred hotel style: {hotel_style or 'any'}\n"
                            f"Interests: {', '.join(interests) or 'none'}\n\n"
                            f"Hotels (JSON):\n{json.dumps(stays_summary, indent=2)}"
                        )
                    ),
                ]
            )
        except Exception as exc:
            log.error("llm_failed", error=str(exc))
            # Fallback: top 3 by rating
            ranking = _RankingOutput(
                ranked_indices=list(range(min(3, len(candidates)))),
                personalization_reasons=["Best available option"] * min(3, len(candidates)),
                rationale="Ranked by rating (fallback).",
            )

        # Build shortlist with personalization_reason + price_disclaimer
        shortlist: list[StayOption] = []
        for rank, idx in enumerate(ranking.ranked_indices[:5]):
            if idx >= len(candidates):
                continue
            reason = (
                ranking.personalization_reasons[rank]
                if rank < len(ranking.personalization_reasons)
                else "Matches your preferences"
            )
            shortlist.append(
                candidates[idx].model_copy(
                    update={
                        "personalization_reason": reason,
                        "price_disclaimer": _PRICE_DISCLAIMER,
                    }
                )
            )

        if not shortlist:
            shortlist = [
                s.model_copy(
                    update={
                        "personalization_reason": "Best available option",
                        "price_disclaimer": _PRICE_DISCLAIMER,
                    }
                )
                for s in candidates[:3]
            ]

        stays_pick = shortlist[0] if shortlist else None
        log.info(
            "agent_done",
            shortlist=len(shortlist),
            pick=stays_pick.name if stays_pick else None,
        )
        return {
            "stays_shortlist": shortlist,
            "stays_pick": stays_pick,
            "stays_rationale": ranking.rationale,
        }
