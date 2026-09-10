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

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.llm import get_llm
from app.tools.factory import ToolFactory

logger = structlog.get_logger(__name__)

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

        log = logger.bind(
            agent="transport_search",
            source=source,
            destination=destination,
            session_id=session_id,
        )
        log.info("agent_start")

        # Step A: ask LLM for plausible route combinations.
        raw_combos = await self._get_route_combinations(source, destination, log)

        transport_hubs = list({c.get("via_hub") for c in raw_combos if c.get("via_hub")})

        # Step B: search every route in parallel.
        dep_date = dates.departure.isoformat() if dates else ""
        legs_raw: dict[str, list[Any]] = {}

        async def _fetch_leg(combo: dict[str, Any]) -> None:
            orig = combo["origin"]
            dest = combo["destination"]
            mode = combo["mode"]
            leg_key = f"{orig}→{dest}"

            try:
                options = await self._fetch_route(combo, dep_date)
                if options:
                    legs_raw.setdefault(leg_key, []).extend(options)
            except ValueError:
                log.warning("unsupported_transport_mode", leg=leg_key, mode=mode)
            except Exception as exc:
                log.warning("leg_fetch_failed", leg=leg_key, mode=mode, error=str(exc))

        await asyncio.gather(*[_fetch_leg(c) for c in raw_combos])

        log.info("agent_done", hubs=transport_hubs, legs=list(legs_raw.keys()))
        return {
            "transport_hubs": transport_hubs,
            "transport_legs_raw": legs_raw,
        }

    async def _get_route_combinations(
        self, source: str, destination: str, log: Any
    ) -> list[dict[str, Any]]:
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

    async def _fetch_route(self, combo: dict[str, Any], departure_date: str) -> list[Any]:
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

    async def _fetch_flight(
        self, origin: str, destination: str, departure_date: str
    ) -> list[Any]:
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

    async def _fetch_taxi(
        self, origin: str, destination: str, departure_date: str
    ) -> list[Any]:
        route_result, info_result = await asyncio.gather(
            self._road_route_tool.run(
                origin=origin,
                destination=destination,
                departure_date=departure_date,
            ),
            self._taxi_info_tool.run(location=destination, destination=destination),
        )
        return list(route_result.get("options", [])) + list(info_result.get("options", []))
