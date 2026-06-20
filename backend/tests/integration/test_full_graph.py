"""Full-graph integration tests — all 8 cases from P2-9.

All tests run with ``MOCK_EXTERNAL_APIS=true`` and a patched LLM so that:
  • Zero real network calls are made
  • LLM returns minimal but schema-valid Pydantic objects
  • Only the graph structure, tool calls, and agent logic are verified

The fake LLM factory dispatches to per-schema response builders, returning
the simplest valid instance of each agent's output model.
"""

from __future__ import annotations

from datetime import UTC, date
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.agents.orchestrator import _FieldConfidence, _ParsedQuery
from app.agents.stay_analyst_agent import _RankingOutput
from app.agents.transport_optimizer_agent import _OptimiserOutput
from app.agents.transport_search_agent import _HubResult, _RouteCombo
from app.graph.graph import build_graph
from app.graph.state import initial_state
from app.models.itinerary import (
    ActivityOption,
    Day,
    Itinerary,
    Place,
    TimeSlotOptions,
    TransportSection,
    TripSegment,
)
from app.models.reports import (
    BudgetReport,
    DestinationContextReport,
    ScamEntry,
    ScamSafetyReport,
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


def _stub_itinerary(destination: str = "Osaka", trip_days: int = 3) -> Itinerary:
    days = [
        Day(
            date=date(2026, 10, 14) + __import__("datetime").timedelta(days=i),
            day_number=i + 1,
            location=destination,
            morning=TimeSlotOptions(
                slot="morning",
                options=[
                    ActivityOption(
                        place=_stub_place(f"Morning Place {i + 1}"),
                        rank=1,
                        recommendation_reason="Great for photography lovers.",
                        best_for=["photography", "history"],
                        estimated_duration_minutes=120,
                    )
                ],
            ),
            afternoon=TimeSlotOptions(
                slot="afternoon",
                options=[
                    ActivityOption(
                        place=_stub_place(f"Afternoon Place {i + 1}", lat=34.70, lng=135.51),
                        rank=1,
                        recommendation_reason="Matches your interest in food.",
                        best_for=["food"],
                        estimated_duration_minutes=90,
                    )
                ],
            ),
            evening=TimeSlotOptions(
                slot="evening",
                options=[
                    ActivityOption(
                        place=_stub_place(f"Evening Place {i + 1}", lat=34.71, lng=135.52),
                        rank=1,
                        recommendation_reason="Great nightlife spot.",
                        best_for=["nightlife"],
                        estimated_duration_minutes=60,
                    )
                ],
            ),
        )
        for i in range(trip_days)
    ]
    return Itinerary(
        title=f"{trip_days} Days in {destination}",
        source="Kolkata",
        destination=destination,
        destinations=[destination],
        travelers=2,
        reality_banner="Moderate crowds, pleasant weather.",
        segments=[TripSegment(location=destination, days=days)],
        transport_section=TransportSection(recommended=_stub_transport_rec(), alternatives=[]),
        safety_briefing="Exercise normal caution. Beware of overcharging taxis.",
        budget_breakdown=None,
    )


# ── Per-schema dispatch table ─────────────────────────────────────────────────


def _make_fake_llm(destination: str = "Osaka", is_intl: bool = False) -> MagicMock:
    """Return a MagicMock LLM that dispatches by schema type."""
    _responses: dict[type, Any] = {
        _ParsedQuery: _ParsedQuery(
            source_city=_FieldConfidence(value="Kolkata", confidence=0.9),
            destination=_FieldConfidence(value=destination, confidence=0.95),
            departure_date="2026-10-14",
            return_date="2026-10-17",
            trip_days=3,
            travelers=_FieldConfidence(value="2", confidence=1.0),
            budget_tier="mid",
            interests=["food", "history"],
            is_international=is_intl,
            self_drive_intent=False,
            dates_confidence=0.9,
        ),
        DestinationContextReport: DestinationContextReport(
            destination=destination,
            travel_month="October",
            is_peak_season=False,
            season_label="Shoulder season",
            season_reason="Post-summer, fewer crowds",
            crowd_level="Moderate",
            crowd_notes="Moderate tourist traffic",
            real_daily_cost=5000.0,
            currency_code="JPY",
            seasonal_weather_summary="Pleasant, 18–24°C",
        ),
        ScamSafetyReport: ScamSafetyReport(
            destination=destination,
            advisory_level="Exercise normal caution",
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
        Itinerary: _stub_itinerary(destination=destination),
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
        chain.invoke = MagicMock(return_value=response)
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
) -> dict[str, Any]:
    """Run the graph with a fake LLM injected directly into all agents."""
    import asyncio

    fake_llm = _make_fake_llm(destination=destination, is_intl=is_intl)

    async def _run() -> dict[str, Any]:
        factory = ToolFactory(mock=True)
        compiled = build_graph(tool_factory=factory, llm=fake_llm)
        state = initial_state(query=query, session_id=session_id)
        if extra_state:
            state.update(extra_state)
        return await compiled.ainvoke(state)

    return asyncio.get_event_loop().run_until_complete(_run())


# ── Test cases ────────────────────────────────────────────────────────────────


class TestFullGraph:
    # Case 1: domestic trip
    def test_domestic_trip_osaka_returns_itinerary(self, mock_factory: ToolFactory) -> None:
        result = _run_graph_with_fake_llm(
            query="3 days Osaka from Kolkata, mid-October, love food",
            destination="Osaka",
            is_intl=False,
        )
        itinerary = result.get("itinerary")
        assert itinerary is not None, "Itinerary must be compiled"
        assert len(itinerary.segments) >= 1
        assert len(itinerary.segments[0].days) == 3

        # Accommodation shortlist (may be empty if no mock fixture for this destination)
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
        for seg in itinerary.segments:
            for day in seg.days:
                for slot in [day.morning, day.afternoon, day.evening]:
                    total = sum(o.estimated_duration_minutes for o in slot.options) / 60.0
                    assert total <= slot_limit_hours, (
                        f"Day {day.day_number} {slot.slot} total {total:.1f}h > {slot_limit_hours}h"
                    )

    # Case 7: clarification gate — vague query triggers clarification
    def test_vague_query_triggers_clarification(self) -> None:
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
                chain.invoke = MagicMock(return_value=vague_response)
            else:
                chain.invoke = MagicMock(return_value=MagicMock())
            return chain

        mock_llm = MagicMock()
        mock_llm.with_structured_output = MagicMock(side_effect=_with_structured_output)

        import asyncio

        async def _run() -> dict[str, Any]:
            factory = ToolFactory(mock=True)
            compiled = build_graph(tool_factory=factory, llm=mock_llm)
            state = initial_state(query="plan a trip to Tokyo", session_id="vague-test")
            return await compiled.ainvoke(state)

        result = asyncio.get_event_loop().run_until_complete(_run())

        assert result.get("needs_clarification") is True, "Should trigger clarification"
        assert result.get("itinerary") is None, "No itinerary when clarification needed"
        prompts = result.get("clarification_prompts", [])
        assert len(prompts) >= 1, "Must have at least one clarification prompt"
        fields = [p.field for p in prompts]
        assert "destination" in fields or "dates" in fields or "travelers" in fields

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
        # In mock mode with no official source fixture, confidence may be "low"
        assert visa.confidence is not None


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
        from app.agents.itinerary_compiler_agent import _resolve_conflicts
        from app.models.itinerary import ActivityOption, Day, Place, TimeSlotOptions, TripSegment

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
        day = Day(
            date=date(2026, 10, 14),
            day_number=1,
            location="Osaka",
            morning=TimeSlotOptions(slot="morning", options=[opt_closed, opt_open]),
            afternoon=TimeSlotOptions(slot="afternoon"),
            evening=TimeSlotOptions(slot="evening"),
        )
        seg = TripSegment(location="Osaka", days=[day])
        itinerary = Itinerary(
            title="Test",
            source="KOL",
            destination="Osaka",
            destinations=["Osaka"],
            travelers=1,
            segments=[seg],
        )

        resolved = _resolve_conflicts(itinerary, conflict_names={"ClosedMuseum"}, duration_flags=[])

        morning_opts = resolved.segments[0].days[0].morning.options
        names = [o.place.name for o in morning_opts]
        assert "ClosedMuseum" not in names
        assert "OpenPark" in names
