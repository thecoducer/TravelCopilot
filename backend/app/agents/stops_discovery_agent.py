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
from typing import Any

from app.agents.base import AgentClarificationMixin
from app.config import settings
from app.graph.state import TripStateModel
from app.llm import StructuredOutputError, get_llm, invoke_structured
from app.logging import get_agent_logger
from app.models.enums import AgentName, LogEvent, StopKind
from app.models.output.stops_discovery_agent_output import (
    StopDiscoveryGatewayOption,
    StopDiscoveryRoute,
    StopDiscoveryStop,
)
from app.models.stops import (
    SINGLE_STOP_ID,
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
from app.prompts.stops_discovery_agent_prompts import ROUTE_DISCOVERY_PROMPT

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


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return slug or "stop"


# option_id is model-supplied and becomes part of every leg and stop id, so it is
# slugified and capped rather than interpolated raw.
_MAX_OPTION_ID_LENGTH = 40


def _option_slug(option_id: str) -> str:
    return _slugify(option_id)[:_MAX_OPTION_ID_LENGTH].strip("_") or "gateway"


class _StopIdAllocator:
    """Assigns stable, unique stop_ids per occurrence — repeats get _01/_02/…"""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def next_id(self, name: str) -> str:
        slug = _slugify(name)
        self._counts[slug] = self._counts.get(slug, 0) + 1
        return f"{slug}_{self._counts[slug]:02d}"


def _normalize_nights(hints: list[int], trip_nights: int) -> list[int]:
    """Scale LLM-provided night counts so they sum exactly to ``trip_nights``.

    An N-day trip contains N-1 nights; scaling to N would push the final stop's
    checkout one day past the traveller's return date.
    """
    n = len(hints)
    if n == 0:
        return []
    total_hint = sum(hints) or n
    scaled = [max(1, round(h * trip_nights / total_hint)) for h in hints]
    diff = trip_nights - sum(scaled)
    if diff:
        scaled[-1] = max(1, scaled[-1] + diff)
    if sum(scaled) != trip_nights:
        scaled = _force_total(scaled, trip_nights)
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
    last_stop_index = len(overnight_ids) - 1
    for stop_index, (stop_id, night_count) in enumerate(zip(overnight_ids, nights, strict=True)):
        # The final stop also owns the return day, which has no night attached.
        day_count = night_count + 1 if stop_index == last_stop_index else night_count
        for offset in range(day_count):
            is_first = offset == 0
            is_last = offset == day_count - 1
            allocations[day_index] = DayAllocation(
                day_index=day_index,
                date=start_date + timedelta(days=day_index),
                stop_id=stop_id,
                is_checkin_day=is_first,
                is_checkout_day=is_last,
                # Arrival days involve a transfer; so does the journey home.
                is_travel_day=is_first or (stop_index == last_stop_index and is_last),
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
    option: StopDiscoveryGatewayOption,
    first_stop: TripStop,
    last_stop: TripStop,
    stops_by_day: dict[int, DayAllocation],
    last_day_index: int,
    self_drive_intent: bool,
) -> GatewayOption:
    option_slug = _option_slug(option.option_id)
    is_passthrough = _slugify(option.gateway_stop.name) != _slugify(first_stop.name)

    if is_passthrough:
        gateway_stop = TripStop(
            stop_id=f"{option_slug}_gateway",
            name=option.gateway_stop.name,
            country=option.gateway_stop.country,
            stop_kind=StopKind.GATEWAY_TRANSIT,
            sequence=0,
            nights=0,
        )
        entry_legs = [
            _make_leg(
                f"{option_slug}_entry_src",
                SOURCE_STOP_ID,
                gateway_stop.stop_id,
                LegType.SOURCE_TO_GATEWAY,
                0,
                stops_by_day,
                self_drive_intent,
            ),
            _make_leg(
                f"{option_slug}_entry_stop",
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
                f"{option_slug}_exit_stop",
                last_stop.stop_id,
                gateway_stop.stop_id,
                LegType.STOP_TO_GATEWAY,
                last_day_index,
                stops_by_day,
                self_drive_intent,
            ),
            _make_leg(
                f"{option_slug}_exit_src",
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
                f"{option_slug}_entry_src",
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
                f"{option_slug}_exit_src",
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
    route: StopDiscoveryRoute,
    dates: TripDates,
    self_drive_intent: bool,
    route_version: int,
    destination: str,
) -> dict[str, Any]:
    trip_days = dates.trip_days

    if route.route_discovery_status == "single_destination" or not route.overnight_stops:
        stop = TripStop(
            stop_id=SINGLE_STOP_ID,
            name=destination,
            stop_kind=StopKind.OVERNIGHT,
            sequence=0,
            nights=trip_days,
            arrival_date=dates.departure,
            departure_date=dates.return_date,
        )
        return {
            "route_discovery_status": "single_destination",
            "route_verification_status": "provisional",
            "route_version": route_version,
            "stops": {SINGLE_STOP_ID: stop},
            "route_legs": {},
            "stops_by_day": {
                day_index: DayAllocation(
                    day_index=day_index,
                    date=dates.departure + timedelta(days=day_index),
                    stop_id=SINGLE_STOP_ID,
                    is_checkin_day=day_index == 0,
                    is_checkout_day=day_index == trip_days - 1,
                )
                for day_index in range(trip_days)
            },
            "gateway_options": [],
            "selected_gateway_option_id": None,
        }

    # A stop can't be allocated fewer than 1 night, so cap the circuit length
    # to the trip's actual duration rather than producing an invalid route.
    overnight_stops_input = route.overnight_stops[:trip_days]
    allocator = _StopIdAllocator()
    overnight_ids = [allocator.next_id(stop.name) for stop in overnight_stops_input]
    nights = _normalize_nights(
        [max(1, stop.nights_hint) for stop in overnight_stops_input], max(1, trip_days - 1)
    )
    stops_by_day = _build_stops_by_day(overnight_ids, nights, dates.departure)
    last_day_index = max(stops_by_day)

    overnight_stops: dict[str, TripStop] = {}
    for i, (stop_id, stop_input, night_count) in enumerate(
        zip(overnight_ids, overnight_stops_input, nights, strict=True)
    ):
        day_indices = sorted(d for d, a in stops_by_day.items() if a.stop_id == stop_id)
        arrival = stops_by_day[day_indices[0]].date
        overnight_stops[stop_id] = TripStop(
            stop_id=stop_id,
            name=stop_input.name,
            country=stop_input.country,
            stop_kind=StopKind.OVERNIGHT,
            sequence=i + 1,  # sequence 0 is reserved for a distinct gateway stop, if any
            nights=night_count,
            arrival_date=arrival,
            # Derived from nights rather than the allocated day span: the final stop
            # owns one extra (night-less) return day.
            departure_date=arrival + timedelta(days=night_count),
            permits_required=stop_input.permits_required,
            altitude_meters=stop_input.altitude_meters,
            notes=stop_input.notes,
        )

    first_stop = overnight_stops[overnight_ids[0]]
    last_stop = overnight_stops[overnight_ids[-1]]

    gateway_options_input = route.gateway_options[: settings.max_gateway_options]
    if not gateway_options_input:
        gateway_options_input = [
            StopDiscoveryGatewayOption(
                option_id="gw_direct",
                gateway_name="Direct",
                gateway_stop=StopDiscoveryStop(name=first_stop.name, stop_kind="overnight"),
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
        destination_stop = overnight_stops[overnight_ids[i + 1]]
        leg_type = (
            LegType.COUNTRY_TRANSFER
            if (
                origin.country
                and destination_stop.country
                and origin.country != destination_stop.country
            )
            else LegType.INTERNAL_TRANSFER
        )
        day_index = max(d for d, a in stops_by_day.items() if a.stop_id == origin.stop_id)
        leg = _make_leg(
            f"leg_internal_{i + 1:02d}",
            origin.stop_id,
            destination_stop.stop_id,
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


class StopsDiscoveryAgent(AgentClarificationMixin):
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
            route = await invoke_structured(
                self._llm,
                StopDiscoveryRoute,
                ROUTE_DISCOVERY_PROMPT.partial(
                    max_gateway_options=settings.max_gateway_options
                ).format_messages(
                    source=s.source,
                    destination=s.destination,
                    trip_days=s.dates.trip_days,
                    travelers=s.travelers,
                    self_drive_intent=s.self_drive_intent,
                ),
                agent=AgentName.STOPS_DISCOVERY,
                session_id=s.session_id,
                log=log,
            )
        except StructuredOutputError as exc:
            log.error(
                LogEvent.AGENT_FAILED,
                section="route_discovery",
                truncated=exc.truncated,
                error=str(exc),
            )
            return _empty_result("discovery_failed", route_version)

        try:
            result = _shape_route(route, s.dates, s.self_drive_intent, route_version, s.destination)
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
