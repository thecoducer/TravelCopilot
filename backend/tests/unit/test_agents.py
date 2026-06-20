"""Unit tests for agents — all LLM calls are mocked via MagicMock.

No API keys are needed.  Tests verify:
  1. Agent returns the correct state keys
  2. Agent handles empty / missing inputs gracefully
  3. Conditional agents (visa, self_drive) no-op correctly
  4. The full LangGraph compiles without errors
"""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.agents.destination_context_agent import DestinationContextAgent
from app.agents.food_discovery_agent import FoodDiscoveryAgent
from app.agents.local_experiences_agent import LocalExperiencesAgent
from app.agents.orchestrator import OrchestratorAgent, quick_extract_days
from app.agents.scam_safety_agent import ScamSafetyAgent
from app.agents.self_drive_search_agent import SelfDriveSearchAgent
from app.agents.stay_analyst_agent import StayAnalystAgent
from app.agents.stay_search_agent import StaySearchAgent
from app.agents.transport_search_agent import TransportSearchAgent
from app.agents.visa_agent import VisaAgent
from app.graph.graph import build_graph
from app.graph.state import initial_state
from app.models.reports import (
    DestinationContextReport,
    ScamEntry,
    ScamSafetyReport,
    VisaReport,
)
from app.models.transport import StayOption
from app.models.user_profile import BudgetPreference, TripDates, UserProfile
from app.tools.factory import ToolFactory

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_tool_factory() -> ToolFactory:
    return ToolFactory(mock=True)


@pytest.fixture
def base_state() -> dict[str, Any]:
    return {
        **initial_state(query="3 days in Leh from Kolkata", session_id="test-session"),
        "source": "Kolkata",
        "destination": "Leh",
        "dates": TripDates(departure=date(2026, 7, 15), return_date=date(2026, 7, 18)),
        "travelers": 2,
        "budget": BudgetPreference(),
        "is_international": False,
        "self_drive_intent": False,
    }


def _make_llm(return_value: Any) -> MagicMock:
    """Build a mock LLM whose .with_structured_output().invoke() returns return_value."""
    mock_chain = MagicMock()
    mock_chain.invoke = MagicMock(return_value=return_value)
    mock_llm = MagicMock()
    mock_llm.with_structured_output = MagicMock(return_value=mock_chain)
    return mock_llm


# ── Graph compilation ─────────────────────────────────────────────────────────


class TestGraphCompilation:
    def test_graph_compiles_with_mock_factory(self, mock_tool_factory: ToolFactory) -> None:
        """The full planning graph must compile without errors."""
        graph = build_graph(tool_factory=mock_tool_factory)
        assert graph is not None

    def test_initial_state_has_required_keys(self) -> None:
        state = initial_state("test query", "sess-1")
        required_keys = [
            "query", "session_id", "source", "destination", "dates",
            "is_international", "self_drive_intent",
            "transport_legs_raw", "stays_raw", "experiences_raw",
            "reviews_summary", "restaurant_recommendations", "token_usage",
        ]
        for key in required_keys:
            assert key in state, f"Missing key: {key}"


# ── OrchestratorAgent ────────────────────────────────────────────────────────


class TestOrchestratorAgent:
    @pytest.mark.asyncio
    async def test_domestic_route_returns_correct_keys(self) -> None:
        from app.agents.orchestrator import _FieldConfidence, _ParsedQuery

        mock_response = _ParsedQuery(
            source_city=_FieldConfidence(value="Kolkata", confidence=0.95),
            destination=_FieldConfidence(value="Leh", confidence=0.95),
            departure_date="2026-07-15",
            trip_days=5,
            travelers=_FieldConfidence(value="2", confidence=1.0),
            budget_tier="mid",
            is_international=False,
            self_drive_intent=False,
            dates_confidence=0.9,
            confidence=0.9,
        )
        agent = OrchestratorAgent(llm=_make_llm(mock_response))
        result = await agent({"query": "5 days Leh from Kolkata", "session_id": "s1"})

        assert result.get("source") == "Kolkata"
        assert result.get("destination") == "Leh"
        assert result.get("is_international") is False
        assert result.get("self_drive_intent") is False
        assert result.get("travelers") == 2
        assert result.get("needs_clarification") is False

    @pytest.mark.asyncio
    async def test_self_drive_keyword_detected(self) -> None:
        from app.agents.orchestrator import _FieldConfidence, _ParsedQuery

        mock_response = _ParsedQuery(
            source_city=_FieldConfidence(value="Mumbai", confidence=0.9),
            destination=_FieldConfidence(value="Goa", confidence=0.95),
            departure_date="2026-08-01",
            trip_days=4,
            travelers=_FieldConfidence(value="1", confidence=0.9),
            budget_tier="mid",
            is_international=False,
            self_drive_intent=False,  # LLM misses it — keyword should catch it
            dates_confidence=0.9,
            confidence=0.8,
        )
        agent = OrchestratorAgent(llm=_make_llm(mock_response))
        result = await agent(
            {"query": "4 days Goa from Mumbai, want to rent a scooter", "session_id": "s2"}
        )
        assert result.get("self_drive_intent") is True

    @pytest.mark.asyncio
    async def test_clarification_triggered_when_destination_missing(self) -> None:
        from app.agents.orchestrator import _FieldConfidence, _ParsedQuery

        mock_response = _ParsedQuery(
            source_city=_FieldConfidence(value="unknown", confidence=0.3),
            destination=_FieldConfidence(value=None, confidence=0.0),
            departure_date=None,
            trip_days=3,
            travelers=_FieldConfidence(value=None, confidence=0.0),
            budget_tier="mid",
            is_international=False,
            self_drive_intent=False,
            dates_confidence=0.0,
            confidence=0.3,
        )
        agent = OrchestratorAgent(llm=_make_llm(mock_response))
        result = await agent({"query": "plan a trip", "session_id": "s3"})
        assert result.get("needs_clarification") is True
        prompts = result.get("clarification_prompts", [])
        assert len(prompts) >= 1

    @pytest.mark.asyncio
    async def test_fully_specified_query_no_clarification(self) -> None:
        from app.agents.orchestrator import _FieldConfidence, _ParsedQuery

        mock_response = _ParsedQuery(
            source_city=_FieldConfidence(value="Kolkata", confidence=0.95),
            destination=_FieldConfidence(value="Osaka", confidence=0.98),
            departure_date="2026-10-14",
            return_date="2026-10-17",
            trip_days=3,
            travelers=_FieldConfidence(value="2", confidence=1.0),
            budget_tier="mid",
            is_international=True,
            self_drive_intent=False,
            dates_confidence=0.95,
            confidence=0.95,
        )
        agent = OrchestratorAgent(llm=_make_llm(mock_response))
        result = await agent(
            {"query": "3 days Osaka from Kolkata in October with 2 people", "session_id": "s4"}
        )
        assert result.get("needs_clarification") is False

    def test_quick_extract_days(self) -> None:
        assert quick_extract_days("3 days trip to Goa") == 3
        assert quick_extract_days("10 day vacation") == 10
        assert quick_extract_days("weekend trip") is None


# ── DestinationContextAgent ───────────────────────────────────────────────────


class TestDestinationContextAgent:
    @pytest.mark.asyncio
    async def test_returns_destination_context_report(
        self, mock_tool_factory: ToolFactory, base_state: dict[str, Any]
    ) -> None:
        mock_report = DestinationContextReport(
            destination="Leh",
            travel_month="July",
            is_peak_season=True,
            season_label="Peak season",
            season_reason="Summer trekking season",
            crowd_level="High",
            crowd_notes="Many tourists in July",
            real_daily_cost=2500.0,
            currency_code="INR",
            seasonal_weather_summary="Sunny and dry",
        )
        agent = DestinationContextAgent(
            tool_factory=mock_tool_factory, llm=_make_llm(mock_report)
        )
        result = await agent(base_state)

        assert "destination_context_report" in result
        report = result["destination_context_report"]
        assert report.destination == "Leh"
        assert report.crowd_level in ("Low", "Moderate", "High", "Extreme")
        assert isinstance(report.real_daily_cost, float)

    @pytest.mark.asyncio
    async def test_fallback_on_empty_destination(
        self, mock_tool_factory: ToolFactory
    ) -> None:
        mock_report = DestinationContextReport(
            destination="",
            travel_month="July",
            is_peak_season=False,
            season_label="Unknown",
            season_reason="No data",
            crowd_level="Moderate",
            crowd_notes="",
            real_daily_cost=0.0,
            currency_code="USD",
            seasonal_weather_summary="",
        )
        agent = DestinationContextAgent(
            tool_factory=mock_tool_factory, llm=_make_llm(mock_report)
        )
        result = await agent({"destination": "", "session_id": "s"})
        assert "destination_context_report" in result


# ── ScamSafetyAgent ───────────────────────────────────────────────────────────


class TestScamSafetyAgent:
    @pytest.mark.asyncio
    async def test_returns_scam_safety_report(
        self, mock_tool_factory: ToolFactory, base_state: dict[str, Any]
    ) -> None:
        mock_report = ScamSafetyReport(
            destination="Leh",
            advisory_level="Exercise normal caution",
            top_scams=[
                ScamEntry(
                    name="Overcharging taxis",
                    description="Fixed-rate autorickshaws quote inflated prices",
                    how_to_avoid="Use Ola/Uber or agree fare before boarding",
                )
            ],
            emergency_contacts={"police": "100", "ambulance": "108"},
        )
        agent = ScamSafetyAgent(tool_factory=mock_tool_factory, llm=_make_llm(mock_report))
        result = await agent(base_state)

        assert "scam_safety_report" in result
        report = result["scam_safety_report"]
        assert len(report.top_scams) >= 1
        assert report.advisory_level


# ── VisaAgent ─────────────────────────────────────────────────────────────────


class TestVisaAgent:
    @pytest.mark.asyncio
    async def test_skips_domestic_trip(
        self, mock_tool_factory: ToolFactory, base_state: dict[str, Any]
    ) -> None:
        agent = VisaAgent(tool_factory=mock_tool_factory)
        state = {**base_state, "is_international": False}
        result = await agent(state)
        assert result["visa_report"] is None

    @pytest.mark.asyncio
    async def test_returns_visa_report_for_international(
        self, mock_tool_factory: ToolFactory, base_state: dict[str, Any]
    ) -> None:
        mock_report = VisaReport(
            passport_country="India",
            destination_country="Portugal",
            visa_required=True,
            visa_type="tourist",
            processing_timeline="10–15 business days",
        )
        agent = VisaAgent(tool_factory=mock_tool_factory, llm=_make_llm(mock_report))
        state = {
            **base_state,
            "destination": "Lisbon",
            "is_international": True,
            "user_profile": UserProfile(
                user_id="u1",
                passport_country="India",
                home_city="Mumbai",
            ),
        }
        result = await agent(state)

        assert "visa_report" in result
        report = result["visa_report"]
        assert report.visa_required is True
        assert report.visa_type == "tourist"


# ── TransportSearchAgent ──────────────────────────────────────────────────────


class TestTransportSearchAgent:
    @pytest.mark.asyncio
    async def test_returns_transport_legs_raw(
        self, mock_tool_factory: ToolFactory, base_state: dict[str, Any]
    ) -> None:
        from app.agents.transport_search_agent import _HubResult, _RouteCombo

        mock_hubs = _HubResult(
            route_combinations=[
                _RouteCombo(origin="KOL", destination="IXL", mode="flight"),
            ]
        )
        agent = TransportSearchAgent(
            tool_factory=mock_tool_factory, llm=_make_llm(mock_hubs)
        )
        result = await agent(base_state)

        assert "transport_legs_raw" in result
        assert "transport_hubs" in result
        # Mock flight tool should return some legs
        assert isinstance(result["transport_legs_raw"], dict)

    @pytest.mark.asyncio
    async def test_handles_empty_hub_tool_result(
        self, mock_tool_factory: ToolFactory, base_state: dict[str, Any]
    ) -> None:
        """Should not crash if hub tool returns no routes."""
        from app.agents.transport_search_agent import _HubResult

        agent = TransportSearchAgent(
            tool_factory=mock_tool_factory,
            llm=_make_llm(_HubResult(route_combinations=[])),
        )
        result = await agent({**base_state, "source": "", "destination": ""})
        assert "transport_legs_raw" in result


# ── StaySearchAgent ───────────────────────────────────────────────────────────


class TestStaySearchAgent:
    @pytest.mark.asyncio
    async def test_returns_stays_raw(
        self, mock_tool_factory: ToolFactory, base_state: dict[str, Any]
    ) -> None:
        agent = StaySearchAgent(tool_factory=mock_tool_factory)
        result = await agent(base_state)

        assert "stays_raw" in result
        assert isinstance(result["stays_raw"], list)

    @pytest.mark.asyncio
    async def test_handles_empty_hotel_results(self) -> None:
        """Should return empty list when hotel tool finds nothing."""
        factory = ToolFactory(mock=True)
        agent = StaySearchAgent(tool_factory=factory)
        # zzz destination has no fixture
        result = await agent(
            {**initial_state("trip", "s"), "destination": "zzz_no_fixture"}
        )
        assert result["stays_raw"] == []


# ── LocalExperiencesAgent ─────────────────────────────────────────────────────


class TestLocalExperiencesAgent:
    @pytest.mark.asyncio
    async def test_returns_experiences_raw(
        self, mock_tool_factory: ToolFactory, base_state: dict[str, Any]
    ) -> None:
        agent = LocalExperiencesAgent(tool_factory=mock_tool_factory)
        result = await agent(base_state)

        assert "experiences_raw" in result
        # Mock places tool returns fixture data — at least some experiences expected
        assert isinstance(result["experiences_raw"], list)


# ── StayAnalystAgent ──────────────────────────────────────────────────────────


class TestStayAnalystAgent:
    @pytest.mark.asyncio
    async def test_picks_best_stay_with_shortlist(self, base_state: dict[str, Any]) -> None:
        stays = [
            StayOption(
                name="Hotel A", address="Leh", city="Leh",
                price_per_night=3000, currency_code="INR", rating=4.5, review_count=200,
            ),
            StayOption(
                name="Hotel B", address="Leh", city="Leh",
                price_per_night=2800, currency_code="INR", rating=4.2, review_count=150,
            ),
            StayOption(
                name="Hotel C", address="Leh", city="Leh",
                price_per_night=2600, currency_code="INR", rating=4.0, review_count=120,
            ),
        ]
        from app.agents.stay_analyst_agent import _RankingOutput

        mock_result = _RankingOutput(
            ranked_indices=[0, 1, 2],
            personalization_reasons=[
                "Best rating for mid-range travellers.",
                "Good value.",
                "Affordable option.",
            ],
            rationale="Hotel A has the best rating.",
        )
        agent = StayAnalystAgent(llm=_make_llm(mock_result))
        result = await agent({**base_state, "stays_raw": stays})

        assert result["stays_pick"] is not None
        assert result["stays_pick"].name == "Hotel A"
        shortlist = result["stays_shortlist"]
        assert len(shortlist) >= 3
        for stay in shortlist:
            assert stay.personalization_reason, f"{stay.name} missing personalization_reason"
            assert stay.price_disclaimer

    @pytest.mark.asyncio
    async def test_empty_stays_returns_none(self) -> None:
        agent = StayAnalystAgent(llm=_make_llm(None))
        result = await agent({**initial_state("q", "s"), "stays_raw": []})
        assert result["stays_pick"] is None
        assert result["stays_shortlist"] == []


# ── SelfDriveSearchAgent ──────────────────────────────────────────────────────


class TestSelfDriveSearchAgent:
    @pytest.mark.asyncio
    async def test_skips_when_no_self_drive_intent(
        self, mock_tool_factory: ToolFactory, base_state: dict[str, Any]
    ) -> None:
        agent = SelfDriveSearchAgent(tool_factory=mock_tool_factory)
        result = await agent({**base_state, "self_drive_intent": False})
        assert result["self_drive_report"] is None

    @pytest.mark.asyncio
    async def test_returns_report_when_self_drive(
        self, mock_tool_factory: ToolFactory, base_state: dict[str, Any]
    ) -> None:
        from app.models.reports import SelfDriveReport

        mock_report = SelfDriveReport(
            destination="Goa",
            recommended_vehicle="Activa scooter",
            total_km_estimate=240.0,
            fuel_cost_estimate=620.0,
        )
        agent = SelfDriveSearchAgent(
            tool_factory=mock_tool_factory, llm=_make_llm(mock_report)
        )
        result = await agent(
            {
                **base_state,
                "destination": "Goa",
                "self_drive_intent": True,
            }
        )
        report = result["self_drive_report"]
        assert report is not None
        assert report.recommended_vehicle == "Activa scooter"


# ── FoodDiscoveryAgent ────────────────────────────────────────────────────────


class TestFoodDiscoveryAgent:
    @pytest.mark.asyncio
    async def test_returns_restaurant_recommendations(
        self, mock_tool_factory: ToolFactory, base_state: dict[str, Any]
    ) -> None:
        agent = FoodDiscoveryAgent(tool_factory=mock_tool_factory)
        result = await agent(base_state)

        assert "restaurant_recommendations" in result
        recs = result["restaurant_recommendations"]
        assert isinstance(recs, dict)
        # Should have at least 1 day of recommendations
        assert len(recs) >= 1

    @pytest.mark.asyncio
    async def test_handles_empty_experiences(
        self, mock_tool_factory: ToolFactory, base_state: dict[str, Any]
    ) -> None:
        agent = FoodDiscoveryAgent(tool_factory=mock_tool_factory)
        result = await agent({**base_state, "experiences_raw": []})
        # Should still try to find restaurants at the destination
        assert "restaurant_recommendations" in result
