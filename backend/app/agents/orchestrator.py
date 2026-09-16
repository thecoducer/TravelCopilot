"""OrchestratorAgent — Layer 0: query parsing + intent detection + clarification gate.

Responsibilities:
  1. Parse the free-text user query into structured trip parameters, each with
     a ``parse_confidence`` score (0–1).
    2. Detect ``is_international`` (compares source vs destination country).
    3. Detect ``self_drive_intent`` from the structured parser output.
  4. Load ``UserProfile`` from DB by session_id (best-effort, non-blocking).
    5. Identify missing or low-confidence fields for the clarification manager.
  6. **Clarification gate**: if required fields remain missing or low-confidence
     after profile pre-fill, use LangGraph ``interrupt()`` to pause the graph
     and await structured answers from the client.  The graph resumes via
     ``POST /api/trip/{session_id}/clarify`` — no full re-POST needed.
    Up to ``settings.max_clarification_rounds`` rounds are attempted; after
    that unresolved required fields produce a hard stop.
"""

from __future__ import annotations

import html
import re
from datetime import date, datetime, timedelta
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.agents.base import AgentClarificationMixin
from app.config import settings
from app.llm import get_llm
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
    "is_international": {
        "input_type": "select",
        "options": ["domestic", "international"],
        "generic": "Is this a domestic trip or an international trip?",
        "contextual": "Is this a domestic trip or an international trip?",
    },
}


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


_SYSTEM_PROMPT = """\
You are a travel query parser. Extract structured fields from the user's trip request.
For each field that has ambiguity, set a lower confidence score.

Rules:
- source: return only the departure city name from phrases such as "from Kolkata", "departing from Mumbai", or "starting in Delhi". Do not include the state, region, or country. Return null with confidence=0.0 when no departure city is provided. If the city is ambiguous, lower its confidence and ask the user to clarify the city.
- destination: extract the complete requested place and its stated geographic context from phrases such as "to Arunachal Pradesh, India", "visit Tokyo, Japan", or "trip in Goa, India". Preserve the city, state/region, and country when provided. Return null with confidence=0.0 when no destination is provided.
- If the departure date is relative (e.g. "next month"), resolve to ISO-8601 assuming today is {today}.
- If no date is mentioned at all, set departure_date=null and dates_confidence=0.0.
- departure_date: extract the start date. return_date: extract an explicitly stated end or return date from phrases such as "returning on November 15", "until November 15", or "from November 11 to November 15". Resolve relative dates using today={today}, normalize both dates to ISO-8601, and set return_date=null when no return/end date is specified.
- trip_days: extract the duration of the trip in days (e.g. "6 days" -> 6, "10-day trip" -> 10, "1 week" -> 7, "weekend" -> 2). If no duration is mentioned or implied at all, set trip_days=null and trip_days_confidence=0.0 — never guess a number.
- is_international: identify the country for both source and destination, including when a place is a state, region, or landmark. Set true when the trip crosses country borders (for example, "Kolkata to Tokyo", "New York to Paris", or "India to Bhutan"). Set false when both locations are in the same country (for example, "Kolkata to Goa" or "Mumbai to Ladakh"). Do not treat a region or destination name alone as international; use the source and destination together. Return null when either country cannot be determined reliably; do not guess domestic or international status.
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


def _compute_missing(parsed: _ParsedQuery) -> list[tuple[str, str | None]]:
    """Return list of (field, extracted_value_or_None) for fields needing clarification."""
    field_values: dict[str, str | None] = {
        "destination": parsed.destination.value,
        "source": parsed.source.value,
        "travelers": parsed.travelers.value,
        "dates": parsed.departure_date,
        "trip_days": str(parsed.trip_days) if parsed.trip_days is not None else None,
        "budget": parsed.budget_tier,
        "is_international": (
            "international"
            if parsed.is_international is True
            else "domestic"
            if parsed.is_international is False
            else None
        ),
    }
    field_confidences: dict[str, float] = {
        "destination": parsed.destination.confidence,
        "source": parsed.source.confidence,
        "travelers": parsed.travelers.confidence,
        "dates": parsed.dates_confidence,
        "trip_days": parsed.trip_days_confidence,
        "budget": 1.0 if parsed.budget_tier else 0.0,
        "is_international": 1.0 if parsed.is_international is not None else 0.0,
    }
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

    if parsed.is_international is None and not any(
        field == "is_international" for field, _ in missing
    ):
        missing.append(("is_international", None))
    return missing


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
        if dep_iso:
            parsed.departure_date = dep_iso
            if ret_iso:
                parsed.return_date = ret_iso
        parsed.dates_confidence = conf


class OrchestratorAgent(AgentClarificationMixin):
    def __init__(self, llm: Any | None = None) -> None:
        self._llm = llm or get_llm("orchestrator")

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        raw_query: str = state.get("query", "")
        session_id: str = state.get("session_id", "")
        clarification_round: int = state.get("clarification_round", 0)
        query = html.unescape(raw_query).strip()[:500]
        log = get_agent_logger("orchestrator", session_id)
        log.info("agent_start", query=query[:80])

        parsed: _ParsedQuery | None = None
        rounds_taken = 0
        optional_answers: dict[str, str] = {}

        for _round in range(settings.max_clarification_rounds):
            # ── Injection check ──────────────────────────────────────────────
            if _INJECTION_PATTERNS.search(query):
                log.warning("prompt_injection_detected", session_id=session_id)
                prompts = [
                    ClarificationPrompt(
                        field="query",
                        question=(
                            "Your request contains disallowed patterns."
                            " Please describe your trip normally."
                        ),
                        reason="Prompt injection detected",
                        input_type="text",
                    )
                ]
                answers = ClarificationManager.request(
                    prompts, requester="orchestrator", round_number=_round
                )
                new_q = html.unescape(answers.get("query", "")).strip()[:500]
                if new_q:
                    query = new_q
                parsed = None  # force re-parse with cleaned query
                rounds_taken += 1
                continue

            # ── LLM parse (only on first pass or after query change) ─────────
            if parsed is None:
                today = date.today().isoformat()
                chain = self._llm.with_structured_output(_ParsedQuery)
                try:
                    parsed = await chain.ainvoke(
                        [
                            SystemMessage(content=_SYSTEM_PROMPT.format(today=today)),
                            HumanMessage(content=f"User query: {query}"),
                        ]
                    )
                except Exception as exc:
                    log.error("llm_parse_failed", error=str(exc))
                    prompts = [
                        ClarificationPrompt(
                            field="query",
                            question=(
                                "Could you describe your trip in more detail?"
                                " (e.g. 'I want to go to Leh from Kolkata"
                                " for 5 days in July')"
                            ),
                            reason="LLM parsing failed",
                            input_type="text",
                        )
                    ]
                    answers = ClarificationManager.request(
                        prompts, requester="orchestrator", round_number=_round
                    )
                    new_q = html.unescape(answers.get("query", "")).strip()[:500]
                    if new_q:
                        query = new_q
                    rounds_taken += 1
                    continue

            # Deterministic override for trip duration if explicitly stated in query
            extracted_days = quick_extract_days(query)
            if extracted_days is not None and parsed is not None:
                parsed.trip_days = extracted_days
                parsed.trip_days_confidence = 1.0

            # ── Compute missing / low-confidence fields ──────────────────────
            missing = _compute_missing(parsed)
            if not missing:
                optional_answers = await self.ask_optional_clarification(
                    self._llm,
                    state,
                    requester="orchestrator",
                    round_number=_round,
                    context=f"Parsed trip request: {query}",
                )
                break  # all required fields satisfied

            # ── Interrupt: pause graph and await client answers ──────────────
            log.info(
                "clarification_required",
                fields=[f for f, _ in missing],
                round=_round,
            )
            prompts = [_build_clarification_prompt(f, ev) for f, ev in missing]
            answers = ClarificationManager.request(
                prompts, requester="orchestrator", round_number=_round
            )
            _apply_answers(parsed, answers)
            rounds_taken += 1

        else:
            # Required fields must never be fabricated after clarification runs out.
            log.warning(
                "max_clarification_rounds_exhausted",
                rounds=settings.max_clarification_rounds,
            )
            return {
                "error": "Required trip details are still missing.",
                "missing_required_fields": [field for field, _ in _compute_missing(parsed)]
                if parsed is not None
                else list(settings.clarification_fields),
                "parse_confidence": {},
                "clarification_round": clarification_round + rounds_taken,
            }

        if parsed is None:
            # Should not happen, but guard defensively
            return {
                "error": "Failed to parse trip query",
                "parse_confidence": {},
                "clarification_round": clarification_round + rounds_taken,
            }

        # ── Build parse_confidence map ────────────────────────────────────────
        parse_confidence: dict[str, float] = {
            "destination": parsed.destination.confidence,
            "source": parsed.source.confidence,
            "travelers": parsed.travelers.confidence,
            "dates": parsed.dates_confidence,
            "trip_days": parsed.trip_days_confidence,
        }

        trip_days = parsed.trip_days
        if (
            trip_days is None
            or not parsed.departure_date
            or not parsed.budget_tier
            or parsed.is_international is None
        ):
            return {
                "error": "Required trip details are still missing.",
                "missing_required_fields": [field for field, _ in _compute_missing(parsed)],
                "parse_confidence": parse_confidence,
                "clarification_round": clarification_round + rounds_taken,
            }

        # ── Build TripDates ───────────────────────────────────────────────────
        trip_dates: TripDates | None = None
        if parsed.departure_date:
            try:
                dep = date.fromisoformat(parsed.departure_date)
                ret = (
                    date.fromisoformat(parsed.return_date)
                    if parsed.return_date
                    else dep + timedelta(days=max(0, trip_days - 1))
                )
                trip_dates = TripDates(departure=dep, return_date=ret)
            except ValueError:
                dep = date.today() + timedelta(days=30)
                trip_dates = TripDates(
                    departure=dep,
                    return_date=dep + timedelta(days=max(0, trip_days - 1)),
                )
        else:
            dep = date.today() + timedelta(days=30)
            trip_dates = TripDates(
                departure=dep,
                return_date=dep + timedelta(days=max(0, trip_days - 1)),
            )

        tier = BudgetTier(parsed.budget_tier)
        budget = budget_to_state(BudgetPreference(tier=tier))

        try:
            travelers = max(1, int(parsed.travelers.value or 1))
        except (ValueError, TypeError):
            travelers = 1

        destination = (parsed.destination.value or "").strip()
        source = (parsed.source.value or "").strip()

        is_intl = parsed.is_international

        self_drive = parsed.self_drive_intent

        updates: dict[str, Any] = {
            "source": source,
            "destination": destination,
            "dates": trip_dates,
            "travelers": travelers,
            "budget": budget,
            "is_international": is_intl,
            "self_drive_intent": self_drive,
            "parse_confidence": parse_confidence,
            "clarification_round": clarification_round + rounds_taken,
            "optional_clarification_answers": optional_answers,
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
            self_drive=self_drive,
            rounds=rounds_taken,
        )
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
