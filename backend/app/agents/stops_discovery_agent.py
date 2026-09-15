"""StopsDiscoveryAgent — Layer 1: provisional multi-stop route discovery.

Resolves a free-text source/destination/date query into a **provisional**
ordered route: overnight stops, access-gateway options, leg types, and day
allocation. See ``specs/stops-discovery-agent-spec.md`` for the full contract.

This agent never hardcodes a country/city/region name — it asks the LLM to
reason about the destination's geography generically, then applies
deterministic shaping (stop/leg identity, day allocation, gateway legs) so
every downstream agent gets a stable, typed contract instead of raw prose.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.config import settings
from app.graph.state import TripStateModel
from app.llm import get_llm
from app.logging import get_agent_logger
from app.models.stops import (
    SOURCE_STOP_ID,
    DayAllocation,
    GatewayOption,
    GatewayTradeoffs,
    LegType,
    RouteLegPlan,
    TransportSearchPolicy,
    TripStop,
    default_allowed_modes,
)
from app.models.user_profile import TripDates

_SYSTEM_PROMPT = """\
You are a trip route-planning expert with deep knowledge of world geography and \
regional transport connectivity. Given a traveller's source, destination, trip \
length, and travel style, decide whether the destination is best modelled as:

- a single overnight stop ("single_destination"), or
- a multi-stop circuit of overnight stops connected by an access gateway \
("multi_stop_provisional") — use this whenever the destination is a region, \
country, or area typically visited via more than one overnight town/city, or \
whenever the source has no direct transport connection to the destination \
region and a nearer transport hub is the practical entry/exit point.

For "multi_stop_provisional" routes, propose:
1. ``overnight_stops``: an ordered list of the overnight stops a typical \
traveller would visit (the same place may repeat, e.g. on the way back). \
Give each a sensible number of nights given the total trip length.
2. ``gateway_options``: up to {max_gateway_options} distinct ways to reach the \
region from the source (e.g. flying direct vs. a scenic overland route), each \
with realistic trade-offs. Mark exactly one option ``is_recommended=true``. If \
the first overnight stop already has practical direct transport from the \
source, set the gateway stop's name equal to the first overnight stop's name \
and its stop_kind to "overnight" (no separate transit stop is needed).

Rules:
- Never invent a country name; only set ``country`` when you are confident.
- Keep nights realistic and proportionate to trip length.
- If self_drive_intent is true, prefer gateway options reachable by road/rental.
"""

# leg_type -> relative ordering used to assign a stable, readable `sequence`
# once the full route (gateway legs + internal transfers) is known.
_LEG_TYPE_ORDER: dict[LegType, int] = {
    LegType.SOURCE_TO_GATEWAY: 0,
    LegType.GATEWAY_TO_STOP: 1,
    LegType.INTERNAL_TRANSFER: 2,
    LegType.COUNTRY_TRANSFER: 2,
    LegType.STOP_TO_GATEWAY: 3,
    LegType.GATEWAY_TO_SOURCE: 4,
}

_LONG_DISTANCE_LEG_TYPES = frozenset(
    {LegType.SOURCE_TO_GATEWAY, LegType.GATEWAY_TO_SOURCE, LegType.COUNTRY_TRANSFER}
)


class _Stop(BaseModel):
    name: str
    stop_kind: Literal["overnight", "gateway_transit"] = "overnight"
    nights_hint: int = Field(default=1, ge=0)
    country: str | None = None
    permits_required: list[str] = Field(default_factory=list)
    altitude_meters: int | None = None
    notes: str | None = None


class _GatewayOption(BaseModel):
    option_id: str
    gateway_name: str
    gateway_stop: _Stop
    transit_duration_hours: float | None = None
    cost_tier: str | None = None
    scenic_value: str | None = None
    acclimatization_notes: str | None = None
    is_recommended: bool = False


class _Route(BaseModel):
    route_discovery_status: Literal["single_destination", "multi_stop_provisional"]
    overnight_stops: list[_Stop] = Field(default_factory=list)
    gateway_options: list[_GatewayOption] = Field(default_factory=list)


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return slug or "stop"


class _StopIdAllocator:
    """Assigns stable, unique stop_ids per occurrence — repeats get _01/_02/…"""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def next_id(self, name: str) -> str:
        slug = _slugify(name)
        self._counts[slug] = self._counts.get(slug, 0) + 1
        return f"{slug}_{self._counts[slug]:02d}"


def _normalize_nights(hints: list[int], trip_days: int) -> list[int]:
    """Scale LLM-provided night counts so they sum exactly to ``trip_days``."""
    n = len(hints)
    if n == 0:
        return []
    total_hint = sum(hints) or n
    scaled = [max(1, round(h * trip_days / total_hint)) for h in hints]
    diff = trip_days - sum(scaled)
    if diff:
        scaled[-1] = max(1, scaled[-1] + diff)
    if sum(scaled) != trip_days:
        scaled = _force_total(scaled, trip_days)
    return scaled


def _force_total(values: list[int], total: int) -> list[int]:
    """Deterministically nudge values to sum exactly to ``total``, min 1 each."""
    values = list(values)
    i = 0
    while sum(values) < total:
        values[i % len(values)] += 1
        i += 1
    i = 0
    guard = 0
    while sum(values) > total and guard < 10_000:
        idx = i % len(values)
        if values[idx] > 1:
            values[idx] -= 1
        i += 1
        guard += 1
    return values


def _build_stops_by_day(
    overnight_ids: list[str], nights: list[int], start_date: date
) -> dict[int, DayAllocation]:
    """Allocate one calendar day per index, attributing transfer days per Core concepts.

    Each overnight stop's first/last allocated day is a checkin/checkout +
    travel day — the single source of truth every downstream agent reads
    instead of re-deriving day counts from ``nights`` independently.
    """
    allocations: dict[int, DayAllocation] = {}
    day_index = 0
    for stop_id, night_count in zip(overnight_ids, nights, strict=True):
        for offset in range(night_count):
            is_first = offset == 0
            is_last = offset == night_count - 1
            allocations[day_index] = DayAllocation(
                day_index=day_index,
                date=start_date + timedelta(days=day_index),
                stop_id=stop_id,
                is_checkin_day=is_first,
                is_checkout_day=is_last,
                is_travel_day=is_first or is_last,
            )
            day_index += 1
    return allocations


def _make_leg(
    leg_id: str,
    origin_stop_id: str,
    destination_stop_id: str,
    leg_type: LegType,
    day_index: int,
    stops_by_day: dict[int, DayAllocation],
    self_drive_intent: bool,
) -> RouteLegPlan:
    travel_date = stops_by_day[day_index].date
    return RouteLegPlan(
        leg_id=leg_id,
        origin_stop_id=origin_stop_id,
        destination_stop_id=destination_stop_id,
        sequence=0,  # reassigned by _resequence() once the full route is known
        leg_type=leg_type,
        travel_day_index=day_index,
        planned_departure_date=travel_date,
        planned_arrival_date=travel_date,
        policy=TransportSearchPolicy(
            allowed_modes=default_allowed_modes(leg_type, self_drive_intent),
            search_scope="long_distance" if leg_type in _LONG_DISTANCE_LEG_TYPES else "regional",
        ),
    )


def _resequence(route_legs: dict[str, RouteLegPlan]) -> dict[str, RouteLegPlan]:
    ordered = sorted(
        route_legs.values(),
        key=lambda leg: (leg.travel_day_index, _LEG_TYPE_ORDER.get(leg.leg_type, 9)),
    )
    return {leg.leg_id: leg.model_copy(update={"sequence": i}) for i, leg in enumerate(ordered)}


def _build_gateway_option(
    option: _GatewayOption,
    first_stop: TripStop,
    last_stop: TripStop,
    stops_by_day: dict[int, DayAllocation],
    last_day_index: int,
    self_drive_intent: bool,
) -> GatewayOption:
    is_passthrough = _slugify(option.gateway_stop.name) != _slugify(first_stop.name)

    if is_passthrough:
        gateway_stop = TripStop(
            stop_id=f"{option.option_id}_gateway",
            name=option.gateway_stop.name,
            country=option.gateway_stop.country,
            stop_kind="gateway_transit",
            sequence=0,
            nights=0,
        )
        entry_legs = [
            _make_leg(
                f"{option.option_id}_entry_src",
                SOURCE_STOP_ID,
                gateway_stop.stop_id,
                LegType.SOURCE_TO_GATEWAY,
                0,
                stops_by_day,
                self_drive_intent,
            ),
            _make_leg(
                f"{option.option_id}_entry_stop",
                gateway_stop.stop_id,
                first_stop.stop_id,
                LegType.GATEWAY_TO_STOP,
                0,
                stops_by_day,
                self_drive_intent,
            ),
        ]
        exit_legs = [
            _make_leg(
                f"{option.option_id}_exit_stop",
                last_stop.stop_id,
                gateway_stop.stop_id,
                LegType.STOP_TO_GATEWAY,
                last_day_index,
                stops_by_day,
                self_drive_intent,
            ),
            _make_leg(
                f"{option.option_id}_exit_src",
                gateway_stop.stop_id,
                SOURCE_STOP_ID,
                LegType.GATEWAY_TO_SOURCE,
                last_day_index,
                stops_by_day,
                self_drive_intent,
            ),
        ]
    else:
        gateway_stop = first_stop
        entry_legs = [
            _make_leg(
                f"{option.option_id}_entry_src",
                SOURCE_STOP_ID,
                first_stop.stop_id,
                LegType.SOURCE_TO_GATEWAY,
                0,
                stops_by_day,
                self_drive_intent,
            ),
        ]
        exit_legs = [
            _make_leg(
                f"{option.option_id}_exit_src",
                last_stop.stop_id,
                SOURCE_STOP_ID,
                LegType.GATEWAY_TO_SOURCE,
                last_day_index,
                stops_by_day,
                self_drive_intent,
            ),
        ]

    return GatewayOption(
        option_id=option.option_id,
        gateway_name=option.gateway_name,
        gateway_stop=gateway_stop,
        entry_legs=entry_legs,
        exit_legs=exit_legs,
        tradeoffs=GatewayTradeoffs(
            transit_duration_hours=option.transit_duration_hours,
            cost_tier=option.cost_tier,
            scenic_value=option.scenic_value,
            acclimatization_notes=option.acclimatization_notes,
        ),
        is_recommended=option.is_recommended,
    )


def _empty_result(status: str, route_version: int) -> dict[str, Any]:
    return {
        "route_discovery_status": status,
        "route_verification_status": "provisional",
        "route_version": route_version,
        "stops": {},
        "route_legs": {},
        "stops_by_day": {},
        "gateway_options": [],
        "selected_gateway_option_id": None,
    }


def _shape_route(
    route: _Route,
    dates: TripDates,
    self_drive_intent: bool,
    route_version: int,
) -> dict[str, Any]:
    trip_days = dates.trip_days

    if route.route_discovery_status == "single_destination" or not route.overnight_stops:
        return _empty_result("single_destination", route_version)

    # A stop can't be allocated fewer than 1 night, so cap the circuit length
    # to the trip's actual duration rather than producing an invalid route.
    overnight_stops_input = route.overnight_stops[:trip_days]
    allocator = _StopIdAllocator()
    overnight_ids = [allocator.next_id(stop.name) for stop in overnight_stops_input]
    nights = _normalize_nights(
        [max(1, stop.nights_hint) for stop in overnight_stops_input], trip_days
    )
    stops_by_day = _build_stops_by_day(overnight_ids, nights, dates.departure)
    last_day_index = max(stops_by_day)

    overnight_stops: dict[str, TripStop] = {}
    for i, (stop_id, stop_input, night_count) in enumerate(
        zip(overnight_ids, overnight_stops_input, nights, strict=True)
    ):
        day_indices = sorted(d for d, a in stops_by_day.items() if a.stop_id == stop_id)
        overnight_stops[stop_id] = TripStop(
            stop_id=stop_id,
            name=stop_input.name,
            country=stop_input.country,
            stop_kind="overnight",
            sequence=i + 1,  # sequence 0 is reserved for a distinct gateway stop, if any
            nights=night_count,
            arrival_date=stops_by_day[day_indices[0]].date,
            departure_date=stops_by_day[day_indices[-1]].date + timedelta(days=1),
            permits_required=stop_input.permits_required,
            altitude_meters=stop_input.altitude_meters,
            notes=stop_input.notes,
        )

    first_stop = overnight_stops[overnight_ids[0]]
    last_stop = overnight_stops[overnight_ids[-1]]

    gateway_options_input = route.gateway_options[: settings.max_gateway_options]
    if not gateway_options_input:
        gateway_options_input = [
            _GatewayOption(
                option_id="gw_direct",
                gateway_name="Direct",
                gateway_stop=_Stop(name=first_stop.name, stop_kind="overnight"),
                is_recommended=True,
            )
        ]
    if not any(option.is_recommended for option in gateway_options_input):
        gateway_options_input[0].is_recommended = True

    gateway_options = [
        _build_gateway_option(
            option, first_stop, last_stop, stops_by_day, last_day_index, self_drive_intent
        )
        for option in gateway_options_input
    ]
    recommended = next((g for g in gateway_options if g.is_recommended), gateway_options[0])

    stops: dict[str, TripStop] = dict(overnight_stops)
    if recommended.gateway_stop.stop_id not in stops:
        stops[recommended.gateway_stop.stop_id] = recommended.gateway_stop

    route_legs: dict[str, RouteLegPlan] = {
        leg.leg_id: leg for leg in [*recommended.entry_legs, *recommended.exit_legs]
    }

    # Deterministic internal_transfer legs between consecutive overnight stops —
    # never asked of the LLM, so it can neither invent nor drop a transfer.
    for i in range(len(overnight_ids) - 1):
        origin = overnight_stops[overnight_ids[i]]
        destination = overnight_stops[overnight_ids[i + 1]]
        leg_type = (
            LegType.COUNTRY_TRANSFER
            if origin.country and destination.country and origin.country != destination.country
            else LegType.INTERNAL_TRANSFER
        )
        day_index = max(d for d, a in stops_by_day.items() if a.stop_id == origin.stop_id)
        leg = _make_leg(
            f"leg_internal_{i + 1:02d}",
            origin.stop_id,
            destination.stop_id,
            leg_type,
            day_index,
            stops_by_day,
            self_drive_intent,
        )
        route_legs[leg.leg_id] = leg

    return {
        "route_discovery_status": "multi_stop_provisional",
        "route_verification_status": "provisional",
        "route_version": route_version,
        "stops": stops,
        "route_legs": _resequence(route_legs),
        "stops_by_day": stops_by_day,
        "gateway_options": gateway_options,
        "selected_gateway_option_id": recommended.option_id,
    }


class StopsDiscoveryAgent:
    """Layer 1 — provisional multi-stop route and gateway discovery."""

    def __init__(self, llm: Any | None = None) -> None:
        self._llm = llm or get_llm("stops_discovery")

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        s = TripStateModel.from_state(state)
        log = get_agent_logger(
            "stops_discovery", s.session_id, source=s.source, destination=s.destination
        )
        log.info("agent_start")
        route_version = s.route_version + 1

        if not s.destination or not s.dates:
            log.info(
                "agent_done", status="single_destination", reason="missing_destination_or_dates"
            )
            return _empty_result("single_destination", route_version)

        try:
            chain = self._llm.with_structured_output(_Route)
            route: _Route = await chain.ainvoke(
                [
                    SystemMessage(
                        content=_SYSTEM_PROMPT.format(
                            max_gateway_options=settings.max_gateway_options
                        )
                    ),
                    HumanMessage(
                        content=(
                            f"Source: {s.source}\nDestination: {s.destination}\n"
                            f"Trip length: {s.dates.trip_days} days\n"
                            f"Travelers: {s.travelers}\n"
                            f"Self-drive intent: {s.self_drive_intent}"
                        )
                    ),
                ]
            )
        except Exception as exc:
            log.error("route_discovery_llm_failed", error=str(exc))
            return _empty_result("discovery_failed", route_version)

        try:
            result = _shape_route(route, s.dates, s.self_drive_intent, route_version)
        except Exception as exc:
            log.error("route_shaping_failed", error=str(exc))
            return _empty_result("discovery_failed", route_version)

        log.info(
            "agent_done",
            status=result["route_discovery_status"],
            stops=len(result["stops"]),
            legs=len(result["route_legs"]),
        )
        return result
