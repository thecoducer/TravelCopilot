"""Cross-cutting domain enums.

Single source of truth for category/type vocabularies that were previously
scattered as bare string literals across agents, services and prompts.

All members are ``StrEnum`` so existing ``value == "literal"`` comparisons and
JSON serialisation keep working unchanged.
"""

from __future__ import annotations

from enum import StrEnum


class AgentName(StrEnum):
    """Canonical agent identifiers used for logging, metrics and per-agent config."""

    ORCHESTRATOR = "orchestrator"
    STOPS_DISCOVERY = "stops_discovery"
    VISA = "visa"
    TRANSPORT_SEARCH = "transport_search"
    TRANSPORT_OPTIMIZER = "transport_optimizer"
    STAY_SEARCH = "stay_search"
    STAY_ANALYST = "stay_analyst"
    SELF_DRIVE_SEARCH = "self_drive_search"
    LOCAL_EXPERIENCES = "local_experiences"
    FOOD_DISCOVERY = "food_discovery"
    REVIEWS = "reviews"
    SAFETY = "safety"
    BUDGET_PLANNER = "budget_planner"
    ITINERARY_COMPILER = "itinerary_compiler"


class LogEvent(StrEnum):
    """Structured log event names — the ``event`` key of every structlog call."""

    AGENT_START = "agent_start"
    AGENT_DONE = "agent_done"
    AGENT_DEGRADED = "agent_degraded"
    AGENT_FAILED = "agent_failed"

    LLM_STRUCTURED_START = "llm_structured_start"
    LLM_STRUCTURED_DONE = "llm_structured_done"
    LLM_STRUCTURED_RETRY = "llm_structured_retry"
    LLM_STRUCTURED_FAILED = "llm_structured_failed"
    LLM_OUTPUT_TRUNCATED = "llm_output_truncated"
    LLM_USAGE_RECORDED = "llm_usage_recorded"
    LLM_USAGE_TRACKING_FAILED = "llm_usage_tracking_failed"

    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_DONE = "tool_call_done"
    TOOL_CALL_FAILED = "tool_call_failed"

    CLARIFICATION_REQUESTED = "clarification_requested"
    CLARIFICATION_RESOLVED = "clarification_resolved"

    CURRENCY_RESOLVED = "currency_resolved"
    CURRENCY_CONVERSION_FAILED = "currency_conversion_failed"

    ROUTE_CALENDAR_ADJUSTED = "route_calendar_adjusted"
    SECTION_UNAVAILABLE = "section_unavailable"


class SectionStatus(StrEnum):
    """Why an optional itinerary section is empty — never ship a bare ``null``."""

    POPULATED = "populated"
    NOT_APPLICABLE = "not_applicable"
    UNAVAILABLE = "unavailable"


class DataSource(StrEnum):
    """Provenance of a record, so unverified model output is never shown as fact."""

    PROVIDER = "provider"
    LLM = "llm"
    FALLBACK = "fallback"
    USER = "user"


class Sentiment(StrEnum):
    """Review sentiment — ``UNKNOWN`` is the only valid value without evidence."""

    POSITIVE = "positive"
    MIXED = "mixed"
    NEGATIVE = "negative"
    UNKNOWN = "unknown"


class MealType(StrEnum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    SNACK = "snack"


class DaySlot(StrEnum):
    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"


class StopKind(StrEnum):
    """Whether a routed stop is slept at or only passed through."""

    OVERNIGHT = "overnight"
    GATEWAY_TRANSIT = "gateway_transit"


class ConnectivityLevel(StrEnum):
    """Mobile/data coverage expectation at a stop."""

    RELIABLE = "reliable"
    PATCHY = "patchy"
    LIMITED = "limited"
    NONE = "none"
    UNKNOWN = "unknown"


class PermitStatus(StrEnum):
    REQUIRED = "required"
    RECOMMENDED = "recommended"
    NOT_REQUIRED = "not_required"
    UNKNOWN = "unknown"


class BudgetVerdict(StrEnum):
    """``INCOMPLETE`` when a cost component could not be priced at all."""

    ON_BUDGET = "on-budget"
    OVER_BUDGET = "over"
    UNDER_BUDGET = "under"
    INCOMPLETE = "incomplete"


class FinishReason(StrEnum):
    """Provider completion reasons that matter for structured-output handling."""

    STOP = "stop"
    LENGTH = "length"
    CONTENT_FILTER = "content_filter"
    TOOL_CALLS = "tool_calls"


# Meal types that map to a scheduled slot on a trip day, in service order.
ORDERED_MEAL_TYPES: tuple[MealType, ...] = (
    MealType.BREAKFAST,
    MealType.LUNCH,
    MealType.DINNER,
)

ORDERED_DAY_SLOTS: tuple[DaySlot, ...] = (
    DaySlot.MORNING,
    DaySlot.AFTERNOON,
    DaySlot.EVENING,
)
