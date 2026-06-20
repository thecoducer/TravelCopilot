"""TransportOptimizerAgent — Layer 3: multi-modal route reasoning.

Applies a budget pre-filter before LLM reasoning so that budget users never
see premium/business-class options.  Produces both the recommended route and
up to 2 budget-filtered alternatives.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.llm import get_llm
from app.models.transport import TransportRecommendation
from app.tools.factory import ToolFactory

logger = structlog.get_logger(__name__)

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


def _is_premium(leg: dict[str, Any]) -> bool:
    """Return True if the leg uses a premium seat class."""
    seat = str(leg.get("travel_class", leg.get("seat_class", ""))).lower()
    return any(p in seat for p in _PREMIUM_CLASSES)


def _budget_filter(legs_raw: dict[str, list[Any]], budget_tier: str) -> dict[str, list[Any]]:
    """Remove premium options from legs_raw for non-luxury tiers."""
    if budget_tier == "luxury":
        return legs_raw
    return {
        key: [leg for leg in options if not _is_premium(leg)]
        for key, options in legs_raw.items()
    }


class TransportOptimizerAgent:
    """Layer 3 — Budget-filtered route selection + alternatives."""

    def __init__(
        self,
        tool_factory: ToolFactory | None = None,
        llm: object | None = None,
    ) -> None:
        self._llm = llm or get_llm("transport_optimizer")

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        source: str = state.get("source", "")
        destination: str = state.get("destination", "")
        legs_raw: dict[str, list[Any]] = state.get("transport_legs_raw", {})
        dates = state.get("dates")
        budget = state.get("budget")
        travelers: int = state.get("travelers", 1)
        session_id: str = state.get("session_id", "")

        log = logger.bind(agent="transport_optimizer", source=source, destination=destination, session_id=session_id)
        log.info("agent_start", route_options=list(legs_raw.keys()))

        if not legs_raw:
            log.warning("no_legs_raw")
            return {"transport_recommendation": None, "transport_alternatives": []}

        budget_tier = budget.tier if budget else "mid"

        # ── Budget pre-filter ────────────────────────────────────────────
        filtered_legs = _budget_filter(legs_raw, budget_tier)

        trip_days = dates.trip_days if dates else 3

        def _trim_leg(leg: dict[str, Any]) -> dict[str, Any]:
            return {
                "operator": leg.get("operator", leg.get("airline", {}).get("name", "")),
                "duration_minutes": leg.get("total_duration", leg.get("duration", 0)),
                "price": leg.get("price", 0),
                "stops": leg.get("stops", len(leg.get("layovers", []))),
                "departure": leg.get("departure_airport", {}).get("time", ""),
                "seat_class": leg.get("travel_class", "economy"),
            }

        legs_summary = {
            k: [_trim_leg(l) for l in v[:4]] for k, v in filtered_legs.items()
        }

        chain = self._llm.with_structured_output(_OptimiserOutput)  # type: ignore[union-attr]
        try:
            output: _OptimiserOutput = chain.invoke(
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

        def _patch_legs(rec: TransportRecommendation) -> TransportRecommendation:
            patched = []
            for leg in rec.recommended_legs:
                patched.append(
                    leg.model_copy(
                        update={
                            "price_cached_at": getattr(leg, "price_cached_at", None) or now,
                            "price_disclaimer": leg.price_disclaimer or disclaimer,
                        }
                    )
                )
            return rec.model_copy(update={"recommended_legs": patched})

        recommendation = _patch_legs(output.recommended)
        alternatives = [_patch_legs(a) for a in output.alternatives[:2]]

        log.info("agent_done", total_cost=recommendation.total_cost, alternatives=len(alternatives))
        return {
            "transport_recommendation": recommendation,
            "transport_alternatives": alternatives,
        }


