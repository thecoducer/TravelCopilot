"""Single resolution point for the currency used across a planning session.

Every agent, tool adapter and budget calculation must ask for the trip currency
here rather than assuming one. Supply providers are queried *in* this currency,
so prices arrive already denominated correctly instead of being fetched in USD
and guessed back from a symbol later.
"""

from __future__ import annotations

from typing import Any

import structlog

from app.config import ISO_CURRENCY_CODE_LENGTH, settings
from app.models.enums import LogEvent

logger = structlog.get_logger(__name__)


def is_valid_currency_code(value: object) -> bool:
    """True for a syntactically valid ISO 4217 alphabetic code."""
    return (
        isinstance(value, str)
        and len(value.strip()) == ISO_CURRENCY_CODE_LENGTH
        and value.strip().isalpha()
    )


def resolve_trip_currency(user_profile: Any = None, *, log: Any = None) -> str:
    """Return the ISO 4217 code every price in this trip should be expressed in.

    Falls back to the configured default when the profile carries no usable
    preference, and records which source won so a surprising currency in the
    itinerary can be traced back.
    """
    preferred = getattr(user_profile, "preferred_currency", None)
    if is_valid_currency_code(preferred):
        return str(preferred).strip().upper()

    resolved = settings.default_currency.strip().upper()
    (log or logger).debug(
        LogEvent.CURRENCY_RESOLVED,
        currency=resolved,
        source="default",
        rejected=preferred if preferred else None,
    )
    return resolved


def resolve_from_state(state: dict[str, Any], *, log: Any = None) -> str:
    """Convenience wrapper for agents that hold raw graph state."""
    return resolve_trip_currency(state.get("user_profile"), log=log)
