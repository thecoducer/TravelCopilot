"""OrchestratorAgent — Layer 0: query parsing + intent detection + clarification gate.

Responsibilities:
  1. Parse the free-text user query into structured trip parameters, each with
     a ``parse_confidence`` score (0–1).
    2. Derive ``is_international`` from the parsed source/destination countries.
    3. Detect ``self_drive_intent`` from the structured parser output.
  4. Load ``UserProfile`` from DB by session_id (best-effort, non-blocking).
    5. Identify missing or low-confidence fields for the clarification manager.
  6. **Clarification gate**: the node itself never interrupts. It records the
     fields it still needs in ``pending_clarification_fields``; the separate
     ``orchestrator_clarification`` node performs the LangGraph ``interrupt()``
     and loops back. Keeping the interrupt out of this node matters because
     LangGraph re-executes a node from the top on every resume — with the pause
     inline, the LLM parse would re-run (and could return a different result)
     on every clarification round.

The parse is cached in ``parsed_query`` state, so the LLM runs once per
planning session regardless of how many clarification rounds are needed.
"""

from __future__ import annotations

import html
import re
import time
from datetime import date, datetime, timedelta
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, ValidationError

from app.agents.base import AgentClarificationMixin
from app.config import settings
from app.llm import get_llm, structured_llm
from app.logging import get_agent_logger
from app.models.clarification import ClarificationPrompt
from app.models.user_profile import (
    BudgetPreference,
    BudgetTier,
    TripDates,
    UserProfile,
    budget_to_state,
)
from app.services.clarification_manager import ClarificationManager
from app.services.user_profile_service import upsert_user_profile

# ── Security: prompt injection patterns ──────────────────────────────────────
_INJECTION_PATTERNS = re.compile(
    r"(ignore previous|disregard|system prompt|<\s*script|javascript:|"
    r"on\w+\s*=|prompt injection|forget instructions)",
    re.IGNORECASE,
)

# ── Field metadata for contextual clarification prompts ───────────────────────
_FIELD_META: dict[str, dict[str, Any]] = {
    "destination": {
        "input_type": "text",
        "options": [],
        "generic": "Where would you like to travel? Please name the city or region.",
        "contextual": "You mentioned '{value}' — which city or region specifically?",
    },
    "dates": {
        "input_type": "date",
        "options": [],
        "generic": "What is the start date of your trip?",
        "contextual": "When would you like to start your trip to '{value}'?",
    },
    "travelers": {
        "input_type": "number",
        "options": [],
        "generic": "How many people are travelling?",
        "contextual": "How many people will be going on the trip?",
    },
    "trip_days": {
        "input_type": "number",
        "options": [],
        "generic": "How many days is your trip?",
        "contextual": "You mentioned '{value}' days — is that the total length of your trip?",
    },
    "budget": {
        "input_type": "select",
        "options": ["budget", "mid", "luxury"],
        "generic": "What is your budget preference: budget, mid-range, or luxury?",
        "contextual": "You mentioned a {value} budget — is that right?",
    },
    "source": {
        "input_type": "text",
        "options": [],
        "generic": "What city will you be departing from?",
        "contextual": "Please provide the departure city.",
    },
    "query": {
        "input_type": "text",
        "options": [],
        "generic": (
            "Could you describe your trip in more detail?"
            " (e.g. 'I want to go to Leh from Kolkata for 5 days in July')"
        ),
        "contextual": "Could you describe your trip in more detail?",
    },
}

# Skippable questions asked once after the required fields resolve. The catalogue is
# fixed rather than LLM-generated so the prompts stay identical across graph resumes.
_OPTIONAL_CLARIFICATION_PROMPTS: tuple[ClarificationPrompt, ...] = (
    ClarificationPrompt(
        field="optional_pace",
        question="What pace would you like for this trip?",
        reason="Controls how many activities are scheduled per day",
        input_type="select",
        options=["relaxed", "balanced", "packed"],
        optional=True,
    ),
    ClarificationPrompt(
        field="optional_travel_style",
        question="Which travel style best describes this trip?",
        reason="Shapes stay and experience recommendations",
        input_type="select",
        options=["adventure", "cultural", "family", "backpacker", "luxury"],
        optional=True,
    ),
    ClarificationPrompt(
        field="optional_must_see",
        question="Anything you absolutely want to include?",
        reason="Guarantees a must-see place makes the itinerary",
        input_type="text",
        optional=True,
    ),
)

# Folded into the same clarification round as the optional catalogue (rather than a
# separate food_clarification graph node) so route discovery and supply search never
# stall waiting on a second human round-trip.
_FOOD_CLARIFICATION_PROMPTS: tuple[ClarificationPrompt, ...] = (
    ClarificationPrompt(
        field="preferred_cuisines",
        question="Which cuisines would you most like to eat on this trip?",
        reason="Personalize restaurant discovery",
        input_type="text",
        optional=True,
    ),
    ClarificationPrompt(
        field="dietary_restrictions",
        question="Do you have dietary restrictions or requirements?",
        reason="Avoid unsuitable restaurant recommendations",
        input_type="text",
        options=["No dietary restrictions"],
        optional=True,
    ),
)


def _split_food_preference(value: str) -> list[str]:
    """Convert a comma-separated clarification answer to normalized values."""
    return [item.strip() for item in value.split(",") if item.strip()]


# ── Structured LLM output ─────────────────────────────────────────────────────


class _FieldConfidence(BaseModel):
    value: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class _ParsedQuery(BaseModel):
    """Structured output from the orchestrator's LLM call."""

    source: _FieldConfidence = Field(
        default_factory=lambda: _FieldConfidence(value=None, confidence=0.0)
    )
    destination: _FieldConfidence = Field(
        default_factory=lambda: _FieldConfidence(value=None, confidence=0.0)
    )
    departure_date: str | None = Field(
        default=None, description="ISO-8601 departure date, null if not mentioned"
    )
    return_date: str | None = Field(
        default=None,
        description=("ISO-8601 return/end date if explicitly mentioned, otherwise null"),
    )
    # None means the query did not state or imply a duration — the compiler must
    # never guess this, so it is a first-class clarification field like ``dates``.
    trip_days: int | None = Field(
        default=None,
        ge=1,
        description="Total duration of the trip in days (e.g. 6 for 'for 6 days', 7 for '1 week')",
    )
    trip_days_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    travelers: _FieldConfidence = Field(
        default_factory=lambda: _FieldConfidence(value=None, confidence=0.0)
    )
    budget_tier: str | None = Field(
        default=None, description="budget | mid | luxury; null if not specified"
    )
    interests: list[str] = Field(default_factory=list)
    is_international: bool | None = Field(
        default=None,
        description=(
            "True for cross-border travel, false for same-country travel, "
            "null when geography is ambiguous"
        ),
    )
    self_drive_intent: bool = False
    dates_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source_country: str | None = Field(
        default=None,
        description="Country of the departure city, null when it cannot be determined",
    )
    destination_country: str | None = Field(
        default=None,
        description="Country of the destination, null when it cannot be determined",
    )


_SYSTEM_PROMPT = """\
You are a travel query parser. Extract structured fields from the user's trip request.
For each field that has ambiguity, set a lower confidence score.

Rules:
- source: return only the departure city name from phrases such as "from Kolkata", "departing from Mumbai", or "starting in Delhi". Do not include the state, region, or country. Return null with confidence=0.0 when no departure city is provided. If the city is ambiguous, lower its confidence and ask the user to clarify the city.
- destination: extract the complete requested place and its stated geographic context from phrases such as "to Arunachal Pradesh, India", "visit Tokyo, Japan", or "trip in Goa, India". Preserve the city, state/region, and country when provided. Return null with confidence=0.0 when no destination is provided.
- If the departure date is relative (e.g. "next month"), resolve to ISO-8601 assuming today is {today}.
- If no date is mentioned at all, set departure_date=null and dates_confidence=0.0.
- departure_date: extract the start date. return_date: extract an explicitly stated end or return date from phrases such as "returning on November 15", "until November 15", or "from November 11 to November 15". Resolve relative dates using today={today}, normalize both dates to ISO-8601, and set return_date=null when no return/end date is specified.
- trip_days: extract the duration of the trip in days (e.g. "sixteen days" -> "16", "6 days" -> 6, "10-day trip" -> 10, "1 week" -> 7, "weekend" -> 2). Convert number words to integers. If no duration is mentioned or implied at all, set trip_days=null and trip_days_confidence=0.0 — never guess a number.
- is_international: identify the country for both source and destination, including when a place is a state, region, or landmark. Set true when the trip crosses country borders (for example, "Kolkata to Tokyo", "New York to Paris", or "India to Bhutan"). Set false when both locations are in the same country (for example, "Kolkata to Goa" or "Mumbai to Ladakh"). Do not treat a region or destination name alone as international; use the source and destination together. Return null when either country cannot be determined reliably; do not guess domestic or international status.
- source_country / destination_country: always return the full English country name for each place when it can be identified from the place itself (for example, source="Kolkata" -> source_country="India"; destination="Sikkim" -> destination_country="India"; destination="Tokyo" -> destination_country="Japan"). Resolve states, regions, and landmarks to their country. Return null only when the place is genuinely absent or too ambiguous to place in a country.
- self_drive_intent: set true when the traveller wants to drive themselves or arrange a vehicle for the trip, including phrases such as "rent a car", "hire a scooter", "drive from Delhi to Manali", "road trip", "self-drive", "use our own car", or "motorbike trip". Set false for ordinary transport requests such as flights, trains, buses, taxis, or airport transfers when the traveller is not driving. Do not infer self-drive only from a destination being remote or scenic.
- budget_tier: extract an explicit budget preference only. Use "budget" for hostel/cheapest/backpacker, "luxury" for five-star/premium, and "mid" for mid-range/standard. If no preference is stated, return null; never assume "mid".
- For interests, extract: food, nightlife, history, adventure, photography, wellness, nature, art.
- Confidence rules (dates_confidence, trip_days_confidence): 1.0 = explicitly stated; 0.7 = strongly implied; 0.5 = inferred; 0.0 = absent.
- For travelers: confidence=1.0 for explicit phrases such as "2 people", "three people", "2 travelers", "three travelers", "there are 2 of us", "we are 2", or "a group of three". Convert number words to integers. If no traveler count is stated, return value=null and confidence=0.0; never assume one traveler.

Examples:
- "Plan 5 days in Tokyo from Kolkata" -> is_international=true, self_drive_intent=false.
- "Plan a trip to Darjeeling for 5 days for three people" -> travelers.value="3", travelers.confidence=1.0.
- "Plan a road trip from Mumbai to Goa in our own car" -> is_international=false, self_drive_intent=true.
- "Fly from Delhi to London and take trains between cities" -> is_international=true, self_drive_intent=false.
- "Rent a scooter in Goa" -> is_international=false, self_drive_intent=true.
- "Plan a trip from Springfield to Paris" -> is_international=null if the source country is not specified and Springfield is ambiguous.
"""  # noqa: E501


# ── Clarification helper functions ────────────────────────────────────────────


def _is_blank(value: str | None) -> bool:
    return value is None or str(value).lower().strip() in ("", "unknown", "none")


def _build_clarification_prompt(field: str, extracted_value: str | None) -> ClarificationPrompt:
    """Build a contextual ClarificationPrompt for a missing/low-confidence field."""
    meta = _FIELD_META.get(
        field,
        {
            "input_type": "text",
            "options": [],
            "generic": f"Could you clarify: {field}?",
            "contextual": f"Could you clarify: {field}?",
        },
    )
    if extracted_value and not _is_blank(extracted_value):
        question = meta["contextual"].format(value=extracted_value)
    else:
        question = meta["generic"]
    return ClarificationPrompt(
        field=field,
        question=question,
        reason=f"Missing or low-confidence value for '{field}'",
        input_type=meta["input_type"],
        options=meta.get("options", []),
        extracted_value=extracted_value if not _is_blank(extracted_value) else None,
    )


def _field_values(parsed: _ParsedQuery) -> dict[str, str | None]:
    """Map each clarification field to the value currently parsed for it."""
    return {
        "destination": parsed.destination.value,
        "source": parsed.source.value,
        "travelers": parsed.travelers.value,
        "dates": parsed.departure_date,
        "trip_days": str(parsed.trip_days) if parsed.trip_days is not None else None,
        "budget": parsed.budget_tier,
    }


def _field_confidences(parsed: _ParsedQuery) -> dict[str, float]:
    return {
        "destination": parsed.destination.confidence,
        "source": parsed.source.confidence,
        "travelers": parsed.travelers.confidence,
        "dates": parsed.dates_confidence,
        "trip_days": parsed.trip_days_confidence,
        "budget": 1.0 if parsed.budget_tier else 0.0,
    }


def _compute_missing(parsed: _ParsedQuery) -> list[tuple[str, str | None]]:
    """Return list of (field, extracted_value_or_None) for fields needing clarification."""
    field_values = _field_values(parsed)
    field_confidences = _field_confidences(parsed)
    thresholds = settings.field_thresholds
    fallback = settings.parse_confidence_threshold

    missing: list[tuple[str, str | None]] = []
    for field in settings.clarification_fields:
        threshold = thresholds.get(field, fallback)
        val = field_values.get(field)
        conf = field_confidences.get(field, 0.0)

        if _is_blank(val) or conf < threshold:
            extracted = None if _is_blank(val) else str(val)
            missing.append((field, extracted))
    return missing


def _derive_is_international(parsed: _ParsedQuery, log: Any) -> bool:
    """Resolve cross-border travel from the parsed countries instead of asking the user."""
    source_country = (parsed.source_country or "").strip().lower()
    destination_country = (parsed.destination_country or "").strip().lower()
    if source_country and destination_country:
        return source_country != destination_country
    if parsed.is_international is not None:
        return parsed.is_international
    log.warning(
        "is_international_defaulted_domestic",
        source_country=parsed.source_country,
        destination_country=parsed.destination_country,
    )
    return False


def _restore_parsed(payload: Any) -> _ParsedQuery | None:
    """Rebuild the cached parse from state, or None when absent/incompatible."""
    if not isinstance(payload, dict):
        return None
    try:
        return _ParsedQuery.model_validate(payload)
    except ValidationError:
        return None


def _confidence_map(parsed: _ParsedQuery) -> dict[str, float]:
    return {
        "destination": parsed.destination.confidence,
        "source": parsed.source.confidence,
        "travelers": parsed.travelers.confidence,
        "dates": parsed.dates_confidence,
        "trip_days": parsed.trip_days_confidence,
    }


_MISSING_DETAILS_ERROR = "Required trip details are still missing."


def _hard_stop(message: str, fields: list[str]) -> dict[str, Any]:
    """Stop planning rather than fabricating required trip details."""
    return {
        "error": message,
        "missing_required_fields": fields,
        "pending_clarification_fields": [],
    }


def _build_trip_dates(parsed: _ParsedQuery, trip_days: int) -> TripDates:
    span = timedelta(days=max(0, trip_days - 1))
    try:
        departure = date.fromisoformat(parsed.departure_date or "")
        return_date = (
            date.fromisoformat(parsed.return_date) if parsed.return_date else departure + span
        )
    except ValueError:
        departure = date.today() + timedelta(days=30)
        return_date = departure + span
    return TripDates(departure=departure, return_date=return_date)


def _parse_date_answer(dates_str: str) -> tuple[str | None, str | None, float]:
    """Parse a user-provided start date string (HTML date picker YYYY-MM-DD or DD/MM/YYYY).

    Returns ``(departure_iso, return_iso_or_None, confidence)``.
    """
    cleaned = dates_str.strip()
    if not cleaned:
        return None, None, 0.0

    # 1. ISO format: "YYYY-MM-DD" or "YYYY/MM/DD" (native HTML5 date picker output)
    try:
        dep = date.fromisoformat(cleaned.replace("/", "-"))
        return dep.isoformat(), None, 1.0
    except ValueError:
        pass

    # 2. "DD/MM/YYYY" or "DD-MM-YYYY" format
    for fmt in ("%d/%m/%Y", "%d-%m-%Y"):
        try:
            dep = datetime.strptime(cleaned, fmt).date()
            return dep.isoformat(), None, 1.0
        except ValueError:
            pass

    return None, None, 0.0


def _apply_answers(parsed: _ParsedQuery, answers: dict[str, str]) -> None:
    """Inject user's clarification answers directly into ``parsed`` at confidence=1.0."""
    if dest := answers.get("destination", "").strip():
        parsed.destination = _FieldConfidence(value=dest, confidence=1.0)
    if source := answers.get("source", "").strip():
        parsed.source = _FieldConfidence(value=source, confidence=1.0)
    if travelers_str := answers.get("travelers", "").strip():
        try:
            int(travelers_str)  # validate it's a number
            parsed.travelers = _FieldConfidence(value=travelers_str, confidence=1.0)
        except ValueError:
            pass
    if trip_days_str := answers.get("trip_days", "").strip():
        try:
            parsed.trip_days = max(1, int(trip_days_str))
            parsed.trip_days_confidence = 1.0
        except ValueError:
            pass
    if (budget := answers.get("budget", "").strip().lower()) and budget in {
        tier.value for tier in BudgetTier
    }:
        parsed.budget_tier = budget
    if trip_type := answers.get("is_international", "").strip().lower():
        if trip_type in {"international", "international trip"}:
            parsed.is_international = True
        elif trip_type in {"domestic", "domestic trip"}:
            parsed.is_international = False
    if dates_str := answers.get("dates", "").strip():
        dep_iso, ret_iso, conf = _parse_date_answer(dates_str)
        # An unparseable answer must not clear a date the parser already resolved.
        if dep_iso:
            parsed.departure_date = dep_iso
            if ret_iso:
                parsed.return_date = ret_iso
            parsed.dates_confidence = conf


class OrchestratorAgent(AgentClarificationMixin):
    def __init__(self, llm: Any | None = None) -> None:
        self._llm = llm or get_llm("orchestrator")

    async def _parse_query(self, query: str, log: Any) -> _ParsedQuery | None:
        """Run the single structured-output parse for this planning session."""
        chain = structured_llm(self._llm, _ParsedQuery)
        started = time.perf_counter()
        try:
            raw = await chain.ainvoke(
                [
                    SystemMessage(content=_SYSTEM_PROMPT.format(today=date.today().isoformat())),
                    HumanMessage(content=f"User query: {query}"),
                ]
            )
        except Exception as exc:
            log.error(
                "llm_parse_failed",
                error=str(exc),
                latency_ms=round((time.perf_counter() - started) * 1000, 1),
            )
            return None

        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        parsed = raw if isinstance(raw, _ParsedQuery) else _ParsedQuery.model_validate(raw)
        log.info(
            "llm_parse_result",
            query=query[:80],
            latency_ms=latency_ms,
            parsed=parsed.model_dump(mode="json"),
        )
        return parsed

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        session_id: str = state.get("session_id", "")
        clarification_round: int = state.get("clarification_round", 0)
        answers: dict[str, str] = dict(state.get("clarification_answers") or {})
        log = get_agent_logger("orchestrator", session_id)

        restated = html.unescape(answers.get("query", "")).strip()[:500]
        query = restated or html.unescape(state.get("query", "")).strip()[:500]
        log.info("agent_start", query=query[:80], round=clarification_round)

        rounds_left = clarification_round < settings.max_clarification_rounds

        if _INJECTION_PATTERNS.search(query):
            log.warning("prompt_injection_detected")
            if not rounds_left:
                return _hard_stop("Your request could not be parsed safely.", ["query"])
            return {"parsed_query": None, "pending_clarification_fields": ["query"]}

        parsed = _restore_parsed(state.get("parsed_query"))
        if parsed is None:
            parsed = await self._parse_query(query, log)
        if parsed is None:
            if not rounds_left:
                return _hard_stop("Failed to parse trip query", ["query"])
            return {"pending_clarification_fields": ["query"]}

        extracted_days = quick_extract_days(query)
        if extracted_days is not None:
            parsed.trip_days = extracted_days
            parsed.trip_days_confidence = 1.0

        _apply_answers(parsed, answers)
        is_intl = _derive_is_international(parsed, log)
        parsed.is_international = is_intl

        # A field answered once is never re-asked; a useless answer fails the gate below
        # instead of restarting the question loop.
        missing = [(f, v) for f, v in _compute_missing(parsed) if not answers.get(f, "").strip()]
        base_updates: dict[str, Any] = {
            "parsed_query": parsed.model_dump(mode="json"),
            "parse_confidence": _confidence_map(parsed),
        }
        log.info(
            "clarification_gate",
            missing=[field for field, _ in missing],
            round=clarification_round,
        )

        if missing:
            fields = [field for field, _ in missing]
            if not rounds_left:
                log.warning("max_clarification_rounds_exhausted", rounds=clarification_round)
                return {**base_updates, **_hard_stop(_MISSING_DETAILS_ERROR, fields)}
            return {**base_updates, "pending_clarification_fields": fields}

        trip_days = parsed.trip_days
        if trip_days is None or not parsed.departure_date or not parsed.budget_tier:
            fields = [field for field, _ in _compute_missing(parsed)]
            return {**base_updates, **_hard_stop(_MISSING_DETAILS_ERROR, fields)}

        trip_dates = _build_trip_dates(parsed, trip_days)
        budget = budget_to_state(BudgetPreference(tier=BudgetTier(parsed.budget_tier)))

        try:
            travelers = max(1, int(parsed.travelers.value or 1))
        except (ValueError, TypeError):
            travelers = 1

        destination = (parsed.destination.value or "").strip()
        source = (parsed.source.value or "").strip()

        updates: dict[str, Any] = {
            **base_updates,
            "source": source,
            "destination": destination,
            "dates": trip_dates,
            "travelers": travelers,
            "budget": budget,
            "is_international": is_intl,
            "self_drive_intent": parsed.self_drive_intent,
            "missing_required_fields": [],
            "pending_clarification_fields": [],
        }

        # Bootstrap user profile from interests
        if parsed.interests:
            existing = state.get("user_profile")
            if existing:
                merged = list(set(existing.interests) | set(parsed.interests))
                updates["user_profile"] = existing.model_copy(update={"interests": merged})
            else:
                updates["user_profile"] = UserProfile(
                    user_id=session_id or "anon",
                    interests=parsed.interests,
                )

        log.info(
            "agent_done",
            source=source,
            destination=destination,
            is_international=is_intl,
            self_drive=parsed.self_drive_intent,
            rounds=clarification_round,
        )
        return updates


async def orchestrator_clarification_node(state: dict[str, Any]) -> dict[str, Any]:
    """Pause the graph for the fields the orchestrator flagged, then loop back to it.

    This node holds the only orchestrator ``interrupt()``. It performs no LLM work, so
    LangGraph's re-execution of the node on resume is free and deterministic.
    """
    session_id = state.get("session_id", "")
    round_number = state.get("clarification_round", 0)
    fields = list(state.get("pending_clarification_fields") or [])
    log = get_agent_logger("orchestrator", session_id)

    parsed = _restore_parsed(state.get("parsed_query"))
    values = _field_values(parsed) if parsed else {}
    prompts = [_build_clarification_prompt(field, values.get(field)) for field in fields]
    log.info("clarification_required", fields=fields, round=round_number)

    answers = ClarificationManager.request(
        prompts, requester="orchestrator", round_number=round_number
    )
    merged = {
        **(state.get("clarification_answers") or {}),
        **{field: value for field, value in answers.items() if value.strip()},
    }
    return {
        "clarification_answers": merged,
        "clarification_round": round_number + 1,
        "pending_clarification_fields": [],
    }


async def optional_clarification_node(state: dict[str, Any]) -> dict[str, Any]:
    """Ask skippable trip-style questions and durable food preferences in one round.

    Food preferences are folded in here (rather than a separate later graph node)
    so route discovery and supply search never stall on a second human round-trip.
    """
    session_id = state.get("session_id", "")
    log = get_agent_logger("orchestrator", session_id)

    prompts: list[ClarificationPrompt] = []
    if settings.enable_optional_clarification:
        prompts.extend(prompt.model_copy() for prompt in _OPTIONAL_CLARIFICATION_PROMPTS)

    profile: UserProfile | None = state.get("user_profile")
    ask_food = not (profile and profile.food_preferences_configured)
    if ask_food:
        prompts.extend(prompt.model_copy() for prompt in _FOOD_CLARIFICATION_PROMPTS)

    if not prompts:
        return {}

    log.info("optional_clarification_requested", fields=[prompt.field for prompt in prompts])
    answers = ClarificationManager.request_optional(
        prompts, requester="orchestrator", round_number=state.get("clarification_round", 0)
    )

    food_fields = {"preferred_cuisines", "dietary_restrictions"}
    updates: dict[str, Any] = {
        "optional_clarification_answers": {
            field: value
            for field, value in answers.items()
            if field not in food_fields and value.strip() and value.strip() != "__skip__"
        }
    }

    if ask_food:
        dietary_answer = answers.get("dietary_restrictions", "").strip()
        dietary = (
            []
            if dietary_answer.lower() in ("", "__skip__", "no dietary restrictions")
            else _split_food_preference(dietary_answer)
        )
        cuisines_answer = answers.get("preferred_cuisines", "").strip()
        cuisines = (
            [] if cuisines_answer in ("", "__skip__") else _split_food_preference(cuisines_answer)
        )
        updated_profile = (profile or UserProfile(user_id=session_id or "anon")).model_copy(
            update={
                "preferred_cuisines": cuisines,
                "dietary_restrictions": dietary,
                "food_preferences_configured": True,
            }
        )
        if session_id:
            try:
                await upsert_user_profile(session_id, updated_profile)
            except Exception as exc:
                log.warning("profile_persist_failed", error=str(exc))
        updates["user_profile"] = updated_profile

    return updates


# ── Helper ───────────────────────────────────────────────────────────────────

_DAYS_PATTERN = re.compile(r"\b(\d+)\s*[- ]?days?\b", re.IGNORECASE)
_NIGHTS_PATTERN = re.compile(r"\b(\d+)\s*[- ]?nights?\b", re.IGNORECASE)
_WEEKS_PATTERN = re.compile(r"\b(\d+)\s*[- ]?weeks?\b", re.IGNORECASE)


def quick_extract_days(query: str) -> int | None:
    """Return number of trip days from a query string if mentioned."""
    if not query:
        return None
    m = _DAYS_PATTERN.search(query)
    if m:
        return max(1, int(m.group(1)))
    m_nights = _NIGHTS_PATTERN.search(query)
    if m_nights:
        return max(1, int(m_nights.group(1)) + 1)
    m_weeks = _WEEKS_PATTERN.search(query)
    if m_weeks:
        return max(1, int(m_weeks.group(1)) * 7)
    if re.search(r"\ba\s+week\b|\bone\s+week\b", query, re.IGNORECASE):
        return 7
    if re.search(r"\bweekend\b", query, re.IGNORECASE):
        return 2
    return None
