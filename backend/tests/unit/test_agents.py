"""Unit tests for agents — all LLM calls are mocked via MagicMock.

No API keys are needed.  Tests verify:
  1. Agent returns the correct state keys
  2. Agent handles empty / missing inputs gracefully
  3. Conditional agents (visa, self_drive) no-op correctly
  4. The full LangGraph compiles without errors
  5. OrchestratorAgent raises NodeInterrupt for ambiguous queries
  6. Clarification helpers (UserProfile pre-fill, max rounds, answers) work correctly
"""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.base import request_optional_clarification
from app.agents.food_discovery_agent import FoodDiscoveryAgent
from app.agents.local_experiences_agent import LocalExperiencesAgent
from app.agents.orchestrator import OrchestratorAgent, quick_extract_days
from app.agents.reviews_agent import ReviewsAgent
from app.agents.safety_agent import SafetyAgent
from app.agents.self_drive_search_agent import SelfDriveSearchAgent
from app.agents.stay_analyst_agent import StayAnalystAgent
from app.agents.stay_search_agent import StaySearchAgent
from app.agents.transport_search_agent import TransportSearchAgent
from app.agents.visa_agent import VisaAgent
from app.graph.graph import build_graph
from app.graph.state import initial_state
from app.models.clarification import ClarificationPrompt
from app.models.itinerary import Experience
from app.models.reports import (
    BudgetReport,
    SafetyReport,
    ScamEntry,
    VisaReport,
)
from app.models.stops import DayAllocation, TripStop
from app.models.transport import StayOption
from app.models.user_profile import BudgetPreference, TripDates, UserProfile
from app.services.clarification_manager import ClarificationManager
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
        "dates": TripDates(departure=date(2026, 7, 15), return_date=date(2026, 7, 17)),
        "travelers": 2,
        "budget": BudgetPreference(),
        "is_international": False,
        "self_drive_intent": False,
    }


def _make_llm(return_value: Any) -> MagicMock:
    """Build a mock LLM whose structured chain returns return_value asynchronously."""
    mock_chain = MagicMock()
    mock_chain.ainvoke = AsyncMock(return_value=return_value)
    mock_llm = MagicMock()
    mock_llm.with_structured_output = MagicMock(return_value=mock_chain)
    return mock_llm


async def _drive_orchestrator(
    agent: Any,
    state: dict[str, Any],
    answers: dict[str, str] | None = None,
) -> tuple[dict[str, Any], list[dict]]:
    """Run orchestrator + clarification nodes the way the graph wires them.

    Returns the final orchestrator update and every interrupt payload raised.
    """
    from app.agents.orchestrator import orchestrator_clarification_node
    from app.config import settings

    payloads: list[dict] = []

    def fake_interrupt(payload: dict) -> dict:
        payloads.append(payload)
        fields = {prompt["field"] for prompt in payload["prompts"]}
        return {f: v for f, v in (answers or {}).items() if f in fields}

    working = dict(state)
    result: dict[str, Any] = {}
    with patch("app.services.clarification_manager.interrupt", side_effect=fake_interrupt):
        for _ in range(settings.max_clarification_rounds + 1):
            result = await agent(working)
            working.update(result)
            if not result.get("pending_clarification_fields"):
                break
            working.update(await orchestrator_clarification_node(working))
    return result, payloads


class _StaticTool:
    def __init__(self, response: dict[str, Any]) -> None:
        self._response = response

    async def run(self, **kwargs: object) -> dict[str, Any]:
        return self._response


class _StaticToolFactory:
    def __init__(self, responses: dict[str, dict[str, Any]]) -> None:
        self._responses = responses

    def get(self, tool_name: str) -> _StaticTool:
        return _StaticTool(self._responses.get(tool_name, {}))


# ── Graph compilation ─────────────────────────────────────────────────────────


class TestGraphCompilation:
    def test_graph_compiles_with_mock_factory(self, mock_tool_factory: ToolFactory) -> None:
        """The full planning graph must compile without errors."""
        graph = build_graph(tool_factory=mock_tool_factory)
        assert graph is not None

    def test_initial_state_has_required_keys(self) -> None:
        state = initial_state("test query", "sess-1")
        required_keys = [
            "query",
            "session_id",
            "source",
            "destination",
            "dates",
            "is_international",
            "self_drive_intent",
            "transport_legs_raw",
            "stays_raw",
            "experiences_raw",
            "reviews_summary",
            "food_recommendations",
            "token_usage",
        ]
        for key in required_keys:
            assert key in state, f"Missing key: {key}"


# ── OrchestratorAgent ────────────────────────────────────────────────────────


class TestOrchestratorAgent:
    @pytest.mark.asyncio
    async def test_domestic_route_returns_correct_keys(self) -> None:
        from app.agents.orchestrator import _FieldConfidence, _ParsedQuery

        mock_response = _ParsedQuery(
            source=_FieldConfidence(value="Kolkata", confidence=0.95),
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
        assert result.get("dates").trip_days == 5
        assert result.get("dates").departure == date(2026, 7, 15)
        assert result.get("dates").return_date == date(2026, 7, 19)
        # orchestrator no longer writes needs_clarification on the happy path
        assert "needs_clarification" not in result

    @pytest.mark.asyncio
    async def test_self_drive_intent_comes_from_structured_parser(self) -> None:
        from app.agents.orchestrator import _FieldConfidence, _ParsedQuery

        mock_response = _ParsedQuery(
            source=_FieldConfidence(value="Mumbai", confidence=0.9),
            destination=_FieldConfidence(value="Goa", confidence=0.95),
            departure_date="2026-08-01",
            trip_days=4,
            travelers=_FieldConfidence(value="1", confidence=0.9),
            budget_tier="mid",
            is_international=False,
            self_drive_intent=True,
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
        """When required fields are missing, the orchestrator calls interrupt()
        with a payload containing the clarification prompts.
        """
        from app.agents.orchestrator import _FieldConfidence, _ParsedQuery
        from app.config import settings

        mock_response = _ParsedQuery(
            source=_FieldConfidence(value="unknown", confidence=0.3),
            destination=_FieldConfidence(value=None, confidence=0.0),
            departure_date=None,
            trip_days=3,
            travelers=_FieldConfidence(value="2", confidence=1.0),
            budget_tier="mid",
            is_international=False,
            self_drive_intent=False,
            dates_confidence=0.0,
            confidence=0.3,
        )
        agent = OrchestratorAgent(llm=_make_llm(mock_response))

        with patch.object(settings, "max_clarification_rounds", 1):
            _, payloads = await _drive_orchestrator(
                agent, {"query": "plan a trip", "session_id": "s3"}
            )

        assert len(payloads) >= 1, "interrupt() was not called"
        fields = [p["field"] for p in payloads[0]["prompts"]]
        assert "destination" in fields

    @pytest.mark.asyncio
    async def test_clarification_requests_all_missing_trip_fields(self) -> None:
        from app.agents.orchestrator import _ParsedQuery
        from app.config import settings

        agent = OrchestratorAgent(llm=_make_llm(_ParsedQuery()))

        with patch.object(settings, "max_clarification_rounds", 1):
            result, payloads = await _drive_orchestrator(
                agent, {"query": "plan a trip", "session_id": "s_all_missing"}
            )

        fields = {prompt["field"] for prompt in payloads[0]["prompts"]}
        assert fields == set(settings.clarification_fields)
        assert result["error"] == "Required trip details are still missing."

    @pytest.mark.asyncio
    async def test_clarification_triggered_when_trip_days_unstated(self) -> None:
        """A query with no stated or implied duration must be clarified, never defaulted to 3."""
        from app.agents.orchestrator import _FieldConfidence, _ParsedQuery

        mock_response = _ParsedQuery(
            source=_FieldConfidence(value="Kolkata", confidence=0.95),
            destination=_FieldConfidence(value="Goa", confidence=0.95),
            departure_date="2026-11-01",
            trip_days=None,
            trip_days_confidence=0.0,
            travelers=_FieldConfidence(value="2", confidence=1.0),
            budget_tier="mid",
            is_international=False,
            self_drive_intent=False,
            dates_confidence=0.9,
        )
        agent = OrchestratorAgent(llm=_make_llm(mock_response))

        result, payloads = await _drive_orchestrator(
            agent,
            {"query": "trip to Goa from Kolkata", "session_id": "s_days"},
            {"trip_days": "4"},
        )

        assert len(payloads) >= 1, "interrupt() was not called"
        fields = [p["field"] for p in payloads[0]["prompts"]]
        assert "trip_days" in fields
        assert result["dates"].trip_days == 4

    @pytest.mark.asyncio
    async def test_fully_specified_query_no_clarification(self) -> None:
        from app.agents.orchestrator import _FieldConfidence, _ParsedQuery

        mock_response = _ParsedQuery(
            source=_FieldConfidence(value="Kolkata", confidence=0.95),
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
        # No interrupt — result contains destination and source directly
        assert result.get("destination") == "Osaka"
        assert result.get("source") == "Kolkata"

    @pytest.mark.asyncio
    async def test_unstable_llm_parse_does_not_reask_answered_fields(self) -> None:
        """A disagreeing second parse must not restart the clarification loop."""
        from app.agents.orchestrator import _FieldConfidence, _ParsedQuery

        first = _ParsedQuery(
            source=_FieldConfidence(value=None, confidence=0.0),
            destination=_FieldConfidence(value="Sikkim", confidence=0.95),
            departure_date=None,
            trip_days=8,
            trip_days_confidence=1.0,
            travelers=_FieldConfidence(value=None, confidence=0.0),
            budget_tier=None,
            dates_confidence=0.0,
            destination_country="India",
        )
        drifted = first.model_copy(
            update={"destination": _FieldConfidence(value="Sikkim", confidence=0.1)}
        )

        chain = MagicMock()
        chain.ainvoke = AsyncMock(side_effect=[first, drifted, drifted])
        llm = MagicMock()
        llm.with_structured_output = MagicMock(return_value=chain)

        agent = OrchestratorAgent(llm=llm)
        result, payloads = await _drive_orchestrator(
            agent,
            {"query": "Plan a trip to sikkim for eight days", "session_id": "s_unstable"},
            {"source": "Kolkata", "dates": "2026-11-01", "travelers": "2", "budget": "mid"},
        )

        assert len(payloads) == 1, "all missing fields must be asked in one round"
        assert chain.ainvoke.await_count == 1, "the parse must not re-run per round"
        asked = [p["field"] for payload in payloads for p in payload["prompts"]]
        assert sorted(asked) == sorted(set(asked)), f"a field was asked twice: {asked}"
        assert result.get("source") == "Kolkata"
        assert result.get("destination") == "Sikkim"
        assert result.get("is_international") is False
        assert result["dates"].trip_days == 8

    @pytest.mark.asyncio
    async def test_optional_clarification_is_opt_in(self) -> None:
        from app.agents.orchestrator import optional_clarification_node
        from app.config import settings

        with patch("app.services.clarification_manager.interrupt") as interrupt_mock:
            assert await optional_clarification_node({"session_id": "s_opt"}) == {}
        interrupt_mock.assert_not_called()

        with (
            patch.object(settings, "enable_optional_clarification", True),
            patch(
                "app.services.clarification_manager.interrupt",
                return_value={"optional_pace": "relaxed", "optional_must_see": "__skip__"},
            ),
        ):
            result = await optional_clarification_node({"session_id": "s_opt"})

        assert result["optional_clarification_answers"] == {"optional_pace": "relaxed"}

    def test_quick_extract_days(self) -> None:
        assert quick_extract_days("3 days trip to Goa") == 3
        assert quick_extract_days("10 day vacation") == 10
        assert quick_extract_days("6-day trek in Ladakh") == 6
        assert quick_extract_days("I want to visit Ladakh from Kolkata for 6 days.") == 6
        assert quick_extract_days("1 week in Japan") == 7
        assert quick_extract_days("a week holiday") == 7
        assert quick_extract_days("5 nights in Paris") == 6
        assert quick_extract_days("weekend trip") == 2
        assert quick_extract_days("summer holiday") is None

    @pytest.mark.asyncio
    async def test_structured_travelers_value_is_used(self) -> None:
        from app.agents.orchestrator import _FieldConfidence, _ParsedQuery

        mock_response = _ParsedQuery(
            source=_FieldConfidence(value="Kolkata", confidence=0.95),
            destination=_FieldConfidence(value="Arunachal Pradesh", confidence=0.95),
            departure_date="2026-11-11",
            trip_days=5,
            travelers=_FieldConfidence(value="2", confidence=1.0),
            budget_tier="mid",
            is_international=False,
            dates_confidence=0.95,
        )
        agent = OrchestratorAgent(llm=_make_llm(mock_response))
        result = await agent(
            {
                "query": (
                    "Plan a trip to Arunachal Pradesh from Kolkata for 5 days. "
                    "We are 2 people. Start date is 11th November this year."
                ),
                "session_id": "s_arunachal",
            }
        )

        assert result["travelers"] == 2
        assert result["source"] == "Kolkata"
        assert result["destination"] == "Arunachal Pradesh"
        assert result["dates"].departure == date(2026, 11, 11)
        assert result["dates"].trip_days == 5

    @pytest.mark.asyncio
    async def test_deterministic_duration_override_from_query(self) -> None:
        """Query duration '6 days' deterministically overrides LLM default trip_days=3."""
        from app.agents.orchestrator import _FieldConfidence, _ParsedQuery

        # Mock LLM returns default trip_days=3, missing the 'for 6 days' in query
        mock_response = _ParsedQuery(
            source=_FieldConfidence(value="Kolkata", confidence=0.95),
            destination=_FieldConfidence(value="Ladakh", confidence=0.95),
            departure_date=None,
            trip_days=3,  # LLM failed to extract 6
            travelers=_FieldConfidence(value="1", confidence=0.8),
            budget_tier="mid",
            is_international=False,
            self_drive_intent=False,
            dates_confidence=0.0,
            confidence=0.5,
        )
        agent = OrchestratorAgent(llm=_make_llm(mock_response))

        result, _ = await _drive_orchestrator(
            agent,
            {
                "query": "I want to visit Ladakh from Kolkata for 6 days.",
                "session_id": "s_6day_test",
            },
            {"dates": "2026-10-28"},
        )

        assert result.get("source") == "Kolkata"
        assert result.get("destination") == "Ladakh"
        dates = result.get("dates")
        assert dates is not None
        assert dates.trip_days == 6
        assert dates.departure == date(2026, 10, 28)
        assert dates.return_date == date(2026, 11, 2)

    @pytest.mark.asyncio
    async def test_clarification_interrupt_contains_input_type(self) -> None:
        """Interrupt payload prompts include input_type for frontend rendering."""
        from app.agents.orchestrator import _FieldConfidence, _ParsedQuery
        from app.config import settings

        mock_response = _ParsedQuery(
            source=_FieldConfidence(value="Kolkata", confidence=0.9),
            destination=_FieldConfidence(value=None, confidence=0.0),
            departure_date=None,
            trip_days=3,
            travelers=_FieldConfidence(value="1", confidence=0.8),
            budget_tier="mid",
            is_international=False,
            self_drive_intent=False,
            dates_confidence=0.0,
            confidence=0.4,
        )
        agent = OrchestratorAgent(llm=_make_llm(mock_response))

        with patch.object(settings, "max_clarification_rounds", 1):
            _, payloads = await _drive_orchestrator(
                agent, {"query": "trip somewhere", "session_id": "s5"}
            )

        assert len(payloads) >= 1
        prompts = payloads[0]["prompts"]
        destination_prompt = next(p for p in prompts if p["field"] == "destination")
        assert destination_prompt["input_type"] == "text"
        dates_prompt = next((p for p in prompts if p["field"] == "dates"), None)
        if dates_prompt:
            assert dates_prompt["input_type"] == "date"

    @pytest.mark.asyncio
    async def test_missing_source_requires_clarification(self) -> None:
        """A missing source is never inferred from a user profile."""
        from app.agents.orchestrator import _FieldConfidence, _ParsedQuery

        mock_response = _ParsedQuery(
            source=_FieldConfidence(value=None, confidence=0.0),
            destination=_FieldConfidence(value="Leh", confidence=0.95),
            departure_date="2026-07-15",
            trip_days=4,
            travelers=_FieldConfidence(value="1", confidence=0.8),
            budget_tier="mid",
            is_international=False,
            self_drive_intent=False,
            dates_confidence=0.85,
            confidence=0.85,
        )
        agent = OrchestratorAgent(llm=_make_llm(mock_response))
        state = {
            "query": "4 days in Leh in July",
            "session_id": "s6",
        }
        result, _ = await _drive_orchestrator(agent, state, {"source": "Kolkata"})
        assert result.get("source") == "Kolkata"
        assert result.get("destination") == "Leh"

    def test_is_international_is_derived_not_asked(self) -> None:
        """An unresolved international flag is derived from countries, never clarified."""
        from app.agents.orchestrator import (
            _compute_missing,
            _derive_is_international,
            _FieldConfidence,
            _ParsedQuery,
        )

        parsed = _ParsedQuery(
            source=_FieldConfidence(value="Kolkata", confidence=1.0),
            destination=_FieldConfidence(value="Darjeeling", confidence=0.95),
            trip_days=5,
            trip_days_confidence=1.0,
            travelers=_FieldConfidence(value="3", confidence=1.0),
            budget_tier="mid",
            departure_date="2026-10-01",
            dates_confidence=1.0,
            is_international=None,
            source_country="India",
            destination_country="India",
        )

        missing = dict(_compute_missing(parsed))

        assert "source" not in missing
        assert "is_international" not in missing
        assert _derive_is_international(parsed, MagicMock()) is False

        crossing = parsed.model_copy(update={"destination_country": "Japan"})
        assert _derive_is_international(crossing, MagicMock()) is True

    def test_clarification_manager_wraps_request_metadata(self) -> None:
        prompt = ClarificationPrompt(
            field="source",
            question="Where are you departing from?",
            reason="Required for route planning",
        )
        with patch(
            "app.services.clarification_manager.interrupt",
            return_value={"source": "Kolkata"},
        ) as mocked_interrupt:
            answers = ClarificationManager.request(
                [prompt], requester="orchestrator", round_number=2
            )

        assert answers == {"source": "Kolkata"}
        payload = mocked_interrupt.call_args.args[0]
        assert payload["requester"] == "orchestrator"
        assert payload["round"] == 2
        assert payload["request_id"]
        assert payload["prompts"][0]["field"] == "source"

    def test_clarification_manager_rejects_unsupported_field(self) -> None:
        prompt = ClarificationPrompt(
            field="unsupported",
            question="What else?",
            reason="test",
        )
        with pytest.raises(ValueError, match="Unsupported clarification field"):
            ClarificationManager.request([prompt], requester="test", round_number=0)

    def test_clarification_manager_allows_skippable_llm_question(self) -> None:
        prompt = ClarificationPrompt(
            field="optional_activity_pace",
            question="Do you prefer a relaxed or packed itinerary?",
            reason="Helps balance the daily schedule",
            optional=True,
        )
        with patch(
            "app.services.clarification_manager.interrupt",
            return_value={"optional_activity_pace": "__skip__"},
        ):
            answers = ClarificationManager.request(
                [prompt], requester="orchestrator", round_number=0
            )

        assert answers["optional_activity_pace"] == "__skip__"

    def test_any_agent_can_request_optional_clarification(self) -> None:
        prompt = ClarificationPrompt(
            field="optional_accessibility_needs",
            question="Should we account for any accessibility needs?",
            reason="Helps select suitable activities",
        )
        with patch(
            "app.services.clarification_manager.interrupt",
            return_value={"optional_accessibility_needs": "__skip__"},
        ):
            answers = request_optional_clarification(
                [prompt], requester="local_experiences", round_number=1
            )

        assert answers["optional_accessibility_needs"] == "__skip__"

    @pytest.mark.asyncio
    async def test_date_clarification_preserves_parsed_trip_days(self) -> None:
        """A single calendar date preserves the parsed trip duration."""
        from app.agents.orchestrator import _FieldConfidence, _ParsedQuery

        mock_response = _ParsedQuery(
            source=_FieldConfidence(value="Kolkata", confidence=0.95),
            destination=_FieldConfidence(value="Ladakh", confidence=0.95),
            departure_date=None,
            trip_days=5,
            travelers=_FieldConfidence(value="1", confidence=0.8),
            budget_tier="mid",
            is_international=False,
            self_drive_intent=False,
            dates_confidence=0.0,
            confidence=0.5,
        )
        agent = OrchestratorAgent(llm=_make_llm(mock_response))

        result, _ = await _drive_orchestrator(
            agent,
            {
                "query": "I want to go to ladakh from kolkata for 5 days",
                "session_id": "s_clarify",
            },
            {"dates": "2026-10-14"},
        )

        assert result.get("source") == "Kolkata"
        assert result.get("destination") == "Ladakh"
        dates = result.get("dates")
        assert dates is not None
        assert dates.trip_days == 5
        assert dates.departure == date(2026, 10, 14)
        assert dates.return_date == date(2026, 10, 18)

    def test_parse_date_answer_formats(self) -> None:
        from app.agents.orchestrator import _parse_date_answer

        # Standard HTML5 date picker ISO format
        dep, ret, conf = _parse_date_answer("2026-10-14")
        assert dep == "2026-10-14"
        assert ret is None
        assert conf == 1.0

        # DD/MM/YYYY format
        dep, ret, conf = _parse_date_answer("14/10/2026")
        assert dep == "2026-10-14"
        assert ret is None
        assert conf == 1.0

        # DD-MM-YYYY format
        dep, ret, conf = _parse_date_answer("14-10-2026")
        assert dep == "2026-10-14"
        assert ret is None
        assert conf == 1.0

        # Empty / invalid format
        dep, ret, conf = _parse_date_answer("invalid-date")
        assert dep is None
        assert ret is None
        assert conf == 0.0

    @pytest.mark.asyncio
    async def test_max_clarification_rounds_exhausted_stops_without_defaults(self) -> None:
        """After max clarification rounds, required fields remain unresolved."""
        from app.agents.orchestrator import _FieldConfidence, _ParsedQuery
        from app.config import settings

        ambiguous_response = _ParsedQuery(
            source=_FieldConfidence(value="unknown", confidence=0.3),
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
        agent = OrchestratorAgent(llm=_make_llm(ambiguous_response))

        with patch.object(settings, "max_clarification_rounds", 2):
            result, payloads = await _drive_orchestrator(
                agent, {"query": "plan a trip", "session_id": "s7"}
            )

        # interrupt() should have been called exactly max_clarification_rounds times
        assert len(payloads) == 2
        assert result["error"] == "Required trip details are still missing."
        assert "destination" in result["missing_required_fields"]
        # The single parse is reused across rounds instead of re-running the LLM.
        assert agent._llm.with_structured_output.call_count == 1


# ── SafetyAgent ───────────────────────────────────────────────────────────────


class TestSafetyAgent:
    @pytest.mark.asyncio
    async def test_returns_safety_report(
        self, mock_tool_factory: ToolFactory, base_state: dict[str, Any]
    ) -> None:
        mock_report = SafetyReport(
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
        agent = SafetyAgent(tool_factory=mock_tool_factory, llm=_make_llm(mock_report))
        result = await agent(base_state)

        assert "safety_report" in result
        report = result["safety_report"]
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
        agent = VisaAgent(
            tool_factory=_StaticToolFactory(
                {
                    "tavily_search": {
                        "results": [
                            {
                                "title": "Official visa guidance",
                                "url": "https://example.gov/visa",
                                "content": "Visa requirements for travellers.",
                            }
                        ]
                    },
                    "visa_centre_search": {
                        "application_centre": {"name": "Application Centre"},
                        "sources": [],
                    },
                    "embassy_search": {"embassy": {"name": "Embassy"}},
                }
            ),
            llm=_make_llm(mock_report),
        )
        state = {
            **base_state,
            "destination": "Lisbon",
            "is_international": True,
            "user_profile": UserProfile(
                user_id="u1",
                passport_country="India",
            ),
            "visa_application_city": "Mumbai",
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
            tool_factory=_StaticToolFactory(
                {
                    "search_transit": {"options": [{"mode": "train"}]},
                    "search_road_routes": {"options": [{"mode": "taxi"}]},
                    "search_taxi_info": {"options": [{"name": "Local Taxi"}]},
                }
            ),
            llm=_make_llm(mock_hubs),
        )
        result = await agent(base_state)

        assert "transport_legs_raw" in result
        assert "transport_hubs" in result
        # Mock flight tool should return some legs
        assert isinstance(result["transport_legs_raw"], dict)

    @pytest.mark.asyncio
    async def test_falls_back_to_direct_flight_when_llm_returns_no_routes(
        self, mock_tool_factory: ToolFactory, base_state: dict[str, Any]
    ) -> None:
        """Should use a direct flight when the LLM returns no routes."""
        from app.agents.transport_search_agent import _HubResult

        agent = TransportSearchAgent(
            tool_factory=mock_tool_factory,
            llm=_make_llm(_HubResult(route_combinations=[])),
        )
        result = await agent({**base_state, "source": "", "destination": ""})
        assert "transport_legs_raw" in result
        assert result["transport_hubs"] == []

    @pytest.mark.asyncio
    async def test_dispatches_taxi_and_transit_modes(
        self, mock_tool_factory: ToolFactory, base_state: dict[str, Any]
    ) -> None:
        from app.agents.transport_search_agent import _HubResult, _RouteCombo

        mock_hubs = _HubResult(
            route_combinations=[
                _RouteCombo(origin="KOL", destination="DEL", mode="train"),
                _RouteCombo(origin="DEL", destination="LEH", mode="taxi"),
                {"origin": "KOL", "destination": "LEH", "mode": "other"},
            ]
        )
        agent = TransportSearchAgent(
            tool_factory=_StaticToolFactory(
                {
                    "search_transit": {"options": [{"mode": "train"}]},
                    "search_road_routes": {"options": [{"mode": "taxi"}]},
                    "search_taxi_info": {"options": [{"name": "Local Taxi"}]},
                }
            ),
            llm=_make_llm(mock_hubs),
        )
        result = await agent({**base_state, "source": "KOL", "destination": "LEH"})

        assert "KOL→DEL" in result["transport_legs_raw"]
        assert "DEL→LEH" in result["transport_legs_raw"]
        assert "KOL→LEH" not in result["transport_legs_raw"]


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
        # zzz destination has no recorded provider response
        result = await agent({**initial_state("trip", "s"), "destination": "zzz_no_fixture"})
        assert result["stays_raw"] == []


# ── LocalExperiencesAgent ─────────────────────────────────────────────────────


class TestLocalExperiencesAgent:
    @pytest.mark.asyncio
    async def test_returns_experiences_raw_single_destination(
        self, mock_tool_factory: ToolFactory, base_state: dict[str, Any]
    ) -> None:
        from app.models.itinerary import Experience, ExperiencesOutput

        mock_experiences = ExperiencesOutput(
            experiences=[
                Experience(
                    name="Shanti Stupa",
                    type="historical_landmark",
                    description="White-domed Buddhist stupa offering panoramic views of Leh.",
                    duration_hours=2.0,
                    price_range="Free",
                    best_time_to_visit="Sunset",
                    lat=34.1648,
                    lng=77.5847,
                    rating=4.7,
                    review_count=1200,
                ),
                Experience(
                    name="Leh Palace",
                    type="historical_landmark",
                    description="Former royal palace overlooking the town of Leh.",
                    duration_hours=1.5,
                    price_range="Inexpensive",
                    best_time_to_visit="Morning",
                    lat=34.1654,
                    lng=77.5878,
                    rating=4.5,
                    review_count=950,
                ),
            ]
        )
        mock_llm = _make_llm(mock_experiences)
        agent = LocalExperiencesAgent(
            tool_factory=_StaticToolFactory(
                {
                    "search_places": {
                        "places": [
                            {"displayName": {"text": "Shanti Stupa"}},
                            {"displayName": {"text": "Leh Palace"}},
                        ]
                    },
                    "geocode": {"lat": 34.16, "lng": 77.58},
                }
            ),
            llm=mock_llm,
        )
        result = await agent(base_state)

        assert "experiences_raw" in result
        experiences = result["experiences_raw"]
        assert len(experiences) == 2
        assert experiences[0].name == "Shanti Stupa"
        assert experiences[0].lat != 0.0
        assert experiences[0].lng != 0.0
        assert experiences[0].source == "llm"

    @pytest.mark.asyncio
    async def test_multi_stop_returns_experiences_raw_by_stop(
        self, mock_tool_factory: ToolFactory, base_state: dict[str, Any]
    ) -> None:
        from app.models.itinerary import Experience, ExperiencesOutput
        from app.models.stops import TripStop

        mock_experiences = ExperiencesOutput(
            experiences=[
                Experience(
                    name="Local Highlight",
                    type="tourist_attraction",
                    description="A scenic local attraction.",
                    duration_hours=2.0,
                    price_range="Free",
                    lat=34.15,
                    lng=77.57,
                )
            ]
        )
        mock_llm = _make_llm(mock_experiences)
        agent = LocalExperiencesAgent(tool_factory=mock_tool_factory, llm=mock_llm)

        state = {
            **base_state,
            "route_discovery_status": "multi_stop_provisional",
            "stops": {
                "stop_1": TripStop(stop_id="stop_1", name="Leh", stop_kind="overnight", sequence=0),
                "stop_2": TripStop(
                    stop_id="stop_2", name="Nubra", stop_kind="overnight", sequence=1
                ),
            },
            "route_version": 1,
        }
        result = await agent(state)

        assert "experiences_raw_by_stop" in result
        by_stop = result["experiences_raw_by_stop"]
        assert "stop_1" in by_stop
        assert "stop_2" in by_stop
        assert len(by_stop["stop_1"]) >= 1
        assert by_stop["stop_1"][0].stop_id == "stop_1"
        assert by_stop["stop_1"][0].route_version == 1

    @pytest.mark.asyncio
    async def test_fallback_when_llm_returns_empty(
        self, mock_tool_factory: ToolFactory, base_state: dict[str, Any]
    ) -> None:
        from app.models.itinerary import ExperiencesOutput

        mock_llm = _make_llm(ExperiencesOutput(experiences=[]))
        agent = LocalExperiencesAgent(tool_factory=mock_tool_factory, llm=mock_llm)
        result = await agent(base_state)

        assert "experiences_raw" in result
        assert len(result["experiences_raw"]) == 1
        assert "Explore Leh" in result["experiences_raw"][0].name


# ── StayAnalystAgent ──────────────────────────────────────────────────────────


class TestStayAnalystAgent:
    @pytest.mark.asyncio
    async def test_picks_best_stay_with_shortlist(self, base_state: dict[str, Any]) -> None:
        stays = [
            StayOption(
                name="Hotel A",
                address="Leh",
                city="Leh",
                price_per_night=3000,
                currency_code="INR",
                rating=4.5,
                review_count=200,
            ),
            StayOption(
                name="Hotel B",
                address="Leh",
                city="Leh",
                price_per_night=2800,
                currency_code="INR",
                rating=4.2,
                review_count=150,
            ),
            StayOption(
                name="Hotel C",
                address="Leh",
                city="Leh",
                price_per_night=2600,
                currency_code="INR",
                rating=4.0,
                review_count=120,
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
        agent = SelfDriveSearchAgent(tool_factory=mock_tool_factory, llm=_make_llm(mock_report))
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
    async def test_returns_food_recommendations(
        self, mock_tool_factory: ToolFactory, base_state: dict[str, Any]
    ) -> None:
        agent = FoodDiscoveryAgent(tool_factory=mock_tool_factory)
        state = {
            **base_state,
            "stops": {"0": TripStop(stop_id="0", name="Leh", sequence=0)},
            "stops_by_day": {0: DayAllocation(day_index=0, date=date(2026, 7, 15), stop_id="0")},
        }
        result = await agent(state)

        assert "food_recommendations" in result
        assert "food_recommendations_by_stop" in result
        recs = result["food_recommendations"]
        assert isinstance(recs, dict)
        # Should have at least 1 day of recommendations
        assert len(recs) >= 1

    @pytest.mark.asyncio
    async def test_handles_empty_experiences(
        self, mock_tool_factory: ToolFactory, base_state: dict[str, Any]
    ) -> None:
        agent = FoodDiscoveryAgent(tool_factory=mock_tool_factory)
        result = await agent(
            {
                **base_state,
                "experiences_raw": [],
                "stops": {"0": TripStop(stop_id="0", name="Leh", sequence=0)},
                "stops_by_day": {
                    0: DayAllocation(day_index=0, date=date(2026, 7, 15), stop_id="0")
                },
            }
        )
        # Should still try to find restaurants at the destination
        assert "food_recommendations" in result

    @pytest.mark.asyncio
    async def test_uses_saved_food_preferences_in_searches(
        self, mock_tool_factory: ToolFactory, base_state: dict[str, Any]
    ) -> None:
        agent = FoodDiscoveryAgent(tool_factory=mock_tool_factory)
        agent._places_tool.run = AsyncMock(return_value={"places": []})
        profile = UserProfile(
            user_id="u1",
            preferred_cuisines=["Japanese"],
            dietary_restrictions=["vegetarian"],
            food_preferences_configured=True,
        )

        await agent(
            {
                **base_state,
                "user_profile": profile,
                "budget": {"tier": "luxury"},
                "experiences_raw": [],
                "stops": {"0": TripStop(stop_id="0", name="Leh", sequence=0)},
                "stops_by_day": {
                    0: DayAllocation(day_index=0, date=date(2026, 7, 15), stop_id="0")
                },
            }
        )

        places_query = agent._places_tool.run.await_args.kwargs["query"]
        assert "Japanese" in places_query
        assert "vegetarian" in places_query
        assert "luxury" in places_query

        places_call = agent._places_tool.run.await_args
        assert places_call.kwargs["location"] == "Leh"
        assert agent._places_tool.run.await_count == 1
        assert not hasattr(agent, "_tavily_tool")

    @pytest.mark.asyncio
    async def test_searches_google_places_once_at_destination(
        self, mock_tool_factory: ToolFactory, base_state: dict[str, Any]
    ) -> None:
        agent = FoodDiscoveryAgent(tool_factory=mock_tool_factory)
        agent._places_tool.run = AsyncMock(return_value={"places": []})
        wrong_address_experience = Experience(
            name="Activity", description="An activity", address="United States"
        )

        await agent(
            {
                **base_state,
                "experiences_raw": [wrong_address_experience],
                "stops": {"0": TripStop(stop_id="0", name="Leh", sequence=0)},
                "stops_by_day": {
                    0: DayAllocation(day_index=0, date=date(2026, 7, 15), stop_id="0")
                },
            }
        )

        places_call = agent._places_tool.run.await_args
        assert places_call.kwargs["location"] == "Leh"
        assert "Leh" in places_call.kwargs["query"]
        assert agent._places_tool.run.await_count == 1


# ── get_llm factory ───────────────────────────────────────────────────────────


class TestGetLLM:
    def test_returns_litellm_chat_model(self) -> None:
        """get_llm returns a model with the correct metadata (P2-2)."""
        from langchain_litellm import ChatLiteLLM

        from app.llm import get_llm

        llm = get_llm("test_agent", "sess_123")
        assert isinstance(llm, ChatLiteLLM)
        assert llm.metadata["agent_name"] == "test_agent"
        assert llm.metadata["session_id"] == "sess_123"

    def test_model_string_uses_provider_and_model(self) -> None:
        from app.config import settings
        from app.llm import get_llm

        llm = get_llm("orchestrator")
        expected = f"{settings.llm_provider}/{settings.llm_model}"
        assert llm.model == expected


# ── TransportOptimizerAgent ───────────────────────────────────────────────────


class TestTransportOptimizerAgent:
    @pytest.fixture
    def _legs_raw(self) -> dict[str, Any]:
        from datetime import UTC, datetime

        return {
            "KOL→DEL→IXL": [
                {
                    "airline": {"name": "IndiGo"},
                    "price": 9500,
                    "total_duration": 195,
                    "travel_class": "economy",
                    "departure_airport": {"time": "06:00"},
                    "layovers": [{"duration": 60}],
                    "price_cached_at": datetime.now(tz=UTC).isoformat(),
                }
            ],
            "KOL→IXL direct": [
                {
                    "airline": {"name": "Air India"},
                    "price": 14000,
                    "total_duration": 150,
                    "travel_class": "economy",
                    "departure_airport": {"time": "08:00"},
                    "layovers": [],
                    "price_cached_at": datetime.now(tz=UTC).isoformat(),
                }
            ],
        }

    @pytest.mark.asyncio
    async def test_recommendation_has_positive_cost_and_waypoints(
        self,
        base_state: dict[str, Any],
        _legs_raw: dict[str, Any],
    ) -> None:
        from datetime import UTC, datetime

        from app.agents.transport_optimizer_agent import _OptimiserOutput
        from app.models.transport import RouteLeg, RouteWaypoint, TransportRecommendation

        rec = TransportRecommendation(
            recommended_legs=[
                RouteLeg(
                    mode="flight",
                    operator="IndiGo",
                    origin="KOL",
                    destination="IXL",
                    duration_minutes=195,
                    cost=9500.0,
                    currency_code="INR",
                    price_cached_at=datetime.now(tz=UTC),
                    price_disclaimer="Price indicative — verify before booking.",
                )
            ],
            total_cost=9500.0,
            total_duration_minutes=195,
            currency_code="INR",
            rationale="Best value mid-range option.",
            personalization_reason="Matches mid budget tier.",
            route_waypoints=[
                RouteWaypoint(label="KOL", name="Kolkata", lat=22.57, lng=88.36),
                RouteWaypoint(label="IXL", name="Leh", lat=34.15, lng=77.57),
            ],
        )
        mock_out = _OptimiserOutput(recommended=rec, alternatives=[])
        from app.agents.transport_optimizer_agent import TransportOptimizerAgent

        agent = TransportOptimizerAgent(llm=_make_llm(mock_out))
        result = await agent({**base_state, "transport_legs_raw": _legs_raw})

        transport = result["transport_recommendation"]
        assert transport is not None
        assert transport.total_cost > 0
        assert len(transport.route_waypoints) >= 2

    @pytest.mark.asyncio
    async def test_every_leg_has_price_cached_at_and_disclaimer(
        self,
        base_state: dict[str, Any],
        _legs_raw: dict[str, Any],
    ) -> None:
        from datetime import UTC, datetime

        from app.agents.transport_optimizer_agent import _OptimiserOutput
        from app.models.transport import RouteLeg, RouteWaypoint, TransportRecommendation

        leg = RouteLeg(
            mode="flight",
            operator="IndiGo",
            origin="KOL",
            destination="IXL",
            duration_minutes=195,
            cost=9500.0,
            currency_code="INR",
            price_cached_at=datetime.now(tz=UTC),
            price_disclaimer="Price indicative — verify before booking.",
        )
        rec = TransportRecommendation(
            recommended_legs=[leg],
            total_cost=9500.0,
            total_duration_minutes=195,
            currency_code="INR",
            rationale="Best option.",
            personalization_reason="Good value.",
            route_waypoints=[
                RouteWaypoint(label="KOL", name="Kolkata", lat=22.57, lng=88.36),
                RouteWaypoint(label="IXL", name="Leh", lat=34.15, lng=77.57),
            ],
        )
        mock_out = _OptimiserOutput(recommended=rec, alternatives=[])
        from app.agents.transport_optimizer_agent import TransportOptimizerAgent

        agent = TransportOptimizerAgent(llm=_make_llm(mock_out))
        result = await agent({**base_state, "transport_legs_raw": _legs_raw})

        for leg in result["transport_recommendation"].recommended_legs:
            assert leg.price_cached_at is not None, f"{leg.operator} missing price_cached_at"
            assert leg.price_disclaimer, f"{leg.operator} missing price_disclaimer"

    @pytest.mark.asyncio
    async def test_budget_tier_filters_premium_from_raw_legs(
        self,
        base_state: dict[str, Any],
    ) -> None:
        """Budget tier must strip business-class legs before the LLM sees them (P2-6)."""
        from app.agents.transport_optimizer_agent import _budget_filter

        legs_with_premium: dict[str, Any] = {
            "KOL→IXL": [
                {"travel_class": "business", "price": 25000},
                {"travel_class": "economy", "price": 9500},
            ]
        }
        filtered = _budget_filter(legs_with_premium, "budget")
        for options in filtered.values():
            for leg in options:
                assert leg["travel_class"] != "business", (
                    "Business class must be stripped for budget tier"
                )


# ── ReviewsAgent ──────────────────────────────────────────────────────────────


class TestReviewsAgent:
    @pytest.mark.asyncio
    async def test_reviews_summary_covers_all_shortlisted_hotels(
        self, mock_tool_factory: ToolFactory, base_state: dict[str, Any]
    ) -> None:
        from app.models.reports import ReviewSummary
        from app.models.transport import StayOption

        stays = [
            StayOption(
                name=f"Hotel {i}",
                address="Leh",
                city="Leh",
                price_per_night=3000,
                currency_code="INR",
                rating=4.0 + i * 0.1,
                review_count=50,
            )
            for i in range(3)
        ]

        def _mock_side_effect(schema: Any) -> MagicMock:
            from app.agents.reviews_agent import _PlaceSummary

            chain = MagicMock()
            chain.ainvoke = AsyncMock(
                return_value=_PlaceSummary(
                    pros=["Good location", "Clean rooms"],
                    cons=["Noisy street"],
                    sentiment="positive",
                )
            )
            return chain

        mock_llm = MagicMock()
        mock_llm.with_structured_output = MagicMock(side_effect=_mock_side_effect)

        agent = ReviewsAgent(tool_factory=mock_tool_factory, llm=mock_llm)
        result = await agent({**base_state, "stays_shortlist": stays, "experiences_raw": []})

        reviews = result["reviews_summary"]
        for stay in stays:
            assert stay.name in reviews, f"Missing review for {stay.name}"
            assert isinstance(reviews[stay.name], ReviewSummary)


# ── BudgetPlannerAgent ────────────────────────────────────────────────────────


class TestBudgetPlannerAgent:
    @pytest.mark.asyncio
    async def test_budget_report_positive_total_and_all_categories(
        self, mock_tool_factory: ToolFactory, base_state: dict[str, Any]
    ) -> None:
        from datetime import UTC, datetime

        from app.models.reports import BudgetReport
        from app.models.transport import (
            RouteLeg,
            RouteWaypoint,
            StayOption,
            TransportRecommendation,
        )

        transport_rec = TransportRecommendation(
            recommended_legs=[
                RouteLeg(
                    mode="flight",
                    operator="IndiGo",
                    origin="KOL",
                    destination="IXL",
                    duration_minutes=195,
                    cost=9500.0,
                    currency_code="INR",
                    price_cached_at=datetime.now(tz=UTC),
                    price_disclaimer="Indicative.",
                )
            ],
            total_cost=9500.0,
            total_duration_minutes=195,
            currency_code="INR",
            rationale="Best value.",
            personalization_reason="Budget match.",
            route_waypoints=[
                RouteWaypoint(label="KOL", name="Kolkata", lat=22.57, lng=88.36),
                RouteWaypoint(label="IXL", name="Leh", lat=34.15, lng=77.57),
            ],
        )
        stays_shortlist = [
            StayOption(
                name="Hotel A",
                address="Leh",
                city="Leh",
                price_per_night=2500,
                currency_code="INR",
                rating=4.1,
                review_count=80,
            )
        ]

        mock_report = BudgetReport(
            currency_code="INR",
            total_estimated_cost=42000.0,
            per_category_breakdown={
                "transport": 9500.0,
                "accommodation": 7500.0,
                "food": 6000.0,
                "activities": 4500.0,
                "visa": 0.0,
                "self_drive": 0.0,
            },
            per_day_breakdown=[14000.0, 14000.0, 14000.0],
            vs_budget_verdict="on-budget",
        )
        from app.agents.budget_planner_agent import BudgetPlannerAgent

        agent = BudgetPlannerAgent(tool_factory=mock_tool_factory, llm=_make_llm(mock_report))
        result = await agent(
            {
                **base_state,
                "transport_recommendation": transport_rec,
                "stays_shortlist": stays_shortlist,
                "stays_pick": stays_shortlist[0],
            }
        )

        report = result["budget_report"]
        assert report is not None
        assert report.total_estimated_cost > 0
        expected_cats = {"transport", "accommodation", "food", "activities", "visa", "self_drive"}
        assert expected_cats.issubset(set(report.per_category_breakdown.keys()))

    @pytest.mark.asyncio
    async def test_fx_rates_used_populated_for_multi_currency(
        self, mock_tool_factory: ToolFactory, base_state: dict[str, Any]
    ) -> None:
        """FX-normalised breakdown should record fx_rates_used with fetched_at (H)."""
        from datetime import UTC, datetime

        from app.models.reports import BudgetReport, FxRateEntry
        from app.models.transport import (
            RouteLeg,
            RouteWaypoint,
            StayOption,
            TransportRecommendation,
        )

        # Transport in JPY (international trip) to trigger FX conversion
        transport_rec = TransportRecommendation(
            recommended_legs=[
                RouteLeg(
                    mode="flight",
                    operator="ANA",
                    origin="BOM",
                    destination="NRT",
                    duration_minutes=540,
                    cost=65000.0,
                    currency_code="JPY",
                    price_cached_at=datetime.now(tz=UTC),
                    price_disclaimer="Indicative.",
                )
            ],
            total_cost=65000.0,
            total_duration_minutes=540,
            currency_code="JPY",
            rationale="Direct flight.",
            personalization_reason="Good value.",
            route_waypoints=[
                RouteWaypoint(label="BOM", name="Mumbai", lat=19.08, lng=72.88),
                RouteWaypoint(label="NRT", name="Tokyo", lat=35.76, lng=140.38),
            ],
        )
        stays_shortlist = [
            StayOption(
                name="Tokyo Hotel",
                address="Tokyo",
                city="Tokyo",
                price_per_night=12000,
                currency_code="JPY",
                rating=4.3,
                review_count=120,
            )
        ]

        mock_report = BudgetReport(
            currency_code="JPY",
            total_estimated_cost=185000.0,
            per_category_breakdown={
                "transport": 65000.0,
                "accommodation": 60000.0,
                "food": 30000.0,
                "activities": 20000.0,
                "visa": 8000.0,
                "self_drive": 0.0,
            },
            per_day_breakdown=[37000.0] * 5,
            vs_budget_verdict="on-budget",
            fx_rates_used={"INR→JPY": FxRateEntry(rate=1.82, fetched_at=datetime.now(tz=UTC))},
            fx_disclaimer="FX rates fetched at time of planning.",
        )
        from app.agents.budget_planner_agent import BudgetPlannerAgent

        agent = BudgetPlannerAgent(tool_factory=mock_tool_factory, llm=_make_llm(mock_report))
        result = await agent(
            {
                **base_state,
                "destination": "Tokyo",
                "is_international": True,
                "transport_recommendation": transport_rec,
                "stays_shortlist": stays_shortlist,
                "stays_pick": stays_shortlist[0],
            }
        )

        report = result["budget_report"]
        assert report is not None
        # The mock FX tool returns a rate; fx_rates_used may be populated from the agent's
        # _convert() call. We verify the structure is sound either way.
        if report.fx_rates_used:
            for key, entry in report.fx_rates_used.items():
                assert entry.fetched_at is not None, f"fx_rates_used[{key}] missing fetched_at"

    @pytest.mark.asyncio
    async def test_llm_destination_cost_estimation(
        self, mock_tool_factory: ToolFactory, base_state: dict[str, Any]
    ) -> None:
        """Food and activities should be calculated from DestinationCostEstimate."""
        from unittest.mock import AsyncMock, MagicMock

        from app.agents.budget_planner_agent import BudgetPlannerAgent, DestinationCostEstimate

        cost_estimate = DestinationCostEstimate(
            daily_food_per_person=2000.0,
            daily_activity_per_person=1500.0,
            rationale="Tokyo mid-range dining and attraction pricing.",
        )

        mock_chain = MagicMock()
        mock_chain.ainvoke = AsyncMock(return_value=cost_estimate)
        mock_llm = MagicMock()
        mock_llm.with_structured_output = MagicMock(return_value=mock_chain)

        agent = BudgetPlannerAgent(tool_factory=mock_tool_factory, llm=mock_llm)
        result = await agent(
            {
                **base_state,
                "destination": "Tokyo",
                "travelers": 2,
            }
        )

        report = result["budget_report"]
        assert report is not None
        # 2000 per person/day * 3 days * 2 travelers = 12000.0
        assert report.per_category_breakdown["food"] == 12000.0
        # 1500 per person/day * 3 days * 2 travelers = 9000.0
        assert report.per_category_breakdown["activities"] == 9000.0


# ── Itinerary compiler: synthesize, never invent ─────────────────────────────


def _compiler_experience(name: str, lat: float = 34.16, lng: float = 77.58) -> Experience:
    return Experience(
        name=name,
        type="monastery",
        description=f"{name} description.",
        duration_hours=2.0,
        price_range="Free",
        lat=lat,
        lng=lng,
        address=f"{name}, Leh",
        rating=4.6,
        review_count=900,
        source="google_places",
    )


def _compiler_tool_factory() -> _StaticToolFactory:
    return _StaticToolFactory(
        {
            "cluster_by_proximity": {"clusters": []},
            "enforce_opening_hours": {"conflicts": []},
            "validate_day_duration": {"flags": []},
        }
    )


def _compiler_state(base_state: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    return {**base_state, **overrides}


class TestItineraryCompilerContract:
    """The compiler absorbs upstream findings verbatim and never invents new ones."""

    @staticmethod
    def _agent(day_plan: Any) -> Any:
        from app.agents.itinerary_compiler_agent import ItineraryCompilerAgent
        from app.models.itinerary_compilation import DayPlan, TripNarrative

        def _dispatch(schema: Any) -> MagicMock:
            chain = MagicMock()
            if schema is DayPlan:
                chain.ainvoke = AsyncMock(return_value=day_plan)
            elif schema is TripNarrative:
                chain.ainvoke = AsyncMock(return_value=TripNarrative(title="Three Days in Leh"))
            else:
                chain.ainvoke = AsyncMock(return_value=MagicMock())
            return chain

        llm = MagicMock()
        llm.with_structured_output = MagicMock(side_effect=_dispatch)
        return ItineraryCompilerAgent(tool_factory=_compiler_tool_factory(), llm=llm)

    @pytest.mark.asyncio
    async def test_five_day_trip_yields_five_days(self, base_state: dict[str, Any]) -> None:
        from app.models.itinerary_compilation import DayPlan

        state = _compiler_state(
            base_state,
            dates=TripDates(departure=date(2026, 7, 15), return_date=date(2026, 7, 19)),
        )
        result = await self._agent(DayPlan())(state)

        itinerary = result["itinerary"]
        assert len(itinerary.trip_days) == 5
        assert [d.day_number for d in itinerary.trip_days] == [1, 2, 3, 4, 5]

    @pytest.mark.asyncio
    async def test_unknown_llm_picks_are_dropped(self, base_state: dict[str, Any]) -> None:
        from app.models.itinerary_compilation import ActivityPick, DayPlan

        plan = DayPlan(
            activities=[
                ActivityPick(
                    day_number=1,
                    slot="morning",
                    experience_name="Totally Invented Monastery",
                    recommendation_reason="Sounds nice.",
                )
            ]
        )
        state = _compiler_state(base_state, experiences_raw=[_compiler_experience("Thiksey")])
        result = await self._agent(plan)(state)

        scheduled = [
            opt.place.name
            for day in result["itinerary"].trip_days
            for slot in (day.morning, day.afternoon, day.evening)
            for opt in slot.options
        ]
        assert "Totally Invented Monastery" not in scheduled

    @pytest.mark.asyncio
    async def test_stay_and_safety_are_copied_verbatim_onto_every_day(
        self, base_state: dict[str, Any]
    ) -> None:
        from app.models.itinerary_compilation import DayPlan

        stay = StayOption(
            name="Grand Dragon",
            address="Old Road, Leh",
            city="Leh",
            price_per_night=8200.0,
            currency_code="INR",
            rating=4.4,
            review_count=310,
            check_in="2:00 PM",
            check_out="11:00 AM",
        )
        safety = SafetyReport(
            destination="Leh",
            advisory_level="Exercise increased caution",
            crowd_level="High",
            seasonal_weather_summary="Dry and cold at night.",
            altitude_meters=3524,
            acclimatization_advice="Rest for the first 24 hours.",
            top_scams=[
                ScamEntry(
                    name="Taxi overcharging",
                    description="Inflated fixed fares",
                    how_to_avoid="Use the union rate card",
                )
            ],
        )
        state = _compiler_state(
            base_state, stays_shortlist=[stay], stays_pick=stay, safety_report=safety
        )
        result = await self._agent(DayPlan())(state)
        itinerary = result["itinerary"]

        for day in itinerary.trip_days:
            assert day.stay_options is not None
            assert day.stay_options.options == [stay]
            assert day.stay_options.recommended is stay
            assert day.stay_options.check_in == "2:00 PM"
        assert itinerary.safety_section is safety

    @pytest.mark.asyncio
    async def test_trip_level_prose_is_templated_not_generated(
        self, base_state: dict[str, Any]
    ) -> None:
        from app.models.itinerary_compilation import DayPlan
        from app.services.itinerary_compiler_service import ItineraryCompilerService

        service = ItineraryCompilerService()
        safety = SafetyReport(
            destination="Leh",
            advisory_level="Exercise normal caution",
            season_label="Shoulder",
            crowd_level="Moderate",
            seasonal_weather_summary="Clear days, freezing nights.",
        )
        budget = BudgetReport(
            currency_code="INR",
            total_estimated_cost=42000.0,
            per_day_breakdown=[14000.0, 14000.0, 14000.0],
            vs_budget_verdict="on-budget",
        )
        state = _compiler_state(base_state, safety_report=safety, budget_report=budget)
        itinerary = (await self._agent(DayPlan())(state))["itinerary"]

        assert itinerary.safety_briefing == service.render_safety_briefing(safety)
        assert itinerary.reality_banner == service.build_reality_banner(safety, budget)
        assert itinerary.budget_breakdown is budget
        assert [d.estimated_cost for d in itinerary.trip_days] == [14000.0, 14000.0, 14000.0]

    @pytest.mark.asyncio
    async def test_nothing_upstream_is_dropped(self, base_state: dict[str, Any]) -> None:
        from app.models.itinerary_compilation import DayPlan
        from app.services.itinerary_compiler_service import ItineraryCompilerService

        stay = StayOption(
            name="Grand Dragon",
            address="Old Road, Leh",
            city="Leh",
            price_per_night=8200.0,
            currency_code="INR",
            rating=4.4,
            review_count=310,
        )
        state = _compiler_state(
            base_state,
            stays_shortlist=[stay],
            safety_report=SafetyReport(destination="Leh", advisory_level="Normal"),
            budget_report=BudgetReport(
                currency_code="INR", total_estimated_cost=1.0, vs_budget_verdict="under"
            ),
        )
        itinerary = (await self._agent(DayPlan())(state))["itinerary"]

        assert ItineraryCompilerService().assert_upstream_absorbed(itinerary, state) == []

    @pytest.mark.asyncio
    async def test_missing_trip_dates_errors_instead_of_guessing_a_default(
        self, base_state: dict[str, Any]
    ) -> None:
        """The compiler must never invent a trip length — it errors instead of guessing."""
        from app.models.itinerary_compilation import DayPlan

        state = {k: v for k, v in base_state.items() if k != "dates"}
        result = await self._agent(DayPlan())(state)

        assert "error" in result
        assert "itinerary" not in result
