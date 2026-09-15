"""TransportOptimizerAgent — Layer 3: multi-modal route reasoning.

Applies a budget pre-filter before LLM reasoning so that budget users never
see premium/business-class options.  Produces both the recommended route and
up to 2 budget-filtered alternatives.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.llm import get_llm
from app.logging import get_agent_logger
from app.models.stops import RouteLegPlan
from app.models.transport import TransportRecommendation
from app.models.user_profile import budget_from_state
from app.tools.factory import ToolFactory

# Seat classes considered "premium" — excluded for budget tier
_PREMIUM_CLASSES = frozenset(["business", "first", "premium economy", "premium"])

_SYSTEM_PROMPT = """\
You are a transport planning expert. Analyse the route options and produce:
1. The single best recommended route.
2. Two alternative routes (different trade-offs: one faster, one cheaper).

Rules:
- All options MUST be budget-filtered (no premium/business class unless tier is luxury).
- ``personalization_reason`` must reference the traveller's budget tier.
- ``non_obvious_insight`` set ONLY when a cheaper option saves > 15% vs the expensive one.
- ``route_waypoints`` must include at least 2 lat/lng entries (origin + destination).
- Each ``RouteLeg`` must have a non-empty ``price_disclaimer`` and a valid ``price_cached_at``.
- ``alternatives`` is a JSON array with the same TransportRecommendation structure.
"""


class _OptimiserOutput(BaseModel):
    recommended: TransportRecommendation
    alternatives: list[TransportRecommendation] = Field(default_factory=list)


class _LegRecommendation(BaseModel):
    leg_id: str
    recommendation: TransportRecommendation
    no_result: bool = False


class _MultiLegOptimiserOutput(BaseModel):
    per_leg: list[_LegRecommendation] = Field(default_factory=list)
    aggregate: TransportRecommendation


_LEG_SYSTEM_PROMPT = """\
You are a transport planning expert. For every route leg listed below, pick the \
best available option and explain your reasoning, then produce one route-wide \
aggregate summary across all legs.

Rules:
- All options MUST be budget-filtered (no premium/business class unless tier is luxury).
- Each leg's ``personalization_reason`` must reference the traveller's budget tier.
- Each ``RouteLeg`` must have a non-empty ``price_disclaimer`` and a valid ``price_cached_at``.
- If a leg has no viable options, set ``no_result=true`` and leave its recommended_legs empty.
- ``aggregate`` summarises the whole route (all legs combined) — total cost and duration.
- Return exactly one ``per_leg`` entry for every ``leg_id`` provided.
"""


def _trim_leg(leg: dict[str, Any]) -> dict[str, Any]:
    return {
        "operator": leg.get("operator", leg.get("airline", {}).get("name", "")),
        "duration_minutes": leg.get("total_duration", leg.get("duration", 0)),
        "price": leg.get("price", 0),
        "stops": leg.get("stops", len(leg.get("layovers", []))),
        "departure": leg.get("departure_airport", {}).get("time", ""),
        "seat_class": leg.get("travel_class", "economy"),
    }


def _patch_legs(
    rec: TransportRecommendation, now: datetime, disclaimer: str
) -> TransportRecommendation:
    patched = [
        leg.model_copy(
            update={
                "price_cached_at": getattr(leg, "price_cached_at", None) or now,
                "price_disclaimer": leg.price_disclaimer or disclaimer,
            }
        )
        for leg in rec.recommended_legs
    ]
    return rec.model_copy(update={"recommended_legs": patched})


def _is_premium(leg: dict[str, Any]) -> bool:
    """Return True if the leg uses a premium seat class."""
    seat = str(leg.get("travel_class", leg.get("seat_class", ""))).lower()
    return any(p in seat for p in _PREMIUM_CLASSES)


def _budget_filter(legs_raw: dict[str, list[Any]], budget_tier: str) -> dict[str, list[Any]]:
    """Remove premium options from legs_raw for non-luxury tiers."""
    if budget_tier == "luxury":
        return legs_raw
    return {
        key: [leg for leg in options if not _is_premium(leg)] for key, options in legs_raw.items()
    }


class TransportOptimizerAgent:
    """Layer 3 — Budget-filtered route selection + alternatives."""

    def __init__(
        self,
        tool_factory: ToolFactory | None = None,
        llm: Any | None = None,
    ) -> None:
        self._llm = llm or get_llm("transport_optimizer")

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        source: str = state.get("source", "")
        destination: str = state.get("destination", "")
        legs_raw: dict[str, list[Any]] = state.get("transport_legs_raw", {})
        dates = state.get("dates")
        budget = budget_from_state(state.get("budget"))
        travelers: int = state.get("travelers", 1)
        session_id: str = state.get("session_id", "")

        log = get_agent_logger(
            "transport_optimizer", session_id, source=source, destination=destination
        )
        log.info("agent_start", route_options=list(legs_raw.keys()))

        route_legs: dict[str, RouteLegPlan] = state.get("route_legs", {})
        legs_raw_by_leg: dict[str, list[Any]] = state.get("transport_legs_raw_by_leg", {})
        if state.get("route_discovery_status") == "multi_stop_provisional" and legs_raw_by_leg:
            return await self._optimize_route_legs(
                route_legs, legs_raw_by_leg, budget, travelers, state.get("route_version", 0), log
            )

        if not legs_raw:
            log.warning("no_legs_raw")
            return {"transport_recommendation": None, "transport_alternatives": []}

        budget_tier = budget.tier if budget else "mid"

        # ── Budget pre-filter ────────────────────────────────────────────
        filtered_legs = _budget_filter(legs_raw, budget_tier)

        trip_days = dates.trip_days if dates else 3

        legs_summary = {k: [_trim_leg(leg) for leg in v[:4]] for k, v in filtered_legs.items()}

        chain = self._llm.with_structured_output(_OptimiserOutput)
        try:
            output: _OptimiserOutput = await chain.ainvoke(
                [
                    SystemMessage(content=_SYSTEM_PROMPT),
                    HumanMessage(
                        content=(
                            f"Source: {source}\nDestination: {destination}\n"
                            f"Trip days: {trip_days}\nTravelers: {travelers}\n"
                            f"Budget tier: {budget_tier}\n\n"
                            f"Route options (JSON):\n{json.dumps(legs_summary, indent=2)}"
                        )
                    ),
                ]
            )
        except Exception as exc:
            log.error("llm_failed", error=str(exc))
            return {"transport_recommendation": None, "transport_alternatives": []}

        now = datetime.now(tz=UTC)
        disclaimer = "Price is indicative — verify before booking."

        recommendation = _patch_legs(output.recommended, now, disclaimer)
        alternatives = [_patch_legs(a, now, disclaimer) for a in output.alternatives[:2]]

        log.info("agent_done", total_cost=recommendation.total_cost, alternatives=len(alternatives))
        return {
            "transport_recommendation": recommendation,
            "transport_alternatives": alternatives,
        }

    async def _optimize_route_legs(
        self,
        route_legs: dict[str, RouteLegPlan],
        legs_raw_by_leg: dict[str, list[Any]],
        budget: Any,
        travelers: int,
        route_version: int,
        log: Any,
    ) -> dict[str, Any]:
        """Return one recommendation per discovered ``leg_id`` plus a route-wide aggregate.

        Unavailable supply is represented explicitly (``no_result=True``) rather
        than dropping the leg — every leg_id discovered by StopsDiscoveryAgent
        is guaranteed a recommendation record.
        """
        budget_tier = budget.tier if budget else "mid"
        filtered = _budget_filter(legs_raw_by_leg, budget_tier)

        legs_summary = {
            leg_id: {
                "leg_type": str(route_legs[leg_id].leg_type) if leg_id in route_legs else "unknown",
                "planned_date": (
                    route_legs[leg_id].planned_departure_date.isoformat()
                    if leg_id in route_legs
                    else None
                ),
                "options": [_trim_leg(o) for o in options[:4]],
            }
            for leg_id, options in filtered.items()
        }

        chain = self._llm.with_structured_output(_MultiLegOptimiserOutput)
        try:
            output: _MultiLegOptimiserOutput = await chain.ainvoke(
                [
                    SystemMessage(content=_LEG_SYSTEM_PROMPT),
                    HumanMessage(
                        content=(
                            f"Travelers: {travelers}\nBudget tier: {budget_tier}\n\n"
                            f"Route legs (JSON):\n{json.dumps(legs_summary, indent=2)}"
                        )
                    ),
                ]
            )
        except Exception as exc:
            log.error("llm_failed_multi_leg", error=str(exc))
            return {
                "transport_recommendation_by_leg": {},
                "transport_recommendation": None,
                "transport_alternatives": [],
            }

        now = datetime.now(tz=UTC)
        disclaimer = "Price is indicative — verify before booking."

        per_leg: dict[str, TransportRecommendation] = {}
        for item in output.per_leg:
            rec = _patch_legs(item.recommendation, now, disclaimer)
            per_leg[item.leg_id] = rec.model_copy(
                update={
                    "leg_id": item.leg_id,
                    "route_version": route_version,
                    "no_result": item.no_result,
                }
            )

        # Deterministic coverage guarantee — a leg the LLM omitted still gets an
        # explicit no-result record rather than silently disappearing.
        for leg_id in legs_raw_by_leg:
            if leg_id in per_leg:
                continue
            per_leg[leg_id] = TransportRecommendation(
                recommended_legs=[],
                total_cost=0.0,
                total_duration_minutes=0,
                currency_code="INR",
                rationale="No transport options found for this leg.",
                personalization_reason="",
                leg_id=leg_id,
                route_version=route_version,
                no_result=True,
            )

        aggregate = _patch_legs(output.aggregate, now, disclaimer)
        log.info("agent_done", mode="multi_stop_provisional", legs=list(per_leg.keys()))
        return {
            "transport_recommendation_by_leg": per_leg,
            "transport_recommendation": aggregate,
            "transport_alternatives": [],
        }
