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
from datetime import date, datetime, timedelta
from typing import Any

from pydantic import ValidationError

from app.agents.base import AgentClarificationMixin
from app.config import settings
from app.llm import get_llm, structured_llm
from app.logging import get_agent_logger
from app.models.clarification import ClarificationPrompt
from app.models.enums import LogEvent
from app.models.output.orchestrator_agent_output import FieldConfidence, ParsedQuery
from app.models.user_profile import (
    BudgetPreference,
    BudgetTier,
    TripDates,
    UserProfile,
    budget_to_state,
)
from app.prompts.orchestrator_agent_prompts import (
    FIELD_META,
    FOOD_CLARIFICATION_PROMPTS,
    OPTIONAL_CLARIFICATION_PROMPTS,
    QUERY_PARSE_PROMPT,
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
def _split_food_preference(value: str) -> list[str]:
    """Convert a comma-separated clarification answer to normalized values."""
    return [item.strip() for item in value.split(",") if item.strip()]


def _flexibility_prompt() -> ClarificationPrompt:
    """Date-flexibility question — text, config-driven, always skippable."""
    return ClarificationPrompt(
        field=settings.flexibility_days_field,
        question=settings.flexibility_days_prompt,
        reason="Widens the fare search window when dates can move",
        input_type="text",
        optional=True,
    )


def _parse_flexibility_answer(value: str) -> int | None:
    """Read a day count from a free-text answer, clamped to the configured maximum."""
    match = re.search(r"\d+", value)
    if not match:
        return None
    return min(int(match.group()), settings.flexibility_days_max)


# ── Structured LLM output ─────────────────────────────────────────────────────


# ── Clarification helper functions ────────────────────────────────────────────


def _is_blank(value: str | None) -> bool:
    return value is None or str(value).lower().strip() in ("", "unknown", "none")


def _build_clarification_prompt(field: str, extracted_value: str | None) -> ClarificationPrompt:
    """Build a contextual ClarificationPrompt for a missing/low-confidence field."""
    meta = FIELD_META.get(
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


def _field_values(parsed: ParsedQuery) -> dict[str, str | None]:
    """Map each clarification field to the value currently parsed for it."""
    return {
        "destination": parsed.destination.value,
        "source": parsed.source.value,
        "travelers": parsed.travelers.value,
        "dates": parsed.departure_date,
        "trip_days": str(parsed.trip_days) if parsed.trip_days is not None else None,
        "budget": parsed.budget_tier,
    }


def _field_confidences(parsed: ParsedQuery) -> dict[str, float]:
    return {
        "destination": parsed.destination.confidence,
        "source": parsed.source.confidence,
        "travelers": parsed.travelers.confidence,
        "dates": parsed.dates_confidence,
        "trip_days": parsed.trip_days_confidence,
        "budget": 1.0 if parsed.budget_tier else 0.0,
    }


def _compute_missing(parsed: ParsedQuery) -> list[tuple[str, str | None]]:
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


def _derive_is_international(parsed: ParsedQuery, log: Any) -> bool:
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


def _restore_parsed(payload: Any) -> ParsedQuery | None:
    """Rebuild the cached parse from state, or None when absent/incompatible."""
    if not isinstance(payload, dict):
        return None
    try:
        return ParsedQuery.model_validate(payload)
    except ValidationError:
        return None


def _confidence_map(parsed: ParsedQuery) -> dict[str, float]:
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


def _build_trip_dates(parsed: ParsedQuery, trip_days: int) -> TripDates:
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


def _apply_answers(parsed: ParsedQuery, answers: dict[str, str]) -> None:
    """Inject user's clarification answers directly into ``parsed`` at confidence=1.0."""
    if dest := answers.get("destination", "").strip():
        parsed.destination = FieldConfidence(value=dest, confidence=1.0)
    if source := answers.get("source", "").strip():
        parsed.source = FieldConfidence(value=source, confidence=1.0)
    if travelers_str := answers.get("travelers", "").strip():
        try:
            int(travelers_str)  # validate it's a number
            parsed.travelers = FieldConfidence(value=travelers_str, confidence=1.0)
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

    async def _parse_query(self, query: str, log: Any) -> ParsedQuery | None:
        """Run the single structured-output parse for this planning session."""
        chain = structured_llm(self._llm, ParsedQuery)
        try:
            raw = await chain.ainvoke(
                QUERY_PARSE_PROMPT.partial(today=date.today().isoformat()).format_messages(
                    query=query
                )
            )
        except Exception as exc:
            log.error(
                "llm_parse_failed",
                error=str(exc),
            )
            return None

        parsed = raw if isinstance(raw, ParsedQuery) else ParsedQuery.model_validate(raw)
        log.info(
            "llm_parse_result",
            query=query[:80],
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
        # Budget is not necessarily a configured clarification field, so it can be
        # absent without ever having been asked. Defaulting beats hard-stopping with
        # an empty missing-fields list, which tells the caller nothing.
        if not parsed.budget_tier:
            parsed.budget_tier = settings.default_budget_tier
            log.info(
                LogEvent.CLARIFICATION_RESOLVED,
                field="budget",
                resolution="default",
                value=parsed.budget_tier,
            )
        if trip_days is None or not parsed.departure_date:
            fields = [field for field, _ in _compute_missing(parsed)]
            log.warning(
                LogEvent.AGENT_FAILED,
                reason="required_trip_details_missing",
                has_trip_days=trip_days is not None,
                has_departure_date=bool(parsed.departure_date),
                fields=fields,
            )
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
        prompts.extend(prompt.model_copy() for prompt in OPTIONAL_CLARIFICATION_PROMPTS)

    profile: UserProfile | None = state.get("user_profile")
    ask_food = not (profile and profile.food_preferences_configured)
    if ask_food:
        prompts.extend(prompt.model_copy() for prompt in FOOD_CLARIFICATION_PROMPTS)

    dates = state.get("dates")
    # Opt-in like every other skippable question: it costs an interrupt/resume cycle.
    ask_flexibility = dates is not None and settings.enable_optional_clarification
    if ask_flexibility:
        prompts.append(_flexibility_prompt())

    if not prompts:
        return {}

    log.info(
        LogEvent.CLARIFICATION_REQUESTED,
        optional=True,
        fields=[prompt.field for prompt in prompts],
    )
    answers = ClarificationManager.request_optional(
        prompts, requester="orchestrator", round_number=state.get("clarification_round", 0)
    )

    food_fields = {"preferred_cuisines", "dietary_restrictions"}
    reserved_fields = food_fields | {settings.flexibility_days_field}
    updates: dict[str, Any] = {
        "optional_clarification_answers": {
            field: value
            for field, value in answers.items()
            if field not in reserved_fields and value.strip() and value.strip() != "__skip__"
        }
    }

    if ask_flexibility and dates is not None:
        raw = answers.get(settings.flexibility_days_field, "").strip()
        flexibility = None if raw in ("", "__skip__") else _parse_flexibility_answer(raw)
        resolved = flexibility if flexibility is not None else settings.flexibility_days_default
        updates["dates"] = dates.model_copy(update={"flexibility_days": resolved})
        log.info(
            LogEvent.CLARIFICATION_RESOLVED,
            field=settings.flexibility_days_field,
            value=resolved,
            resolution="answered" if flexibility is not None else "default",
        )

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
