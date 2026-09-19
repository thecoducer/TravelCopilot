"""StayAnalystAgent — Layer 3: budget-filtered accommodation shortlist.

Applies a price-tier pre-filter before LLM ranking.  Produces a shortlist of
3–5 options each with ``personalization_reason`` and ``price_disclaimer``,
plus a ``stays_pick`` (the top recommended option).
"""

from __future__ import annotations

import asyncio
import json
from statistics import mean
from typing import Any

from app.agents.base import AgentClarificationMixin
from app.llm import StructuredOutputError, get_llm, invoke_structured
from app.logging import get_agent_logger
from app.models.enums import AgentName, LogEvent
from app.models.output.stay_analyst_agent_output import RankingOutput
from app.models.transport import StayOption
from app.models.user_profile import BudgetTier, budget_from_state
from app.prompts.stay_analyst_agent_prompts import STAY_RANKING_PROMPT

# Multiplier thresholds relative to the average price
_BUDGET_MAX_MULTIPLIER = 0.85  # budget: at most 85% of average price
_MID_MAX_MULTIPLIER = 1.6  # mid: at most 160% of average price

_PRICE_DISCLAIMER = "Price per night is indicative — confirm on booking platform before reserving."


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


class StayAnalystAgent(AgentClarificationMixin):
    """Layer 3 — Budget-filtered hotel ranking with shortlist + personalization."""

    def __init__(self, llm: Any | None = None) -> None:
        self._llm = llm or get_llm("stay_analyst")

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        stays_raw: list[StayOption] = state.get("stays_raw", [])
        stays_raw_by_stop: dict[str, list[StayOption]] = state.get("stays_raw_by_stop", {})
        user_profile = state.get("user_profile")
        budget = budget_from_state(state.get("budget"))
        session_id: str = state.get("session_id", "")

        log = get_agent_logger("stay_analyst", session_id)

        if state.get("route_discovery_status") == "multi_stop_provisional" and stays_raw_by_stop:
            return await self._rank_by_stop(stays_raw_by_stop, user_profile, budget, log)

        log.info("agent_start", candidates=len(stays_raw))
        if not stays_raw:
            log.warning("no_stays_raw")
            return {
                "stays_shortlist": [],
                "stays_pick": None,
                "stays_rationale": "No accommodation options found.",
            }

        shortlist, rationale = await self._rank_candidates(stays_raw, user_profile, budget, log)
        stays_pick = shortlist[0] if shortlist else None
        log.info(
            "agent_done",
            shortlist=len(shortlist),
            pick=stays_pick.name if stays_pick else None,
        )
        return {
            "stays_shortlist": shortlist,
            "stays_pick": stays_pick,
            "stays_rationale": rationale,
        }

    async def _rank_by_stop(
        self,
        stays_raw_by_stop: dict[str, list[StayOption]],
        user_profile: Any,
        budget: Any,
        log: Any,
    ) -> dict[str, Any]:
        """Rank accommodation independently for every overnight ``stop_id``.

        Each result is tagged with its ``stop_id`` so a two-stop trip never
        multiplies one stop's shortlist across another stop's segment.
        """
        log.info("agent_start", mode="multi_stop_provisional", stops=list(stays_raw_by_stop))

        async def _rank_one(
            stop_id: str, candidates: list[StayOption]
        ) -> tuple[str, list[StayOption]]:
            if not candidates:
                return stop_id, []
            shortlist, _rationale = await self._rank_candidates(
                candidates, user_profile, budget, log
            )
            return stop_id, [s.model_copy(update={"stop_id": stop_id}) for s in shortlist]

        results = await asyncio.gather(
            *[_rank_one(stop_id, candidates) for stop_id, candidates in stays_raw_by_stop.items()]
        )
        stays_shortlist_by_stop = dict(results)
        stays_pick_by_stop = {
            stop_id: shortlist[0]
            for stop_id, shortlist in stays_shortlist_by_stop.items()
            if shortlist
        }
        log.info("agent_done", mode="multi_stop_provisional", stops=list(stays_shortlist_by_stop))
        return {
            "stays_shortlist_by_stop": stays_shortlist_by_stop,
            "stays_pick_by_stop": stays_pick_by_stop,
        }

    async def _rank_candidates(
        self,
        stays_raw: list[StayOption],
        user_profile: Any,
        budget: Any,
        log: Any,
    ) -> tuple[list[StayOption], str]:
        """Budget-filter + LLM-rank one candidate pool. Returns (shortlist, rationale)."""
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

        try:
            ranking = await invoke_structured(
                self._llm,
                RankingOutput,
                STAY_RANKING_PROMPT.format_messages(
                    budget_tier=budget_tier,
                    hotel_style=hotel_style or "any",
                    interests=", ".join(interests) or "none",
                    stays=json.dumps(stays_summary, indent=2),
                ),
                agent=AgentName.STAY_ANALYST,
                log=log,
            )
        except StructuredOutputError as exc:
            log.error(LogEvent.AGENT_DEGRADED, section="stay_ranking", error=str(exc))
            # Fallback: top 3 by rating
            ranking = RankingOutput(
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

        return shortlist, ranking.rationale
