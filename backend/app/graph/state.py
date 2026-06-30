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
from typing import Annotated, Any

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from app.models.clarification import ClarificationPrompt
from app.models.itinerary import Experience, Itinerary
from app.models.reports import (
    AgentTokenUsage,
    BudgetReport,
    DestinationContextReport,
    ReviewSummary,
    ScamSafetyReport,
    SelfDriveReport,
    VisaReport,
)
from app.models.transport import StayOption, TransportRecommendation
from app.models.user_profile import BudgetPreference, TripDates, UserProfile


class TripState(dict):  # type: ignore[type-arg]
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
    budget: BudgetPreference
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
    destination_context_report: DestinationContextReport | None
    scam_safety_report: ScamSafetyReport | None
    visa_report: VisaReport | None

    # ── Layer 2: Supply Search ─────────────────────────────────────────────
    transport_hubs: list[str]  # from hub-ID step in TransportSearchAgent
    transport_legs_raw: dict[str, list[Any]]  # keyed by "KOL→DEL"
    stays_raw: list[StayOption]
    experiences_raw: list[Experience]

    # ── Layer 3: Analysis ──────────────────────────────────────────────────
    transport_recommendation: TransportRecommendation | None
    transport_alternatives: list[TransportRecommendation]  # top-2 budget-filtered alternatives
    stays_shortlist: list[StayOption]  # 3–5 ranked options with personalization_reason
    stays_pick: StayOption | None  # first item in shortlist (recommended default)
    stays_rationale: str
    self_drive_report: SelfDriveReport | None

    # ── Layer 4: Enrichment ────────────────────────────────────────────────
    reviews_summary: Annotated[dict[str, ReviewSummary], operator.or_]
    food_recommendations: Annotated[dict[str, list[Any]], operator.or_]
    budget_report: BudgetReport | None

    # ── Output ─────────────────────────────────────────────────────────────
    itinerary: Itinerary | None
    token_usage: Annotated[dict[str, AgentTokenUsage], operator.or_]
    messages: Annotated[list[BaseMessage], add_messages]
    error: str | None


def initial_state(
    query: str,
    session_id: str,
) -> dict[str, Any]:
    """Return a minimal initial state dict ready for graph invocation."""
    return {
        "query": query,
        "session_id": session_id,
        "source": "",
        "destination": "",
        "dates": None,
        "budget": BudgetPreference(),
        "travelers": 1,
        "user_profile": None,
        "is_international": False,
        "self_drive_intent": False,
        # Clarification gate
        "needs_clarification": False,
        "clarification_prompts": [],
        "parse_confidence": {},
        "clarification_round": 0,
        # Layer 1
        "destination_context_report": None,
        "scam_safety_report": None,
        "visa_report": None,
        # Layer 2
        "transport_hubs": [],
        "transport_legs_raw": {},
        "stays_raw": [],
        "experiences_raw": [],
        # Layer 3
        "transport_recommendation": None,
        "transport_alternatives": [],
        "stays_shortlist": [],
        "stays_pick": None,
        "stays_rationale": "",
        "self_drive_report": None,
        # Layer 4
        "reviews_summary": {},
        "food_recommendations": {},
        "budget_report": None,
        # Output
        "itinerary": None,
        "token_usage": {},
        "messages": [],
        "error": None,
    }
