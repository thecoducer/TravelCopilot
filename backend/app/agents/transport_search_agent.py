"""TransportSearchAgent — Layer 2: hub identification + multimodal search.

Pure tool-call agent (no LLM synthesis) — one cheap LLM call for hub
identification (Step A), then parallel tool calls for each route leg (Step B).

Step A — Hub identification:
    LLM enumerates plausible route combinations using geographic knowledge.
    Result written to ``state["transport_hubs"]``.

Step B — Parallel supply search:
    - SerpAPI google_flights for each flight leg
    - Google Routes API transit for train/bus/ferry legs
    - Google Routes API driving routes plus taxi-operator discovery for cab legs
    Result written to ``state["transport_legs_raw"]`` keyed by "ORIG→DEST".
"""

from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.llm import get_llm
from app.logging import get_agent_logger
from app.models.stops import RouteLegPlan, stop_display_name
from app.tools.factory import ToolFactory

# Generic TransportSearchPolicy.allowed_modes value -> which fetch helper handles it.
_TRANSIT_MODES = frozenset({"train", "bus", "intercity_bus", "ferry"})
_ROAD_MODES = frozenset({"road", "taxi", "rental", "local_transit", "private_car"})

_HUB_SYSTEM_PROMPT = """\
You are a transport routing expert. Given a source and destination, identify all
plausible route combinations a traveller might take.

For each route combination return:
  - origin: IATA code or city name
  - destination: IATA code or city name
  - mode: "flight" | "train" | "bus" | "cab" | "taxi" | "ferry" | "other"
  - via_hub: intermediate city/IATA code (if applicable)

Return between 1 and 5 route combinations — prefer direct routes first, then
1-stop via major hubs. For domestic Indian routes always include a train option
where relevant.
"""


class _RouteCombo(BaseModel):
    origin: str
    destination: str
    mode: str = Field(pattern="^(flight|train|bus|cab|taxi|ferry|other)$")
    via_hub: str | None = None


class _HubResult(BaseModel):
    route_combinations: list[_RouteCombo] = Field(default_factory=list)


class TransportSearchAgent:
    """Layer 2 — Multi-modal transport supply search."""

    def __init__(
        self,
        tool_factory: ToolFactory | None = None,
        llm: Any | None = None,
    ) -> None:
        factory = tool_factory or ToolFactory()
        self._flight_tool = factory.get("search_flights")
        self._transit_tool = factory.get("search_transit")
        self._road_route_tool = factory.get("search_road_routes")
        self._taxi_info_tool = factory.get("search_taxi_info")
        self._llm = llm or get_llm("transport_search")

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        source: str = state.get("source", "")
        destination: str = state.get("destination", "")
        dates = state.get("dates")
        session_id: str = state.get("session_id", "")

        log = get_agent_logger(
            "transport_search", session_id, source=source, destination=destination
        )
        log.info("agent_start")

        route_legs: dict[str, RouteLegPlan] = state.get("route_legs", {})
        if state.get("route_discovery_status") == "multi_stop_provisional" and route_legs:
            return await self._search_route_legs(route_legs, state.get("stops", {}), source, log)

        # Example: Kolkata -> Leh may produce KOL->IXL via DEL.
        raw_combos = await self._get_route_combinations(source, destination, log)

        transport_hubs = list({c.get("via_hub") for c in raw_combos if c.get("via_hub")})

        # Each route is independent, so flight, train, and taxi searches can overlap.
        dep_date = dates.departure.isoformat() if dates else ""
        legs_raw: dict[str, list[Any]] = {}

        await asyncio.gather(
            *[self._fetch_leg(combo, dep_date, legs_raw, log) for combo in raw_combos]
        )

        log.info("agent_done", hubs=transport_hubs, legs=list(legs_raw.keys()))
        return {
            "transport_hubs": transport_hubs,
            "transport_legs_raw": legs_raw,
        }

    async def _get_route_combinations(
        self, source: str, destination: str, log: Any
    ) -> list[dict[str, Any]]:
        """Ask the LLM for routes, then use a direct flight as a safe fallback."""
        try:
            chain = self._llm.with_structured_output(_HubResult)
            hubs: _HubResult = await chain.ainvoke(
                [
                    SystemMessage(content=_HUB_SYSTEM_PROMPT),
                    HumanMessage(content=f"Source: {source}\nDestination: {destination}"),
                ]
            )
            combinations = [combo.model_dump() for combo in hubs.route_combinations]
            if combinations:
                return combinations
        except Exception as exc:
            log.warning("hub_llm_failed", error=str(exc))

        return [{"origin": source, "destination": destination, "mode": "flight"}]

    async def _fetch_leg(
        self,
        combo: dict[str, Any],
        departure_date: str,
        legs_raw: dict[str, list[Any]],
        log: Any,
    ) -> None:
        """Fetch one route and add its options without blocking other routes.

        Example: a ``taxi`` combo fetches road and operator data; a failed
        ``flight`` combo is logged while other combinations continue.
        """
        origin = combo["origin"]
        destination = combo["destination"]
        mode = combo["mode"]
        leg_key = f"{origin}→{destination}"

        try:
            options = await self._fetch_route(combo, departure_date)
            if options:
                legs_raw.setdefault(leg_key, []).extend(options)
        except ValueError:
            log.warning("unsupported_transport_mode", leg=leg_key, mode=mode)
        except Exception as exc:
            log.warning("leg_fetch_failed", leg=leg_key, mode=mode, error=str(exc))

    async def _fetch_route(self, combo: dict[str, Any], departure_date: str) -> list[Any]:
        """Map each route mode to its supply search tool."""
        origin = combo["origin"]
        destination = combo["destination"]
        mode = combo["mode"]

        if mode == "flight":
            return await self._fetch_flight(origin, destination, departure_date)
        if mode in {"train", "bus", "ferry"}:
            return await self._fetch_transit(origin, destination, mode, departure_date)
        if mode in {"cab", "taxi"}:
            return await self._fetch_taxi(origin, destination, departure_date)
        raise ValueError(f"Unsupported transport mode: {mode}")

    async def _fetch_flight(self, origin: str, destination: str, departure_date: str) -> list[Any]:
        result = await self._flight_tool.run(
            origin=origin,
            destination=destination,
            departure_date=departure_date,
        )
        return list(result.get("best_flights", [])) + list(result.get("other_flights", []))

    async def _fetch_transit(
        self, origin: str, destination: str, mode: str, departure_date: str
    ) -> list[Any]:
        result = await self._transit_tool.run(
            origin=origin,
            destination=destination,
            mode=mode,
            departure_date=departure_date,
        )
        return list(result.get("options", []))

    async def _fetch_taxi(self, origin: str, destination: str, departure_date: str) -> list[Any]:
        route_result, info_result = await asyncio.gather(
            self._road_route_tool.run(
                origin=origin,
                destination=destination,
                departure_date=departure_date,
            ),
            self._taxi_info_tool.run(location=destination, destination=destination),
        )
        return list(route_result.get("options", [])) + list(info_result.get("options", []))

    # ── Route-aware (multi-stop) search ──────────────────────────────────────

    async def _search_route_legs(
        self,
        route_legs: dict[str, RouteLegPlan],
        stops: dict[str, Any],
        source: str,
        log: Any,
    ) -> dict[str, Any]:
        """Search every ``route_legs`` entry in parallel, keyed by ``leg_id``.

        Never falls back to a name-keyed dict — repeated stop occurrences (and
        the source/gateway sentinel endpoints) each resolve to their own leg.
        """
        results = await asyncio.gather(
            *[self._search_leg(leg, stops, source, log) for leg in route_legs.values()]
        )
        legs_raw_by_leg: dict[str, list[Any]] = {}
        updated_route_legs: dict[str, RouteLegPlan] = {}
        for leg_id, (options, updated_leg) in zip(route_legs.keys(), results, strict=True):
            legs_raw_by_leg[leg_id] = options
            updated_route_legs[leg_id] = updated_leg

        log.info("agent_done", legs=list(legs_raw_by_leg.keys()), mode="multi_stop_provisional")
        return {
            "transport_legs_raw_by_leg": legs_raw_by_leg,
            "route_legs": updated_route_legs,
        }

    async def _search_leg(
        self,
        leg: RouteLegPlan,
        stops: dict[str, Any],
        source: str,
        log: Any,
    ) -> tuple[list[Any], RouteLegPlan]:
        """Search one leg, trying its allowed modes in precedence order.

        Falls back to the next allowed mode when the preferred one returns no
        results, recording ``mode_downgraded`` rather than failing silently
        (Core concepts: transport search policy precedence, tier 5).
        """
        origin_name = stop_display_name(leg.origin_stop_id, stops, source)
        destination_name = stop_display_name(leg.destination_stop_id, stops, source)
        departure_date = leg.planned_departure_date.isoformat()

        options: list[Any] = []
        downgraded = False
        for i, mode in enumerate(leg.policy.allowed_modes or ["road"]):
            try:
                options = await self._fetch_by_generic_mode(
                    mode, origin_name, destination_name, departure_date
                )
            except Exception as exc:
                log.warning("leg_mode_failed", leg_id=leg.leg_id, mode=mode, error=str(exc))
                options = []
            if options:
                downgraded = i > 0
                break

        if not downgraded:
            return options, leg
        return options, leg.model_copy(
            update={"policy": leg.policy.model_copy(update={"mode_downgraded": True})}
        )

    async def _fetch_by_generic_mode(
        self, mode: str, origin: str, destination: str, departure_date: str
    ) -> list[Any]:
        """Map a generic ``TransportSearchPolicy`` mode to a concrete supply search."""
        if mode == "flight":
            return await self._fetch_flight(origin, destination, departure_date)
        if mode in _TRANSIT_MODES:
            transit_mode = mode if mode in {"train", "bus", "ferry"} else "bus"
            return await self._fetch_transit(origin, destination, transit_mode, departure_date)
        return await self._fetch_taxi(origin, destination, departure_date)
