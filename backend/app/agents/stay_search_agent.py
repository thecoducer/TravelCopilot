"""StaySearchAgent — Layer 2: hotel / accommodation supply search.

Pure tool-call agent — no LLM.  Applies user preference filters before
writing results to state.
"""

from __future__ import annotations

import re
from typing import Any

import structlog

from app.models.transport import StayOption
from app.models.user_profile import budget_from_state
from app.tools.factory import ToolFactory

logger = structlog.get_logger(__name__)


_CURRENCY_SYMBOL_TO_CODE = {
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "₹": "INR",
    "¥": "JPY",
}


def _parse_number(value: object, default: float = 0.0) -> float:
    """Parse numbers from heterogeneous internet payloads safely.

    Handles values like "8,200", "₹ 8,200", "1.234,56", "4.5/5", "1,203 reviews".
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        return float(value)

    raw = str(value).strip()
    if not raw:
        return default

    # Keep digits/sign and common separators only.
    token = re.sub(r"[^\d,\.\-]", "", raw)
    if not token:
        return default

    if "," in token and "." in token:
        # Last separator is most likely decimal separator.
        if token.rfind(",") > token.rfind("."):
            token = token.replace(".", "").replace(",", ".")
        else:
            token = token.replace(",", "")
    elif "," in token:
        # Treat as decimal comma only for short trailing precision, else thousands separators.
        frac = token.split(",")[-1]
        if token.count(",") == 1 and len(frac) in {1, 2}:
            token = token.replace(",", ".")
        else:
            token = token.replace(",", "")

    try:
        return float(token)
    except ValueError:
        return default


def _parse_int(value: object, default: int = 0) -> int:
    parsed = _parse_number(value, default=float(default))
    if parsed < 0:
        return default
    return int(parsed)


def _list_of_str(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _extract_rate_lowest(prop: dict[str, Any]) -> object:
    rate = prop.get("rate_per_night", {})
    if isinstance(rate, dict):
        return rate.get("lowest", 0)
    return rate


def _extract_currency(prop: dict[str, Any], price_source: object) -> str:
    explicit = prop.get("currency")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip().upper()

    price_text = str(price_source or "")
    for symbol, code in _CURRENCY_SYMBOL_TO_CODE.items():
        if symbol in price_text:
            return code
    return "INR"


def _extract_coords(prop: dict[str, Any]) -> tuple[float | None, float | None]:
    gps = prop.get("gps_coordinates")
    if not isinstance(gps, dict):
        return None, None

    lat = _parse_number(gps.get("latitude"), default=0.0)
    lng = _parse_number(gps.get("longitude"), default=0.0)
    if lat == 0.0 and lng == 0.0:
        return None, None
    return lat, lng


def _extract_maps_url(prop: dict[str, Any], lat: float | None, lng: float | None) -> str | None:
    direct = prop.get("google_maps_url")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    if lat is not None and lng is not None:
        return f"https://maps.google.com/?q={lat},{lng}"
    return None


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
        budget = budget_from_state(state.get("budget"))
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
                price_source = _extract_rate_lowest(prop)
                price = max(0.0, _parse_number(price_source, default=0.0))
                rating = _parse_number(prop.get("overall_rating", 0), default=0.0)
                rating = max(0.0, min(5.0, rating))
                review_count = _parse_int(prop.get("reviews", 0), default=0)
                lat, lng = _extract_coords(prop)
                currency_code = _extract_currency(prop, price_source)

                stays.append(
                    StayOption(
                        name=str(prop.get("name", "Unknown Hotel") or "Unknown Hotel"),
                        address=str(prop.get("address", destination) or destination),
                        city=destination,
                        price_per_night=price,
                        currency_code=currency_code,
                        rating=rating,
                        review_count=review_count,
                        amenities=_list_of_str(prop.get("amenities", [])),
                        photos=_list_of_str(prop.get("images", [])),
                        google_maps_url=_extract_maps_url(prop, lat, lng),
                        booking_url=(str(prop.get("link")).strip() if prop.get("link") else None),
                        hotel_style=user_profile.hotel_style if user_profile else None,
                        price_tier=str(budget_tier_str),
                        lat=lat,
                        lng=lng,
                        check_in=(
                            str(prop.get("check_in_time")).strip()
                            if prop.get("check_in_time")
                            else None
                        ),
                        check_out=(
                            str(prop.get("check_out_time")).strip()
                            if prop.get("check_out_time")
                            else None
                        ),
                    )
                )
            except Exception as exc:
                log.warning("stay_parse_failed", prop_name=prop.get("name"), error=str(exc))

        log.info("agent_done", stays_found=len(stays))
        return {"stays_raw": stays}
