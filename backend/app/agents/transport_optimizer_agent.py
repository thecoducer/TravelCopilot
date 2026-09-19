"""TransportOptimizerAgent — Layer 3: multi-modal route reasoning.

Applies a budget pre-filter before LLM reasoning so that budget users never
see premium/business-class options.  Produces both the recommended route and
up to 2 budget-filtered alternatives.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.agents.base import AgentClarificationMixin
from app.agents.structured_output import StructuredOutputError, invoke_structured
from app.llm import get_llm
from app.llm.config import llm_settings
from app.logging import get_agent_logger
from app.models.enums import AgentName, LogEvent
from app.models.stops import RouteLegPlan
from app.models.transport import TransportRecommendation
from app.models.user_profile import budget_from_state
from app.services.currency_service import resolve_from_state
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
    # Optional so a no-result leg is expressible: the prompt permits skipping the
    # recommendation, and a required field would reject the model's own valid answer.
    recommendation: TransportRecommendation | None = None
    no_result: bool = False


_LEG_SYSTEM_PROMPT = """\
You are a transport planning expert. Pick the best available option for the single \
route leg below and explain your reasoning.

Rules:
- All options MUST be budget-filtered (no premium/business class unless tier is luxury).
- ``personalization_reason`` must reference the traveller's budget tier.
- Express every cost in the currency given, and set ``currency_code`` to it.
- If the leg has no viable option, set ``no_result=true`` and omit ``recommendation``.
- Never invent a duration or price that is not present in the supplied options.
"""

# Google Routes returns durations as a protobuf duration string ("18543s").
_ISO_SECONDS_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*s\s*$", re.IGNORECASE)


def _duration_to_minutes(value: object) -> float | None:
    """Normalise a provider duration to minutes, or None when it is unusable.

    Returning None rather than 0 matters: a zero-minute leg reads as an instant
    free transfer, and the model then reports it as "invalid data" or picks it.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    if isinstance(value, str):
        match = _ISO_SECONDS_PATTERN.match(value)
        if match:
            seconds = float(match.group(1))
            return round(seconds / 60.0, 2) if seconds > 0 else None
        try:
            parsed = float(value.strip())
        except ValueError:
            return None
        return parsed if parsed > 0 else None
    return None


def _trim_leg(leg: dict[str, Any]) -> dict[str, Any]:
    duration = _duration_to_minutes(leg.get("total_duration", leg.get("duration")))
    raw_price = leg.get("price")
    has_price = isinstance(raw_price, (int, float)) and not isinstance(raw_price, bool)
    return {
        "operator": leg.get("operator", leg.get("airline", {}).get("name", "")),
        "duration_minutes": duration,
        # Ground providers return no fare at all; a 0 here would read as free.
        "price": float(raw_price) if isinstance(raw_price, (int, float)) else None,
        "price_unknown": not has_price,
        "stops": leg.get("stops", len(leg.get("layovers", []))),
        "departure": leg.get("departure_airport", {}).get("time", ""),
        "seat_class": leg.get("travel_class", "economy"),
    }


def _no_result_recommendation(
    leg_id: str, currency: str, route_version: int
) -> TransportRecommendation:
    """Explicit 'nothing bookable found' record for one leg."""
    return TransportRecommendation(
        recommended_legs=[],
        total_cost=0.0,
        total_duration_minutes=0,
        currency_code=currency,
        rationale="No transport options found for this leg.",
        personalization_reason="",
        leg_id=leg_id,
        route_version=route_version,
        no_result=True,
    )


def _aggregate_recommendation(
    per_leg: dict[str, TransportRecommendation], currency: str, route_version: int
) -> TransportRecommendation:
    """Sum the per-leg picks deterministically instead of asking the model to add up."""
    priced = [rec for rec in per_leg.values() if not rec.no_result]
    legs = [leg for rec in priced for leg in rec.recommended_legs]
    return TransportRecommendation(
        recommended_legs=legs,
        total_cost=round(sum(rec.total_cost for rec in priced), 2),
        total_duration_minutes=sum(rec.total_duration_minutes for rec in priced),
        currency_code=currency,
        rationale=(
            f"Whole-route total across {len(priced)} priced leg(s) of {len(per_leg)} discovered."
        ),
        personalization_reason="Aggregated from each leg's budget-filtered pick.",
        leg_id="route_aggregate",
        route_version=route_version,
        no_result=not priced,
    )


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


class TransportOptimizerAgent(AgentClarificationMixin):
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
        currency = resolve_from_state(state, log=log)

        route_legs: dict[str, RouteLegPlan] = state.get("route_legs", {})
        legs_raw_by_leg: dict[str, list[Any]] = state.get("transport_legs_raw_by_leg", {})
        if state.get("route_discovery_status") == "multi_stop_provisional" and legs_raw_by_leg:
            log.info(
                "agent_start",
                mode="multi_stop_provisional",
                legs=list(legs_raw_by_leg.keys()),
                currency=currency,
            )
            return await self._optimize_route_legs(
                route_legs,
                legs_raw_by_leg,
                budget,
                travelers,
                state.get("route_version", 0),
                currency,
                log,
            )

        log.info(
            "agent_start",
            mode="single_destination",
            legs=list(legs_raw.keys()),
            currency=currency,
        )
        if not legs_raw:
            log.warning("no_legs_raw")
            return {"transport_recommendation": None, "transport_alternatives": []}

        budget_tier = budget.tier if budget else "mid"

        # ── Budget pre-filter ────────────────────────────────────────────
        filtered_legs = _budget_filter(legs_raw, budget_tier)

        trip_days = dates.trip_days if dates else 3

        legs_summary = {k: [_trim_leg(leg) for leg in v[:4]] for k, v in filtered_legs.items()}

        try:
            output = await invoke_structured(
                self._llm,
                _OptimiserOutput,
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
                ],
                agent=AgentName.TRANSPORT_OPTIMIZER,
                log=log,
            )
        except StructuredOutputError as exc:
            log.error(
                LogEvent.AGENT_DEGRADED,
                section="transport",
                truncated=exc.truncated,
                error=str(exc),
            )
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
        currency: str,
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

        now = datetime.now(tz=UTC)
        disclaimer = "Price is indicative — verify before booking."

        # One bounded call per leg rather than a single request covering the whole
        # route: the combined schema is large enough that a 9-leg route reliably
        # truncated, and one bad leg then discarded every other leg's answer.
        semaphore = asyncio.Semaphore(llm_settings.concurrency)

        async def _optimise_one(leg_id: str, summary: dict[str, Any]) -> TransportRecommendation:
            if not summary["options"]:
                return _no_result_recommendation(leg_id, currency, route_version)
            async with semaphore:
                try:
                    item = await invoke_structured(
                        self._llm,
                        _LegRecommendation,
                        [
                            SystemMessage(content=_LEG_SYSTEM_PROMPT),
                            HumanMessage(
                                content=(
                                    f"Travelers: {travelers}\n"
                                    f"Budget tier: {budget_tier}\n"
                                    f"Currency: {currency}\n\n"
                                    f"Leg id: {leg_id}\n"
                                    f"Leg (JSON):\n{json.dumps(summary, indent=2)}"
                                )
                            ),
                        ],
                        agent=AgentName.TRANSPORT_OPTIMIZER,
                        log=log,
                    )
                except StructuredOutputError as exc:
                    log.warning(
                        LogEvent.AGENT_DEGRADED,
                        section="transport_leg",
                        leg_id=leg_id,
                        truncated=exc.truncated,
                        error=str(exc),
                    )
                    return _no_result_recommendation(leg_id, currency, route_version)

            if item.recommendation is None:
                return _no_result_recommendation(leg_id, currency, route_version)
            rec = _patch_legs(item.recommendation, now, disclaimer)
            return rec.model_copy(
                update={
                    "leg_id": leg_id,
                    "route_version": route_version,
                    "no_result": item.no_result,
                }
            )

        leg_ids = list(legs_summary.keys())
        results = await asyncio.gather(
            *[_optimise_one(leg_id, legs_summary[leg_id]) for leg_id in leg_ids]
        )
        per_leg: dict[str, TransportRecommendation] = dict(zip(leg_ids, results, strict=True))

        # Deterministic coverage guarantee — a leg the LLM omitted still gets an
        # explicit no-result record rather than silently disappearing.
        for leg_id in legs_raw_by_leg:
            if leg_id not in per_leg:
                per_leg[leg_id] = _no_result_recommendation(leg_id, currency, route_version)

        aggregate = _aggregate_recommendation(per_leg, currency, route_version)
        priced = sum(1 for rec in per_leg.values() if not rec.no_result)
        log.info(
            "agent_done",
            mode="multi_stop_provisional",
            legs=list(per_leg.keys()),
            priced_legs=priced,
            unpriced_legs=len(per_leg) - priced,
        )
        return {
            "transport_recommendation_by_leg": per_leg,
            "transport_recommendation": aggregate,
            "transport_alternatives": [],
        }
