"""Real opening-hours and day-duration validation tools.

Pure-Python implementations — no external API calls.

EnforceOpeningHoursTool
  Checks every experience against the time-slot it is assigned to.
  Returns a list of conflicts (experience closed at that time).

ValidateDayDurationTool
  Sums activity ``duration_hours`` + assumed 30-min transit between activities
  per slot.  Flags any slot exceeding ``slot_max_hours`` (default 10h) or any
  day exceeding ``day_max_hours`` (default 14h).
"""

from __future__ import annotations

from typing import Any

# Slot time windows (24-hour, inclusive)
_SLOT_WINDOWS: dict[str, tuple[int, int]] = {
    "morning": (8, 12),
    "afternoon": (12, 17),
    "evening": (17, 22),
}

_SLOT_MAX_HOURS = 10.0
_DAY_MAX_HOURS = 14.0
_TRANSIT_MINUTES = 30  # assumed transit between consecutive activities


def _is_open_at(opening_hours: dict[str, Any] | None, slot: str) -> bool:
    """Return True if a venue is open during the given slot."""
    if not opening_hours:
        return True  # no hours info → assume open

    try:
        open_hhmm: str = opening_hours.get("open", "00:00")
        close_hhmm: str = opening_hours.get("close", "23:59")

        def _to_minutes(hhmm: str) -> int:
            h, m = hhmm.split(":")
            return int(h) * 60 + int(m)

        open_min = _to_minutes(open_hhmm)
        close_min = _to_minutes(close_hhmm)
        slot_start_h, slot_end_h = _SLOT_WINDOWS.get(slot, (8, 22))
        slot_start_min = slot_start_h * 60
        slot_end_min = slot_end_h * 60

        # Venue must be open for at least 30 minutes within the slot window
        overlap_start = max(open_min, slot_start_min)
        overlap_end = min(close_min, slot_end_min)
        return (overlap_end - overlap_start) >= 30
    except Exception:
        return True  # parse failure → assume open


class EnforceOpeningHoursTool:
    name = "enforce_opening_hours"
    description = "Check experiences against assigned time slots using opening_hours."

    async def run(
        self,
        experiences: list[dict[str, Any]] | None = None,
        travel_dates: Any = None,
        **kwargs: object,
    ) -> dict[str, Any]:
        """
        Args:
            experiences: List of dicts, each with keys:
                ``name``, ``opening_hours`` (optional), ``assigned_slot``
                ("morning" | "afternoon" | "evening").
        """
        experiences = experiences or []
        conflicts: list[dict[str, str]] = []

        for exp in experiences:
            slot = exp.get("assigned_slot", "morning")
            oh = exp.get("opening_hours")
            if not _is_open_at(oh, slot):
                conflicts.append(
                    {
                        "name": exp.get("name", "Unknown"),
                        "assigned_slot": slot,
                        "reason": (
                            f"Closed during {slot} "
                            f"(opens {oh.get('open', '?')} closes {oh.get('close', '?')})"
                        ),
                    }
                )

        return {"conflicts": conflicts, "checked": len(experiences)}


class ValidateDayDurationTool:
    name = "validate_day_duration"
    description = "Flag over-packed day slots (> 10h) or days (> 14h)."

    async def run(
        self,
        day_slots: dict[str, dict[str, list[dict[str, Any]]]] | None = None,
        **kwargs: object,
    ) -> dict[str, Any]:
        """
        Args:
            day_slots: ``{day_iso: {slot_name: [experience_dicts]}}``
                Each experience dict must have ``duration_hours``.
        """
        day_slots = day_slots or {}
        flags: list[dict[str, Any]] = []

        for day, slots in day_slots.items():
            day_total = 0.0
            for slot_name, exps in slots.items():
                if not exps:
                    continue
                slot_total_min = sum(float(e.get("duration_hours", 1.0)) * 60 for e in exps)
                # Add transit time between activities
                slot_total_min += _TRANSIT_MINUTES * max(0, len(exps) - 1)
                slot_total_h = slot_total_min / 60.0
                day_total += slot_total_h

                if slot_total_h > _SLOT_MAX_HOURS:
                    flags.append(
                        {
                            "day": day,
                            "slot": slot_name,
                            "total_hours": round(slot_total_h, 1),
                            "reason": (
                                f"Slot total {slot_total_h:.1f}h exceeds {_SLOT_MAX_HOURS}h cap"
                            ),
                            "excess_activities": max(0, len(exps) - 2),
                        }
                    )

            if day_total > _DAY_MAX_HOURS:
                flags.append(
                    {
                        "day": day,
                        "slot": "day",
                        "total_hours": round(day_total, 1),
                        "reason": f"Full day {day_total:.1f}h exceeds {_DAY_MAX_HOURS}h cap",
                        "excess_activities": 0,
                    }
                )

        return {"flags": flags, "checked_days": len(day_slots)}
