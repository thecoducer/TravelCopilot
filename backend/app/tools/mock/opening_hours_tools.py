"""Mock opening-hours and day-duration validation tools.

Both tools are optimistic in mock mode — they always report zero conflicts so
the compiler can run unobstructed during development.  The real implementations
(real/opening_hours_tools.py) perform the actual checks.
"""

from __future__ import annotations

from typing import Any


class MockEnforceOpeningHoursTool:
    name = "enforce_opening_hours"
    description = "Mock opening-hours check — always returns zero conflicts."

    async def run(
        self,
        experiences: list[dict[str, Any]] | None = None,
        travel_dates: Any = None,
        **kwargs: object,
    ) -> dict[str, Any]:
        return {"conflicts": [], "checked": len(experiences or [])}


class MockValidateDayDurationTool:
    name = "validate_day_duration"
    description = "Mock day-duration check — always returns zero violations."

    async def run(
        self,
        day_slots: dict[str, Any] | None = None,
        **kwargs: object,
    ) -> dict[str, Any]:
        return {"flags": [], "checked_days": len(day_slots or {})}
