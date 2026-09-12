"""LangGraph StateGraph — 14 agent nodes with interrupt-based clarification.

The OrchestratorAgent uses LangGraph ``interrupt()`` to pause the graph when
the user query is ambiguous.  The client resumes via
``POST /api/trip/{session_id}/clarify`` — no full re-POST is needed.

After the orchestrator finishes (with or without clarification rounds), route
discovery fans out directly to the Layer 1 and Layer 2 entry nodes in parallel.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.agents.budget_planner_agent import BudgetPlannerAgent
from app.agents.food_discovery_agent import FoodDiscoveryAgent
from app.agents.itinerary_compiler_agent import ItineraryCompilerAgent
from app.agents.local_experiences_agent import LocalExperiencesAgent
from app.agents.orchestrator import OrchestratorAgent
from app.agents.reviews_agent import ReviewsAgent
from app.agents.safety_agent import SafetyAgent
from app.agents.self_drive_search_agent import SelfDriveSearchAgent
from app.agents.stay_analyst_agent import StayAnalystAgent
from app.agents.stay_search_agent import StaySearchAgent
from app.agents.stops_discovery_agent import StopsDiscoveryAgent
from app.agents.transport_optimizer_agent import TransportOptimizerAgent
from app.agents.transport_search_agent import TransportSearchAgent
from app.agents.visa_agent import VisaAgent
from app.config import settings
from app.graph.state import TripState, initial_state
from app.logging import get_agent_logger
from app.models.clarification import ClarificationPrompt
from app.models.user_profile import UserProfile
from app.services.user_profile_service import upsert_user_profile
from app.tools.factory import ToolFactory


async def _route_clarification_node(state: dict[str, Any]) -> dict[str, Any]:
    """Pause the graph when StopsDiscoveryAgent could not shape a usable route.

    Reuses the existing ``interrupt()``/resume mechanism (see OrchestratorAgent)
    instead of silently falling back to a single-destination itinerary — a
    ``discovery_failed`` route must never reach Layer 2 supply search.
    """
    session_id = state.get("session_id", "")
    round_ = state.get("clarification_round", 0)
    log = get_agent_logger("stops_discovery", session_id)
    log.info("route_clarification_requested", round=round_)

    prompt = ClarificationPrompt(
        field="destination",
        question=(
            "I couldn't work out a clear route for this trip — could you name the"
            " specific places or region you'd like to visit?"
        ),
        reason="Route discovery failed",
        input_type="text",
    )
    answers: dict[str, str] = interrupt({"prompts": [prompt.model_dump()], "round": round_})
    updates: dict[str, Any] = {"clarification_round": round_ + 1}
    new_destination = answers.get("destination", "").strip()
    if new_destination:
        updates["destination"] = new_destination
    return updates


def _split_food_preference(value: str) -> list[str]:
    """Convert a comma-separated clarification answer to normalized values."""
    return [item.strip() for item in value.split(",") if item.strip()]


async def _food_clarification_node(state: dict[str, Any]) -> dict[str, Any]:
    """Collect durable cuisine and dietary preferences before food discovery."""
    session_id = state.get("session_id", "")
    profile: UserProfile | None = state.get("user_profile")
    if profile and profile.food_preferences_configured:
        return {}

    log = get_agent_logger("food_clarification", session_id)
    prompts = [
        ClarificationPrompt(
            field="preferred_cuisines",
            question="Which cuisines would you most like to eat on this trip?",
            reason="Personalize restaurant discovery",
            input_type="text",
        ),
        ClarificationPrompt(
            field="dietary_restrictions",
            question="Do you have dietary restrictions or requirements?",
            reason="Avoid unsuitable restaurant recommendations",
            input_type="text",
            options=["No dietary restrictions"],
        ),
    ]
    log.info("clarification_required", fields=[prompt.field for prompt in prompts])
    answers: dict[str, str] = interrupt(
        {
            "prompts": [prompt.model_dump() for prompt in prompts],
            "round": state.get("clarification_round", 0),
        }
    )

    dietary_answer = answers.get("dietary_restrictions", "").strip()
    dietary = (
        []
        if dietary_answer.lower() == "no dietary restrictions"
        else _split_food_preference(dietary_answer)
    )
    updated_profile = (profile or UserProfile(user_id=session_id or "anon")).model_copy(
        update={
            "preferred_cuisines": _split_food_preference(answers.get("preferred_cuisines", "")),
            "dietary_restrictions": dietary,
            "food_preferences_configured": True,
        }
    )
    if session_id:
        try:
            await upsert_user_profile(session_id, updated_profile)
        except Exception as exc:
            log.warning("profile_persist_failed", error=str(exc))

    return {
        "user_profile": updated_profile,
        "clarification_round": state.get("clarification_round", 0) + 1,
    }


async def _discovery_failed_end_node(state: dict[str, Any]) -> dict[str, Any]:
    """Hard-stop after clarification rounds are exhausted and no route was shaped.

    A ``discovery_failed`` route must never silently degrade into a plausible-
    looking but wrong single-destination itinerary (see spec's non-negotiable
    acceptance gates).
    """
    log = get_agent_logger("stops_discovery", state.get("session_id", ""))
    log.error("route_discovery_failed_hard_stop")
    return {"error": "Could not determine a usable trip route from the query provided."}


def _route_after_discovery(state: dict[str, Any]) -> str | list[str]:
    if state.get("route_discovery_status") != "discovery_failed":
        return [
            "visa",
            "transport_search",
            "stay_search",
            "local_experiences",
        ]
    if state.get("clarification_round", 0) >= settings.max_clarification_rounds:
        return "discovery_failed_end"
    return "route_clarification"


# ── Graph builder ──────────────────────────────────────────────────────────────


def build_graph(
    tool_factory: ToolFactory | None = None,
    llm: Any | None = None,
    checkpointer: Any | None = None,
) -> Any:
    """Construct and compile the full planning graph.

    Args:
        tool_factory: Injected factory (mock or real).
        llm: Optional shared LLM instance injected into all agents.
             Primarily used in tests to avoid real API calls.
        checkpointer: LangGraph checkpointer for interrupt/resume support.
                      Pass ``None`` in tests; use ``AsyncPostgresSaver`` in production.
    """
    factory = tool_factory or ToolFactory()

    orchestrator = OrchestratorAgent(llm=llm)
    stops_discovery = StopsDiscoveryAgent(llm=llm)
    safety = SafetyAgent(tool_factory=factory, llm=llm)
    visa = VisaAgent(tool_factory=factory, llm=llm)
    transport_search = TransportSearchAgent(tool_factory=factory, llm=llm)
    stay_search = StaySearchAgent(tool_factory=factory)
    local_experiences = LocalExperiencesAgent(tool_factory=factory, llm=llm)
    transport_optimizer = TransportOptimizerAgent(tool_factory=factory, llm=llm)
    stay_analyst = StayAnalystAgent(llm=llm)
    self_drive_search = SelfDriveSearchAgent(tool_factory=factory, llm=llm)
    reviews = ReviewsAgent(tool_factory=factory, llm=llm)
    food_discovery = FoodDiscoveryAgent(tool_factory=factory)
    budget_planner = BudgetPlannerAgent(tool_factory=factory, llm=llm)
    itinerary_compiler = ItineraryCompilerAgent(tool_factory=factory, llm=llm)

    graph: Any = StateGraph(TripState)

    # Control nodes (orchestration + interrupt-based gates, not a numbered layer)
    graph.add_node("orchestrator", orchestrator)
    graph.add_node("route_clarification", _route_clarification_node)
    graph.add_node("food_clarification", _food_clarification_node)
    graph.add_node("discovery_failed_end", _discovery_failed_end_node)

    # Layer 1 — Route Discovery + Destination Intelligence
    # (stops_discovery gates every Layer 2 supply-search node; visa runs in
    # parallel with Layer 2 but never blocks it — see plan.md Layer 1 section)
    graph.add_node("stops_discovery", stops_discovery)
    graph.add_node("visa", visa)

    # Layer 2
    graph.add_node("transport_search", transport_search)
    graph.add_node("stay_search", stay_search)
    graph.add_node("local_experiences", local_experiences)

    # Layer 3
    graph.add_node("transport_optimizer", transport_optimizer)
    graph.add_node("stay_analyst", stay_analyst)
    graph.add_node("self_drive_search", self_drive_search)

    # Layer 4
    graph.add_node("reviews", reviews)
    graph.add_node("food_discovery", food_discovery)
    graph.add_node("budget_planner", budget_planner)
    graph.add_node("safety", safety)

    # Layer 5
    graph.add_node("itinerary_compiler", itinerary_compiler)

    # ── Edges ──────────────────────────────────────────────────────────────
    graph.add_edge(START, "orchestrator")

    # Orchestrator → stops_discovery (interrupt() inside the orchestrator handles
    # its own clarification; the graph pauses mid-node and resumes transparently)
    graph.add_edge("orchestrator", "stops_discovery")

    # Successful route discovery fans out directly to the Layer 1/2 entry nodes;
    # a discovery_failed route never reaches supply search with a fabricated
    # single-destination fallback (see the route spec's acceptance gates).
    graph.add_conditional_edges(
        "stops_discovery",
        _route_after_discovery,
        {
            "visa": "visa",
            "transport_search": "transport_search",
            "stay_search": "stay_search",
            "local_experiences": "local_experiences",
            "route_clarification": "route_clarification",
            "discovery_failed_end": "discovery_failed_end",
        },
    )
    graph.add_edge("route_clarification", "stops_discovery")
    graph.add_edge("discovery_failed_end", END)

    # Layer 2 → Layer 3
    graph.add_edge("transport_search", "transport_optimizer")
    graph.add_edge("transport_search", "self_drive_search")
    graph.add_edge("stay_search", "stay_analyst")

    # Layer 3 → budget_planner.
    # safety_report and visa_report are already in state by the time
    # the layer-3 agents finish — no direct edge needed from layer-1 nodes.
    # Removing those edges keeps all budget_planner predecessors at the same
    # graph depth so LangGraph fires it exactly once.
    for node in [
        "transport_optimizer",
        "stay_analyst",
        "self_drive_search",
    ]:
        graph.add_edge(node, "budget_planner")

    # Layer 3+2 → reviews
    graph.add_edge("stay_analyst", "reviews")
    graph.add_edge("local_experiences", "reviews")

    # Food preference answers are collected only after activity locations are known.
    graph.add_edge("local_experiences", "food_clarification")
    graph.add_edge("food_clarification", "food_discovery")

    # food_discovery → safety: agent runs after food outlets + experiences are in state
    graph.add_edge("food_discovery", "safety")

    # Layer 4 + safety → itinerary_compiler (barrier: 3 inputs)
    graph.add_edge("budget_planner", "itinerary_compiler")
    graph.add_edge("reviews", "itinerary_compiler")
    graph.add_edge("safety", "itinerary_compiler")

    graph.add_edge("itinerary_compiler", END)

    return graph.compile(checkpointer=checkpointer)


_compiled_graph: Any | None = None
_graph_init_lock: Any | None = None


def get_graph() -> Any:
    """Return the compiled graph without a checkpointer.

    Used in tests and scripts where no persistent checkpoint is needed.
    For production use ``get_compiled_graph()`` instead.
    """
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph


async def get_compiled_graph() -> Any:
    """Return the production compiled graph (with checkpointer), initialising lazily.

    Async-safe singleton using a lock — safe to call from multiple concurrent
    request handlers.
    """
    import asyncio

    global _compiled_graph, _graph_init_lock

    if _compiled_graph is not None:
        return _compiled_graph

    if _graph_init_lock is None:
        _graph_init_lock = asyncio.Lock()

    async with _graph_init_lock:
        if _compiled_graph is None:
            from app.checkpointer import get_checkpointer

            checkpointer = await get_checkpointer()
            _compiled_graph = build_graph(checkpointer=checkpointer)

    return _compiled_graph


async def run_graph(query: str, session_id: str, **overrides: Any) -> dict[str, Any]:
    """Run the full planning graph for a query.  Returns the final TripState dict."""
    state = initial_state(query=query, session_id=session_id)
    state.update(overrides)
    compiled = await get_compiled_graph()
    config = {"configurable": {"thread_id": session_id}}
    result: dict[str, Any] = await compiled.ainvoke(state, config=config)
    return result
