"""StaySearchAgent — Layer 2: hotel / accommodation supply search.

Pure tool-call agent — no LLM.  Applies user preference filters before
writing results to state.
"""

from __future__ import annotations

from typing import Any

import structlog

from app.models.transport import StayOption
from app.tools.factory import ToolFactory

logger = structlog.get_logger(__name__)


class StaySearchAgent:
    """Layer 2 — Hotel and accommodation search via SerpAPI Google Hotels."""

    def __init__(self, tool_factory: ToolFactory | None = None) -> None:
        factory = tool_factory or ToolFactory()
        self._hotel_tool = factory.get("search_hotels")

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        destination: str = state.get("destination", "")
        dates = state.get("dates")
        travelers: int = state.get("travelers", 1)
        user_profile = state.get("user_profile")
        budget = state.get("budget")
        session_id: str = state.get("session_id", "")

        log = logger.bind(agent="stay_search", destination=destination, session_id=session_id)
        log.info("agent_start")

        checkin = dates.departure.isoformat() if dates else ""
        checkout = dates.return_date.isoformat() if dates and dates.return_date else ""

        result = await self._hotel_tool.run(
            location=destination,
            check_in=checkin,
            check_out=checkout,
            adults=travelers,
            hotel_style=user_profile.hotel_style if user_profile else None,
            budget_tier=budget.tier if budget else "mid",
        )

        raw_properties: list[dict[str, Any]] = result.get("properties", [])

        # Map SerpAPI property dicts to StayOption models — best-effort, skip invalid
        stays: list[StayOption] = []
        budget_tier_str = budget.tier if budget else "mid"

        for prop in raw_properties:
            try:
                price = float(prop.get("rate_per_night", {}).get("lowest", 0) or 0)
                stays.append(
                    StayOption(
                        name=prop.get("name", "Unknown Hotel"),
                        address=prop.get("address", destination),
                        city=destination,
                        price_per_night=price,
                        currency_code=prop.get("currency", "INR"),
                        rating=float(prop.get("overall_rating", 0) or 0),
                        review_count=int(prop.get("reviews", 0) or 0),
                        amenities=prop.get("amenities", []),
                        photos=prop.get("images", []),
                        google_maps_url=prop.get("gps_coordinates") and None,
                        booking_url=prop.get("link"),
                        hotel_style=user_profile.hotel_style if user_profile else None,
                        price_tier=budget_tier_str,
                        check_in=prop.get("check_in_time"),
                        check_out=prop.get("check_out_time"),
                    )
                )
            except Exception as exc:
                log.warning("stay_parse_failed", prop_name=prop.get("name"), error=str(exc))

        log.info("agent_done", stays_found=len(stays))
        return {"stays_raw": stays}
