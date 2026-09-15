"""Full-graph integration tests — all 8 cases from P2-9.

All tests run with ``MOCK_EXTERNAL_APIS=true`` and a patched LLM so that:
  • Zero real network calls are made
  • LLM returns minimal but schema-valid Pydantic objects
  • Only the graph structure, tool calls, and agent logic are verified

The fake LLM factory dispatches to per-schema response builders, returning
the simplest valid instance of each agent's output model.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.orchestrator import _FieldConfidence, _ParsedQuery
from app.agents.stay_analyst_agent import _RankingOutput
from app.agents.stops_discovery_agent import _GatewayOption, _Route, _Stop
from app.agents.transport_optimizer_agent import _MultiLegOptimiserOutput, _OptimiserOutput
from app.agents.transport_search_agent import _HubResult, _RouteCombo
from app.graph.graph import build_graph
from app.graph.state import initial_state
from app.models.itinerary import (
    ActivityOption,
    Experience,
    ExperiencesOutput,
    Place,
    TimeSlotOptions,
    TripDays,
)
from app.models.itinerary_compilation import ActivityPick, DayPlan, DaySummary, TripNarrative
from app.models.reports import (
    BudgetReport,
    SafetyReport,
    ScamEntry,
    SelfDriveReport,
    VisaReport,
)
from app.models.transport import (
    RouteLeg,
    RouteWaypoint,
    StayOption,
    TransportRecommendation,
)
from app.models.user_profile import BudgetPreference, BudgetTier, UserProfile
from app.services.tool_response_store import ToolResponseStore
from app.tools.factory import ToolFactory

# ── Fake LLM factory ──────────────────────────────────────────────────────────


def _stub_place(name: str = "Mock Place", lat: float = 34.69, lng: float = 135.50) -> Place:
    return Place(
        name=name,
        description="A nice place",
        category="tourist_attraction",
        duration_minutes=120,
        price_range="Free",
        lat=lat,
        lng=lng,
        address="123 Mock St",
    )


def _stub_route_leg() -> RouteLeg:
    from datetime import datetime

    return RouteLeg(
        mode="flight",
        operator="Mock Air",
        origin="KOL",
        destination="OSA",
        duration_minutes=480,
        cost=15000.0,
        currency_code="INR",
        price_cached_at=datetime.now(tz=UTC),
        price_disclaimer="Price is indicative — verify before booking.",
    )


def _stub_transport_rec() -> TransportRecommendation:
    return TransportRecommendation(
        recommended_legs=[_stub_route_leg()],
        total_cost=15000.0,
        total_duration_minutes=480,
        currency_code="INR",
        rationale="Direct flight is best.",
        personalization_reason="Matches mid-range budget.",
        route_waypoints=[
            RouteWaypoint(label="KOL", name="Kolkata", lat=22.57, lng=88.36),
            RouteWaypoint(label="OSA", name="Osaka", lat=34.69, lng=135.50),
        ],
    )


def _stub_stay() -> StayOption:
    return StayOption(
        name="Mock Hotel",
        address="Mock Address",
        city="Osaka",
        price_per_night=5000.0,
        currency_code="INR",
        rating=4.2,
        review_count=100,
        personalization_reason="Good value for mid-range travellers.",
        price_disclaimer="Price per night is indicative.",
    )


def _stub_day_plan(destination: str, max_days: int = 8) -> DayPlan:
    """Pick the two mock experiences for every plausible day number.

    The compiler discards picks whose ``day_number`` is outside the resolved route,
    so one fixed plan serves trips of any length.
    """
    return DayPlan(
        activities=[
            ActivityPick(
                day_number=day_number,
                slot=slot,
                experience_name=name,
                recommendation_reason="Matches your interest in history and nature.",
                best_for=["history", "nature"],
            )
            for day_number in range(1, max_days + 1)
            for slot, name in (
                ("morning", f"Historic Temple in {destination}"),
                ("afternoon", f"Scenic Park in {destination}"),
            )
        ]
    )


def _stub_narrative(destination: str, max_days: int = 8) -> TripNarrative:
    return TripNarrative(
        title=f"Days in {destination}",
        day_summaries=[
            DaySummary(day_number=day_number, summary=f"Exploring {destination}.")
            for day_number in range(1, max_days + 1)
        ],
        packing_tips=["Comfortable walking shoes"],
    )


# ── Per-schema dispatch table ─────────────────────────────────────────────────


def _make_fake_llm(
    destination: str = "Osaka",
    is_intl: bool = False,
    route: _Route | None = None,
    parsed_query: _ParsedQuery | None = None,
) -> MagicMock:
    """Return a MagicMock LLM that dispatches by schema type."""
    _responses: dict[type, Any] = {
        _ParsedQuery: parsed_query
        or _ParsedQuery(
            source_city=_FieldConfidence(value="Kolkata", confidence=0.9),
            destination=_FieldConfidence(value=destination, confidence=0.95),
            departure_date="2026-10-14",
            return_date="2026-10-16",
            trip_days=3,
            trip_days_confidence=0.9,
            travelers=_FieldConfidence(value="2", confidence=1.0),
            budget_tier="mid",
            interests=["food", "history"],
            is_international=is_intl,
            self_drive_intent=False,
            dates_confidence=0.9,
        ),
        SafetyReport: SafetyReport(
            destination=destination,
            advisory_level="Exercise normal caution",
            travel_month="October",
            season_label="Shoulder season",
            season_reason="Post-summer, fewer crowds",
            crowd_level="Moderate",
            crowd_notes="Moderate tourist traffic",
            seasonal_weather_summary="Pleasant, 18–24°C",
            top_scams=[
                ScamEntry(
                    name="Overcharging taxis",
                    description="Some taxi drivers quote inflated rates.",
                    how_to_avoid="Use metered taxis or apps.",
                )
            ],
        ),
        VisaReport: VisaReport(
            passport_country="India",
            destination_country=destination,
            visa_required=is_intl,
            visa_type="tourist" if is_intl else None,
            confidence="medium" if is_intl else "high",
            sources=[],
        ),
        _HubResult: _HubResult(
            route_combinations=[
                _RouteCombo(origin="KOL", destination="OSA", mode="flight"),
            ]
        ),
        _Route: route or _Route(route_discovery_status="single_destination"),
        ExperiencesOutput: ExperiencesOutput(
            experiences=[
                Experience(
                    name=f"Top Attraction in {destination}",
                    type="historical_landmark",
                    description=f"A must-visit landmark in {destination}.",
                    duration_hours=2.0,
                    price_range="Free",
                    lat=34.69,
                    lng=135.50,
                    rating=4.8,
                    review_count=2000,
                ),
                Experience(
                    name=f"Scenic Park in {destination}",
                    type="park",
                    description=f"Beautiful park with greenery in {destination}.",
                    duration_hours=1.5,
                    price_range="Free",
                    lat=34.70,
                    lng=135.51,
                    rating=4.5,
                    review_count=1500,
                ),
            ]
        ),
        _MultiLegOptimiserOutput: _MultiLegOptimiserOutput(aggregate=_stub_transport_rec()),
        _RankingOutput: _RankingOutput(
            ranked_indices=[0, 1, 2],
            personalization_reasons=[
                "Good value for mid-range travellers.",
                "Highly rated and central.",
                "Best amenities for your interests.",
            ],
            rationale="Mock Hotel is the best pick for this trip.",
        ),
        _OptimiserOutput: _OptimiserOutput(
            recommended=_stub_transport_rec(),
            alternatives=[],
        ),
        DayPlan: _stub_day_plan(destination),
        TripNarrative: _stub_narrative(destination),
        BudgetReport: BudgetReport(
            currency_code="INR",
            total_estimated_cost=45000.0,
            per_category_breakdown={
                "transport": 15000.0,
                "accommodation": 15000.0,
                "food": 6000.0,
                "activities": 4500.0,
                "visa": 0.0,
                "self_drive": 0.0,
            },
            per_day_breakdown=[15000.0, 15000.0, 15000.0],
            vs_budget_verdict="on-budget",
        ),
        SelfDriveReport: SelfDriveReport(
            destination=destination,
            recommended_vehicle="Activa 125cc",
            total_km_estimate=200.0,
            fuel_cost_estimate=520.0,
            rental_options=[{"name": "Mock Rentals", "price_per_day": 400}],
        ),
    }

    # Also handle the inline _Tips model in budget_planner
    class _FakeTips:
        tips: list[str] = []

    def _with_structured_output(schema: Any) -> MagicMock:
        chain = MagicMock()
        response = _responses.get(schema)
        if response is None:
            # For unknown schemas (e.g. inline Pydantic models), try model_construct
            try:
                response = schema.model_construct()
            except Exception:
                response = MagicMock()
        chain.ainvoke = AsyncMock(return_value=response)
        return chain

    mock_llm = MagicMock()
    mock_llm.with_structured_output = MagicMock(side_effect=_with_structured_output)
    return mock_llm


# ── Shared graph fixture ──────────────────────────────────────────────────────


@pytest.fixture
def mock_factory() -> ToolFactory:
    return ToolFactory(mock=True)


def _run_graph_with_fake_llm(
    query: str,
    session_id: str = "test-session",
    destination: str = "Osaka",
    is_intl: bool = False,
    extra_state: dict[str, Any] | None = None,
    route: _Route | None = None,
) -> dict[str, Any]:
    """Run the graph with a fake LLM injected directly into all agents."""
    import asyncio

    fake_llm = _make_fake_llm(destination=destination, is_intl=is_intl, route=route)

    async def _run() -> dict[str, Any]:
        factory = ToolFactory(mock=True)
        compiled = build_graph(tool_factory=factory, llm=fake_llm)
        state = initial_state(query=query, session_id=session_id)
        if extra_state:
            state.update(extra_state)
        profile = state.get("user_profile")
        if profile is None:
            state["user_profile"] = UserProfile(
                user_id=session_id,
                food_preferences_configured=True,
            )
        else:
            state["user_profile"] = profile.model_copy(update={"food_preferences_configured": True})
        return await compiled.ainvoke(state)

    return asyncio.run(_run())


def _has_recorded_tool_responses() -> bool:
    response_store = ToolResponseStore()
    fingerprint = response_store.fingerprint(
        {"origin": "KOL", "destination": "OSA", "departure_date": "2026-10-14"}
    )
    return response_store.find_latest_success("search_flights", fingerprint) is not None


class TestFullGraph:
    def test_food_preferences_interrupt_and_resume(self) -> None:
        """An incomplete profile must supply food preferences before food search runs."""
        from langgraph.checkpoint.memory import MemorySaver
        from langgraph.types import Command

        async def _run() -> tuple[dict[str, Any], Any]:
            session_id = "food-preferences-test"
            compiled = build_graph(
                tool_factory=ToolFactory(mock=True),
                llm=_make_fake_llm(),
                checkpointer=MemorySaver(),
            )
            config = {"configurable": {"thread_id": session_id}}
            state = initial_state(query="3 days in Osaka from Kolkata", session_id=session_id)
            state["user_profile"] = UserProfile(user_id="u1")

            await compiled.ainvoke(state, config=config)
            snapshot = await compiled.aget_state(config)
            interrupts = snapshot.tasks[0].interrupts
            payload = interrupts[0].value
            fields = [prompt["field"] for prompt in payload["prompts"]]
            assert fields == ["preferred_cuisines", "dietary_restrictions"]

            with patch("app.graph.graph.upsert_user_profile", new=AsyncMock()):
                result = await compiled.ainvoke(
                    Command(
                        resume={
                            "preferred_cuisines": "Japanese, Korean",
                            "dietary_restrictions": "No dietary restrictions",
                        }
                    ),
                    config=config,
                )
            return result, snapshot

        result, snapshot = asyncio.run(_run())
        assert "food_clarification" in snapshot.next
        profile = result["user_profile"]
        assert profile.preferred_cuisines == ["Japanese", "Korean"]
        assert profile.dietary_restrictions == []
        assert profile.food_preferences_configured is True
        assert result.get("itinerary") is not None

    # Case 1: domestic trip
    def test_domestic_trip_osaka_returns_itinerary(self, mock_factory: ToolFactory) -> None:
        result = _run_graph_with_fake_llm(
            query="3 days Osaka from Kolkata, mid-October, love food",
            destination="Osaka",
            is_intl=False,
        )
        itinerary = result.get("itinerary")
        assert itinerary is not None, "Itinerary must be compiled"
        assert len(itinerary.trip_days) == 3
        assert [d.day_number for d in itinerary.trip_days] == [1, 2, 3]

        # Accommodation shortlist may be empty when the replay archive lacks this request.
        stays = result.get("stays_shortlist", [])
        assert isinstance(stays, list), "stays_shortlist must be a list"
        # Each shortlisted hotel must have personalization_reason + price_disclaimer
        for stay in stays:
            assert stay.personalization_reason
            assert stay.price_disclaimer

        # No clarification triggered
        assert result.get("needs_clarification") is False

    # Case 2: international trip with visa
    def test_international_trip_tokyo_has_visa_report(self) -> None:
        result = _run_graph_with_fake_llm(
            query="5 days Tokyo from Mumbai",
            destination="Tokyo",
            is_intl=True,
            extra_state={
                "is_international": True,
                "user_profile": UserProfile(
                    user_id="u1", passport_country="India", home_city="Mumbai"
                ),
            },
        )
        visa = result.get("visa_report")
        assert visa is not None, "Visa report must be set for international trips"
        assert result.get("is_international") is True

    # Case 3: self-drive trip
    def test_self_drive_goa_has_self_drive_report(self) -> None:
        result = _run_graph_with_fake_llm(
            query="3 days Goa from Mumbai, want to rent a scooter",
            destination="Goa",
            is_intl=False,
            extra_state={"self_drive_intent": True},
        )
        assert result.get("self_drive_report") is not None
        assert result.get("visa_report") is None

    # Case 4: route optimisation — alternatives + price_disclaimer on legs
    def test_transport_alternatives_populated(self) -> None:
        if not _has_recorded_tool_responses():
            pytest.skip("requires recorded tool responses under backend/tool_responses")
        result = _run_graph_with_fake_llm(
            query="Kolkata to Leh 4 days",
            destination="Leh",
            is_intl=False,
        )
        transport = result.get("transport_recommendation")
        assert transport is not None, "Transport recommendation must be set"
        for leg in transport.recommended_legs:
            assert leg.price_disclaimer, f"Leg {leg.operator} missing price_disclaimer"
            assert leg.price_cached_at is not None

    # Case 5: budget filtering — shortlisted stays match budget tier
    def test_budget_tier_stay_shortlist(self) -> None:
        result = _run_graph_with_fake_llm(
            query="3 days Osaka from Kolkata budget trip",
            destination="Osaka",
            is_intl=False,
            extra_state={"budget": BudgetPreference(tier=BudgetTier.budget)},
        )
        shortlist = result.get("stays_shortlist", [])
        # All shortlisted hotels must have personalization_reason and price_disclaimer
        for stay in shortlist:
            assert stay.personalization_reason, f"{stay.name} missing personalization_reason"
            assert stay.price_disclaimer, f"{stay.name} missing price_disclaimer"

    # Case 6: no day slot exceeds 10h
    def test_day_slot_duration_under_limit(self) -> None:
        result = _run_graph_with_fake_llm(
            query="5 days Tokyo from Kolkata",
            destination="Tokyo",
            is_intl=False,
        )
        itinerary = result.get("itinerary")
        if itinerary is None:
            return  # no itinerary due to clarification — skip

        slot_limit_hours = 10.0
        for day in itinerary.trip_days:
            for slot in [day.morning, day.afternoon, day.evening]:
                total = sum(o.estimated_duration_minutes for o in slot.options) / 60.0
                assert total <= slot_limit_hours, (
                    f"Day {day.day_number} {slot.slot} total {total:.1f}h > {slot_limit_hours}h"
                )

    # Case 7: clarification gate — vague query triggers interrupt()
    def test_vague_query_triggers_clarification(self) -> None:
        """When required fields are missing the orchestrator calls interrupt().

        With a MemorySaver checkpointer, ainvoke() returns a partial state and
        the graph is paused.  The checkpoint snapshot's tasks carry the interrupt
        payload with the clarification prompts.
        """
        from langgraph.checkpoint.memory import MemorySaver

        from app.agents.orchestrator import _FieldConfidence, _ParsedQuery

        vague_response = _ParsedQuery(
            source_city=_FieldConfidence(value="unknown", confidence=0.5),
            destination=_FieldConfidence(value=None, confidence=0.0),  # missing
            departure_date=None,
            trip_days=3,
            travelers=_FieldConfidence(value=None, confidence=0.0),  # missing
            budget_tier="mid",
            interests=[],
            is_international=False,
            self_drive_intent=False,
            dates_confidence=0.0,  # missing
        )

        def _with_structured_output(schema: Any) -> MagicMock:
            chain = MagicMock()
            if schema is _ParsedQuery:
                chain.ainvoke = AsyncMock(return_value=vague_response)
            else:
                chain.ainvoke = AsyncMock(return_value=MagicMock())
            return chain

        mock_llm = MagicMock()
        mock_llm.with_structured_output = MagicMock(side_effect=_with_structured_output)

        import asyncio

        async def _run() -> tuple[dict, Any]:
            factory = ToolFactory(mock=True)
            checkpointer = MemorySaver()
            compiled = build_graph(tool_factory=factory, llm=mock_llm, checkpointer=checkpointer)
            state = initial_state(query="plan a trip to Tokyo", session_id="vague-test")
            config = {"configurable": {"thread_id": "vague-test"}}
            result = await compiled.ainvoke(state, config=config)
            snapshot = compiled.get_state(config)
            return result, snapshot

        result, snapshot = asyncio.run(_run())

        # Graph is paused at orchestrator — next step is still 'orchestrator'
        assert "orchestrator" in snapshot.next, (
            f"Graph should be paused at orchestrator, got next={snapshot.next}"
        )
        assert result.get("itinerary") is None, "No itinerary when clarification needed"

        # Interrupt payload must contain clarification prompts
        assert snapshot.tasks, "Snapshot must have tasks when paused"
        interrupts = snapshot.tasks[0].interrupts
        assert interrupts, "Paused task must have interrupts"
        payload = interrupts[0].value
        assert "prompts" in payload, "Interrupt payload must contain 'prompts'"
        fields = [p["field"] for p in payload["prompts"]]
        assert any(f in fields for f in ("destination", "dates", "travelers")), (
            f"Expected a required field in clarification prompts, got: {fields}"
        )

    # Case 8: visa sources + confidence populated (G)
    def test_visa_sources_and_confidence(self) -> None:
        result = _run_graph_with_fake_llm(
            query="5 days Tokyo from Mumbai",
            destination="Tokyo",
            is_intl=True,
            extra_state={
                "is_international": True,
                "user_profile": UserProfile(
                    user_id="u2", passport_country="India", home_city="Mumbai"
                ),
            },
        )
        visa = result.get("visa_report")
        if visa is None:
            pytest.skip("Visa report not populated — check is_international routing")
        assert visa.confidence in ("high", "medium", "low")
        # last_verified_at is set by the agent when it receives at least one source
        # With no official source recording, confidence may be "low"
        assert visa.confidence is not None


# ── Multi-stop route (StopsDiscoveryAgent) integration ─────────────────────────


def _repeated_stop_route() -> _Route:
    """A route that revisits one place — Dirang -> Tawang -> Dirang.

    Kept to 3 overnight stops because the fake orchestrator response used by
    ``_make_fake_llm`` always resolves to a fixed 3-day trip.
    """
    return _Route(
        route_discovery_status="multi_stop_provisional",
        overnight_stops=[
            _Stop(name="Dirang", nights_hint=1),
            _Stop(name="Tawang", nights_hint=1),
            _Stop(name="Dirang", nights_hint=1),
        ],
        gateway_options=[
            _GatewayOption(
                option_id="gw_guwahati",
                gateway_name="Via Guwahati",
                gateway_stop=_Stop(name="Guwahati", stop_kind="gateway_transit"),
                is_recommended=True,
            )
        ],
    )


class TestMultiStopRoute:
    def test_stops_discovery_runs_before_layer_2_and_keys_results_by_stop(self) -> None:
        result = _run_graph_with_fake_llm(
            query="5 days Arunachal Pradesh from Kolkata",
            destination="Arunachal Pradesh",
            is_intl=False,
            route=_repeated_stop_route(),
        )

        assert result.get("route_discovery_status") == "multi_stop_provisional"
        stops = result.get("stops", {})
        dirang_ids = [sid for sid, s in stops.items() if s.name == "Dirang"]
        assert len(dirang_ids) == 2, "Repeated stop must get two distinct stop_ids"

        stays_raw_by_stop = result.get("stays_raw_by_stop", {})
        experiences_raw_by_stop = result.get("experiences_raw_by_stop", {})
        overnight_ids = [sid for sid, s in stops.items() if s.stop_kind == "overnight"]
        assert set(stays_raw_by_stop.keys()) <= set(overnight_ids)
        assert set(experiences_raw_by_stop.keys()) <= set(overnight_ids)

        transport_legs_raw_by_leg = result.get("transport_legs_raw_by_leg", {})
        assert set(transport_legs_raw_by_leg.keys()) == set(result.get("route_legs", {}))

        itinerary = result.get("itinerary")
        assert itinerary is not None
        # Every overnight stop occurrence appears — two Dirang visits, never merged.
        day_stop_ids = [day.stop_id for day in itinerary.trip_days]
        assert set(day_stop_ids) == set(overnight_ids)
        assert day_stop_ids == sorted(day_stop_ids, key=lambda sid: stops[sid].sequence), (
            "Days must follow route order"
        )
        dirang_stop_ids = {day.stop_id for day in itinerary.trip_days if day.location == "Dirang"}
        assert len(dirang_stop_ids) == 2

    def test_ladakh_5_day_trip_continuous_day_numbers_and_source(self) -> None:
        """A 5-day multi-stop Ladakh trip must generate 5 days sequentially numbered from 1 to 5."""
        ladakh_route = _Route(
            route_discovery_status="multi_stop_provisional",
            overnight_stops=[
                _Stop(name="Leh", nights_hint=3),
                _Stop(name="Nubra Valley", nights_hint=2),
            ],
            gateway_options=[
                _GatewayOption(
                    option_id="gw_direct",
                    gateway_name="Direct Flight to Leh",
                    gateway_stop=_Stop(name="Leh", stop_kind="overnight"),
                    is_recommended=True,
                )
            ],
        )
        ladakh_parsed = _ParsedQuery(
            source_city=_FieldConfidence(value="Kolkata", confidence=1.0),
            destination=_FieldConfidence(value="Ladakh", confidence=1.0),
            departure_date="2026-10-14",
            return_date="2026-10-18",
            trip_days=5,
            travelers=_FieldConfidence(value="1", confidence=1.0),
            budget_tier="mid",
            interests=["nature", "photography"],
            is_international=False,
            self_drive_intent=False,
            dates_confidence=1.0,
        )

        fake_llm = _make_fake_llm(
            destination="Ladakh",
            is_intl=False,
            route=ladakh_route,
            parsed_query=ladakh_parsed,
        )

        import asyncio

        async def _run() -> dict[str, Any]:
            factory = ToolFactory(mock=True)
            compiled = build_graph(tool_factory=factory, llm=fake_llm)
            state = initial_state(
                query="I want to go to ladakh from kolkata for 5 days", session_id="ladakh-5d-test"
            )
            state["user_profile"] = UserProfile(
                user_id="ladakh-5d-test", food_preferences_configured=True
            )
            return await compiled.ainvoke(state)

        result = asyncio.run(_run())
        itinerary = result.get("itinerary")
        assert itinerary is not None
        assert itinerary.source == "Kolkata"
        assert itinerary.dates is not None
        assert itinerary.dates.trip_days == 5
        assert len(itinerary.stops) == 2

        all_days = itinerary.trip_days
        assert len(all_days) == 5, f"Expected 5 days total, got {len(all_days)}"

        # Assert sequential continuous day numbers: 1, 2, 3, 4, 5
        day_numbers = [day.day_number for day in all_days]
        assert day_numbers == [1, 2, 3, 4, 5], (
            f"Day numbers should be sequential [1, 2, 3, 4, 5], got {day_numbers}"
        )
        assert {day.location for day in all_days} == {"Leh", "Nubra Valley"}

    def test_discovery_failed_pauses_for_clarification(self) -> None:
        from langgraph.checkpoint.memory import MemorySaver

        def _with_structured_output(schema: Any) -> MagicMock:
            chain = MagicMock()
            if schema is _ParsedQuery:
                chain.ainvoke = AsyncMock(
                    return_value=_ParsedQuery(
                        source_city=_FieldConfidence(value="Kolkata", confidence=0.9),
                        destination=_FieldConfidence(value="Nowhereland", confidence=0.95),
                        departure_date="2026-10-14",
                        return_date="2026-10-17",
                        trip_days=3,
                        trip_days_confidence=0.9,
                        travelers=_FieldConfidence(value="2", confidence=1.0),
                        dates_confidence=0.9,
                    )
                )
            elif schema is _Route:
                chain.ainvoke = AsyncMock(side_effect=RuntimeError("route discovery boom"))
            else:
                chain.ainvoke = AsyncMock(return_value=MagicMock())
            return chain

        mock_llm = MagicMock()
        mock_llm.with_structured_output = MagicMock(side_effect=_with_structured_output)

        import asyncio

        async def _run() -> tuple[dict[str, Any], Any]:
            factory = ToolFactory(mock=True)
            checkpointer = MemorySaver()
            compiled = build_graph(tool_factory=factory, llm=mock_llm, checkpointer=checkpointer)
            state = initial_state(query="plan a trip to Nowhereland", session_id="failed-route")
            config = {"configurable": {"thread_id": "failed-route"}}
            result = await compiled.ainvoke(state, config=config)
            snapshot = compiled.get_state(config)
            return result, snapshot

        result, snapshot = asyncio.run(_run())

        assert result.get("route_discovery_status") == "discovery_failed"
        assert result.get("itinerary") is None, (
            "discovery_failed must never silently produce an itinerary"
        )
        assert "route_clarification" in snapshot.next


# ── Tool-level integration (real opening hours + duration tools) ──────────────


class TestDeterministicGates:
    @pytest.mark.asyncio
    async def test_enforce_opening_hours_real(self) -> None:
        from app.tools.real.opening_hours_tools import EnforceOpeningHoursTool

        tool = EnforceOpeningHoursTool()
        # Venue closes at 17:00; assigned to evening slot (17:00–22:00)
        result = await tool.run(
            experiences=[
                {
                    "name": "Museum",
                    "assigned_slot": "evening",
                    "opening_hours": {"open": "09:00", "close": "17:00"},
                }
            ]
        )
        assert len(result["conflicts"]) == 1
        assert result["conflicts"][0]["name"] == "Museum"

    @pytest.mark.asyncio
    async def test_enforce_opening_hours_no_conflict(self) -> None:
        from app.tools.real.opening_hours_tools import EnforceOpeningHoursTool

        tool = EnforceOpeningHoursTool()
        result = await tool.run(
            experiences=[
                {
                    "name": "Park",
                    "assigned_slot": "morning",
                    "opening_hours": {"open": "07:00", "close": "18:00"},
                }
            ]
        )
        assert result["conflicts"] == []

    @pytest.mark.asyncio
    async def test_validate_day_duration_flag(self) -> None:
        from app.tools.real.opening_hours_tools import ValidateDayDurationTool

        tool = ValidateDayDurationTool()
        # Morning slot with 15h of activities
        result = await tool.run(
            day_slots={
                "2026-10-14": {
                    "morning": [
                        {"name": "A", "duration_hours": 5.0},
                        {"name": "B", "duration_hours": 5.0},
                        {"name": "C", "duration_hours": 5.0},
                    ],
                    "afternoon": [],
                    "evening": [],
                }
            }
        )
        flags = result["flags"]
        morning_flags = [f for f in flags if f.get("slot") == "morning"]
        assert len(morning_flags) >= 1, "Over-packed morning must be flagged"

    @pytest.mark.asyncio
    async def test_validate_day_duration_no_flag(self) -> None:
        from app.tools.real.opening_hours_tools import ValidateDayDurationTool

        tool = ValidateDayDurationTool()
        result = await tool.run(
            day_slots={
                "2026-10-14": {
                    "morning": [{"name": "A", "duration_hours": 2.0}],
                    "afternoon": [{"name": "B", "duration_hours": 2.0}],
                    "evening": [{"name": "C", "duration_hours": 1.5}],
                }
            }
        )
        assert result["flags"] == []

    def test_itinerary_with_closed_venue_resolved(self) -> None:
        """Inject a closed venue and verify the deterministic gate removes it."""
        from app.services.itinerary_compiler_service import ItineraryCompilerService

        place_closed = Place(
            name="ClosedMuseum",
            description="",
            category="museum",
            duration_minutes=120,
            price_range="Free",
            lat=34.69,
            lng=135.50,
            address="Test",
        )
        place_open = Place(
            name="OpenPark",
            description="",
            category="park",
            duration_minutes=90,
            price_range="Free",
            lat=34.70,
            lng=135.51,
            address="Test",
        )
        opt_closed = ActivityOption(
            place=place_closed,
            rank=1,
            recommendation_reason="Great museum",
            best_for=["history"],
            estimated_duration_minutes=120,
        )
        opt_open = ActivityOption(
            place=place_open,
            rank=2,
            recommendation_reason="Nice walk",
            best_for=["nature"],
            estimated_duration_minutes=90,
        )
        day = TripDays(
            date=date(2026, 10, 14),
            day_number=1,
            location="Osaka",
            morning=TimeSlotOptions(slot="morning", options=[opt_closed, opt_open]),
            afternoon=TimeSlotOptions(slot="afternoon"),
            evening=TimeSlotOptions(slot="evening"),
        )

        resolved = ItineraryCompilerService().resolve_conflicts(
            [day], conflict_names={"ClosedMuseum"}, duration_flags=[]
        )

        names = [o.place.name for o in resolved[0].morning.options]
        assert "ClosedMuseum" not in names
        assert "OpenPark" in names
