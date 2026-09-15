"""TripState — shared state for the LangGraph multi-agent graph.

All agents read from and write to this single TypedDict.  LangGraph merges
partial updates returned by each node; agents MUST only return the keys they
changed rather than the full state.

Annotated reducers are used for fields that multiple agents write to
(messages, token_usage, reviews_summary, food_recommendations) so that
LangGraph merges rather than overwrites them.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, ConfigDict, Field

from app.models.clarification import ClarificationPrompt
from app.models.itinerary import Experience, Itinerary
from app.models.reports import (
    AgentTokenUsage,
    BudgetReport,
    ReviewSummary,
    SafetyReport,
    SelfDriveReport,
    VisaReport,
)
from app.models.stops import DayAllocation, GatewayOption, RouteLegPlan, TripStop
from app.models.transport import StayOption, TransportRecommendation
from app.models.user_profile import BudgetPreference, TripDates, UserProfile


class TripState(TypedDict, total=False):
    """Full planning state shared across all agent nodes.

    Subclasses dict for LangGraph compatibility while keeping type hints.
    Fields with Annotated reducers are merged; all others use last-write-wins.
    """

    # ── Input ──────────────────────────────────────────────────────────────
    query: str
    session_id: str
    source: str
    destination: str
    dates: TripDates | None
    budget: dict[str, str | float | None] | BudgetPreference
    travelers: int
    user_profile: UserProfile | None
    is_international: bool  # set by OrchestratorAgent
    self_drive_intent: bool  # set by OrchestratorAgent

    # ── Clarification gate (F) ─────────────────────────────────────────────
    needs_clarification: bool  # kept for backward-compat; no longer written by orchestrator
    clarification_prompts: list[ClarificationPrompt]  # kept for backward-compat
    parse_confidence: dict[str, float]  # field → confidence score 0–1
    clarification_round: int  # number of completed clarification rounds

    # ── Layer 1: Destination Intelligence ─────────────────────────────────
    safety_report: SafetyReport | None
    visa_report: VisaReport | None

    # ── Layer 1: Route discovery (StopsDiscoveryAgent) ─────────────────────
    # See specs/stops-discovery-agent-spec.md. All route output is
    # provisional (route_verification_status) until Phase 6 verification.
    route_discovery_status: (
        str  # "single_destination" | "multi_stop_provisional" | "discovery_failed"
    )
    route_verification_status: str  # "provisional" | "verified"
    route_version: int
    stops: dict[str, TripStop]  # keyed by stop_id; unset/empty for single_destination
    route_legs: dict[str, RouteLegPlan]  # keyed by leg_id
    stops_by_day: dict[int, DayAllocation]  # day_index -> allocation record
    gateway_options: list[GatewayOption]
    selected_gateway_option_id: str | None

    # ── Layer 2: Supply Search ─────────────────────────────────────────────
    transport_hubs: list[str]  # from hub-ID step in TransportSearchAgent
    transport_legs_raw: dict[str, list[Any]]  # keyed by "KOL→DEL" (single_destination)
    transport_legs_raw_by_leg: dict[str, list[Any]]  # keyed by leg_id (multi-stop)
    stays_raw: list[StayOption]  # single_destination fallback
    stays_raw_by_stop: dict[str, list[StayOption]]  # keyed by stop_id (multi-stop)
    experiences_raw: list[Experience]  # single_destination fallback
    experiences_raw_by_stop: dict[str, list[Experience]]  # keyed by stop_id (multi-stop)

    # ── Layer 3: Analysis ──────────────────────────────────────────────────
    transport_recommendation: TransportRecommendation | None
    transport_alternatives: list[TransportRecommendation]  # top-2 budget-filtered alternatives
    transport_recommendation_by_leg: dict[str, TransportRecommendation]  # keyed by leg_id
    stays_shortlist: list[StayOption]  # 3–5 ranked options with personalization_reason
    stays_pick: StayOption | None  # first item in shortlist (recommended default)
    stays_rationale: str
    stays_shortlist_by_stop: dict[str, list[StayOption]]  # keyed by stop_id (multi-stop)
    stays_pick_by_stop: dict[str, StayOption]  # keyed by stop_id (multi-stop)
    self_drive_report: SelfDriveReport | None

    # ── Layer 4: Enrichment ────────────────────────────────────────────────
    reviews_summary: Annotated[dict[str, ReviewSummary], operator.or_]
    food_recommendations: Annotated[
        dict[str, list[Any]], operator.or_
    ]  # single_destination fallback
    food_recommendations_by_stop: Annotated[dict[str, dict[str, list[Any]]], operator.or_]
    budget_report: BudgetReport | None

    # ── Output ─────────────────────────────────────────────────────────────
    itinerary: Itinerary | None
    token_usage: Annotated[dict[str, AgentTokenUsage], operator.or_]
    messages: Annotated[list[BaseMessage], add_messages]
    error: str | None


class TripStateModel(BaseModel):
    """Typed, validated read view over a ``TripState`` dict.

    Mirrors ``initial_state()``'s defaults so agents get one call
    (``TripStateModel.from_state(state)``) instead of repeating
    ``state.get("field", default)`` throughout their body. Agents should
    still return plain dicts (partial updates) to LangGraph as before —
    this model is for *reading* state, not writing it.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    query: str = ""
    session_id: str = ""
    source: str = ""
    destination: str = ""
    dates: TripDates | None = None
    budget: dict[str, str | float | None] | BudgetPreference = Field(
        default_factory=BudgetPreference
    )
    travelers: int = 1
    user_profile: UserProfile | None = None
    is_international: bool = False
    self_drive_intent: bool = False

    needs_clarification: bool = False
    clarification_prompts: list[ClarificationPrompt] = Field(default_factory=list)
    parse_confidence: dict[str, float] = Field(default_factory=dict)
    clarification_round: int = 0

    safety_report: SafetyReport | None = None
    visa_report: VisaReport | None = None

    route_discovery_status: str = "single_destination"
    route_verification_status: str = "provisional"
    route_version: int = 0
    stops: dict[str, TripStop] = Field(default_factory=dict)
    route_legs: dict[str, RouteLegPlan] = Field(default_factory=dict)
    stops_by_day: dict[int, DayAllocation] = Field(default_factory=dict)
    gateway_options: list[GatewayOption] = Field(default_factory=list)
    selected_gateway_option_id: str | None = None

    transport_hubs: list[str] = Field(default_factory=list)
    transport_legs_raw: dict[str, list[Any]] = Field(default_factory=dict)
    transport_legs_raw_by_leg: dict[str, list[Any]] = Field(default_factory=dict)
    stays_raw: list[StayOption] = Field(default_factory=list)
    stays_raw_by_stop: dict[str, list[StayOption]] = Field(default_factory=dict)
    experiences_raw: list[Experience] = Field(default_factory=list)
    experiences_raw_by_stop: dict[str, list[Experience]] = Field(default_factory=dict)

    transport_recommendation: TransportRecommendation | None = None
    transport_alternatives: list[TransportRecommendation] = Field(default_factory=list)
    transport_recommendation_by_leg: dict[str, TransportRecommendation] = Field(
        default_factory=dict
    )
    stays_shortlist: list[StayOption] = Field(default_factory=list)
    stays_pick: StayOption | None = None
    stays_rationale: str = ""
    stays_shortlist_by_stop: dict[str, list[StayOption]] = Field(default_factory=dict)
    stays_pick_by_stop: dict[str, StayOption] = Field(default_factory=dict)
    self_drive_report: SelfDriveReport | None = None

    reviews_summary: dict[str, ReviewSummary] = Field(default_factory=dict)
    food_recommendations: dict[str, list[Any]] = Field(default_factory=dict)
    food_recommendations_by_stop: dict[str, dict[str, list[Any]]] = Field(default_factory=dict)
    budget_report: BudgetReport | None = None

    itinerary: Itinerary | None = None
    token_usage: dict[str, AgentTokenUsage] = Field(default_factory=dict)
    messages: list[BaseMessage] = Field(default_factory=list)
    error: str | None = None

    @classmethod
    def from_state(cls, state: dict[str, Any]) -> TripStateModel:
        return cls.model_validate(state)


def initial_state(
    query: str,
    session_id: str,
) -> dict[str, Any]:
    """Return a minimal initial state dict ready for graph invocation.

    Defaults come from ``TripStateModel`` so they're declared in one place.
    """
    return TripStateModel(query=query, session_id=session_id).model_dump()
