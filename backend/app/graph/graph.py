"""LangGraph StateGraph — 14 agent nodes with clarification gate.

Routing after OrchestratorAgent:
  • ``needs_clarification == True``  → ``clarification`` node → END
  • ``needs_clarification == False`` → ``ready_to_plan`` pass-through node
                                       → fan-out to all Layer 1 + Layer 2 nodes

The ``ready_to_plan`` node exists purely as a fan-out source so that we can
use ``conditional_edges`` from ``orchestrator`` (which only supports a single
return value per call) while still enabling parallel execution for all
Layer 1 + 2 agents.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.budget_planner_agent import BudgetPlannerAgent
from app.agents.destination_context_agent import DestinationContextAgent
from app.agents.food_discovery_agent import FoodDiscoveryAgent
from app.agents.itinerary_compiler_agent import ItineraryCompilerAgent
from app.agents.local_experiences_agent import LocalExperiencesAgent
from app.agents.orchestrator import OrchestratorAgent
from app.agents.reviews_agent import ReviewsAgent
from app.agents.scam_safety_agent import ScamSafetyAgent
from app.agents.self_drive_search_agent import SelfDriveSearchAgent
from app.agents.stay_analyst_agent import StayAnalystAgent
from app.agents.stay_search_agent import StaySearchAgent
from app.agents.transport_optimizer_agent import TransportOptimizerAgent
from app.agents.transport_search_agent import TransportSearchAgent
from app.agents.visa_agent import VisaAgent
from app.graph.state import TripState, initial_state
from app.tools.factory import ToolFactory

# ── Clarification pass-through node ──────────────────────────────────────────

async def _clarification_node(state: dict[str, Any]) -> dict[str, Any]:
    """Terminal node reached when the query is ambiguous.

    Emits no changes — the graph simply halts here and the SSE router
    emits a ``needs_clarification`` event to the client.
    """
    return {}  # state already has needs_clarification=True + prompts


async def _ready_to_plan_node(state: dict[str, Any]) -> dict[str, Any]:
    """Pass-through node used as a fan-out source for Layer 1+2 parallelism."""
    return {}


def _route_after_orchestrator(state: dict[str, Any]) -> str:
    if state.get("needs_clarification"):
        return "clarification"
    return "ready_to_plan"


# ── Graph builder ─────────────────────────────────────────────────────────────

def build_graph(tool_factory: ToolFactory | None = None, llm: object | None = None) -> Any:
    """Construct and compile the full planning graph.

    Args:
        tool_factory: Injected factory (mock or real).
        llm: Optional shared LLM instance injected into all agents.
             Primarily used in tests to avoid real API calls.
    """
    factory = tool_factory or ToolFactory()

    orchestrator = OrchestratorAgent(llm=llm)
    dest_context = DestinationContextAgent(tool_factory=factory, llm=llm)
    scam_safety = ScamSafetyAgent(tool_factory=factory, llm=llm)
    visa = VisaAgent(tool_factory=factory, llm=llm)
    transport_search = TransportSearchAgent(tool_factory=factory, llm=llm)
    stay_search = StaySearchAgent(tool_factory=factory)
    local_experiences = LocalExperiencesAgent(tool_factory=factory)
    transport_optimizer = TransportOptimizerAgent(tool_factory=factory, llm=llm)
    stay_analyst = StayAnalystAgent(llm=llm)
    self_drive_search = SelfDriveSearchAgent(tool_factory=factory, llm=llm)
    reviews = ReviewsAgent(tool_factory=factory, llm=llm)
    food_discovery = FoodDiscoveryAgent(tool_factory=factory)
    budget_planner = BudgetPlannerAgent(tool_factory=factory, llm=llm)
    itinerary_compiler = ItineraryCompilerAgent(tool_factory=factory, llm=llm)

    graph = StateGraph(TripState)

    # Control nodes
    graph.add_node("orchestrator", orchestrator)
    graph.add_node("clarification", _clarification_node)
    graph.add_node("ready_to_plan", _ready_to_plan_node)

    # Layer 1
    graph.add_node("destination_context", dest_context)
    graph.add_node("scam_safety", scam_safety)
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

    # Layer 5
    graph.add_node("itinerary_compiler", itinerary_compiler)

    # ── Edges ──────────────────────────────────────────────────────────────
    graph.add_edge(START, "orchestrator")

    # Conditional: clarification gate
    graph.add_conditional_edges(
        "orchestrator",
        _route_after_orchestrator,
        {"clarification": "clarification", "ready_to_plan": "ready_to_plan"},
    )
    graph.add_edge("clarification", END)

    # Fan-out from ready_to_plan → all Layer 1+2 nodes in parallel
    for node in [
        "destination_context", "scam_safety", "visa",
        "transport_search", "stay_search", "local_experiences",
    ]:
        graph.add_edge("ready_to_plan", node)

    # Layer 2 → Layer 3
    graph.add_edge("transport_search", "transport_optimizer")
    graph.add_edge("transport_search", "self_drive_search")
    graph.add_edge("stay_search", "stay_analyst")

    # Layer 1+3 → budget_planner (barrier: waits for all 6)
    for node in [
        "destination_context", "scam_safety", "visa",
        "transport_optimizer", "stay_analyst", "self_drive_search",
    ]:
        graph.add_edge(node, "budget_planner")

    # Layer 3+2 → reviews
    graph.add_edge("stay_analyst", "reviews")
    graph.add_edge("local_experiences", "reviews")

    # Layer 2 → food_discovery
    graph.add_edge("local_experiences", "food_discovery")

    # Layer 4 → itinerary_compiler
    graph.add_edge("budget_planner", "itinerary_compiler")
    graph.add_edge("reviews", "itinerary_compiler")
    graph.add_edge("food_discovery", "itinerary_compiler")

    graph.add_edge("itinerary_compiler", END)

    return graph.compile()


_compiled_graph: Any | None = None


def get_graph() -> Any:
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph


async def run_graph(query: str, session_id: str, **overrides: Any) -> dict[str, Any]:
    """Run the full planning graph for a query.  Returns the final TripState dict."""
    state = initial_state(query=query, session_id=session_id)
    state.update(overrides)
    compiled = get_graph()
    result: dict[str, Any] = await compiled.ainvoke(state)
    return result


