"""OrchestratorAgent — Layer 0: query parsing + intent detection + clarification gate.

Responsibilities:
  1. Parse the free-text user query into structured trip parameters, each with
     a ``parse_confidence`` score (0–1).
  2. Detect ``is_international`` (compares source vs destination country).
  3. Detect ``self_drive_intent`` from keywords.
  4. Load ``UserProfile`` from DB by session_id (best-effort, non-blocking).
  5. **UserProfile pre-fill**: silently resolve missing fields (source city,
     budget tier) from the user's saved profile before triggering clarification.
  6. **Clarification gate**: if required fields remain missing or low-confidence
     after profile pre-fill, use LangGraph ``interrupt()`` to pause the graph
     and await structured answers from the client.  The graph resumes via
     ``POST /api/trip/{session_id}/clarify`` — no full re-POST needed.
     Up to ``settings.max_clarification_rounds`` rounds are attempted; after
     that the agent proceeds with best-effort defaults.
"""

from __future__ import annotations

import html
import re
from datetime import date, timedelta
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from app.config import settings
from app.llm import get_llm
from app.models.user_profile import (
    BudgetPreference,
    BudgetTier,
    ClarificationPrompt,
    TripDates,
    UserProfile,
)

logger = structlog.get_logger(__name__)

# ── Security: prompt injection patterns ──────────────────────────────────────
_INJECTION_PATTERNS = re.compile(
    r"(ignore previous|disregard|system prompt|<\s*script|javascript:|"
    r"on\w+\s*=|prompt injection|forget instructions)",
    re.IGNORECASE,
)

# ── Domestic city set (for is_international heuristic) ──────────────────────
_INDIAN_CITIES: frozenset[str] = frozenset(
    [
        "mumbai",
        "delhi",
        "bangalore",
        "bengaluru",
        "kolkata",
        "chennai",
        "hyderabad",
        "pune",
        "ahmedabad",
        "jaipur",
        "lucknow",
        "kanpur",
        "nagpur",
        "indore",
        "bhopal",
        "goa",
        "leh",
        "srinagar",
        "amritsar",
        "varanasi",
        "agra",
        "kerala",
        "rajasthan",
        "himachal",
        "uttarakhand",
        "sikkim",
        "assam",
        "kochi",
        "udaipur",
        "jodhpur",
        "mysore",
        "coimbatore",
        "madurai",
        "nashik",
        "aurangabad",
        "chandigarh",
        "shimla",
        "manali",
        "mcleod ganj",
        "darjeeling",
        "gangtok",
        "pondicherry",
        "guwahati",
        "bhubaneswar",
        "patna",
        "ranchi",
        "raipur",
        "visakhapatnam",
        "vijayawada",
    ]
)

_SELF_DRIVE_KEYWORDS = frozenset(
    [
        "rent a bike",
        "rent bike",
        "scooter",
        "self-drive",
        "self drive",
        "motorcycle",
        "hire a car",
        "hire car",
        "rent a car",
        "road trip",
        "road-trip",
        "motorbike",
        "two-wheeler",
    ]
)

# Required fields — trigger clarification gate if missing/low-confidence
_REQUIRED_FIELDS: list[str] = ["destination", "dates", "travelers"]

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
        "generic": (
            "What dates are you planning to travel? (e.g. 'July 15–20' or '5 days in October')"
        ),
        "contextual": ("You mentioned '{value}' — what dates specifically? (e.g. 'July 15–20')"),
    },
    "travelers": {
        "input_type": "number",
        "options": [],
        "generic": "How many people are travelling? (including yourself)",
        "contextual": "How many people are travelling? (including yourself)",
    },
    "source": {
        "input_type": "text",
        "options": [],
        "generic": "What city will you be departing from?",
        "contextual": (
            "We guessed you're departing from '{value}' — is that right?"
            " If not, please provide your departure city."
        ),
    },
}

# ── Month name map for date parsing ───────────────────────────────────────────
_MONTH_MAP: dict[str, int] = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


# ── Structured LLM output ─────────────────────────────────────────────────────


class _FieldConfidence(BaseModel):
    value: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class _ParsedQuery(BaseModel):
    """Structured output from the orchestrator's LLM call."""

    source_city: _FieldConfidence = Field(
        default_factory=lambda: _FieldConfidence(value="unknown", confidence=0.5)
    )
    destination: _FieldConfidence = Field(
        default_factory=lambda: _FieldConfidence(value=None, confidence=0.0)
    )
    departure_date: str | None = Field(
        default=None, description="ISO-8601 departure date, null if not mentioned"
    )
    return_date: str | None = None
    trip_days: int = Field(default=3, ge=1)
    travelers: _FieldConfidence = Field(
        default_factory=lambda: _FieldConfidence(value="1", confidence=0.8)
    )
    budget_tier: str = Field(default="mid", description="budget | mid | luxury")
    interests: list[str] = Field(default_factory=list)
    is_international: bool = False
    self_drive_intent: bool = False
    dates_confidence: float = Field(default=0.0, ge=0.0, le=1.0)


_SYSTEM_PROMPT = """\
You are a travel query parser. Extract structured fields from the user's trip request.
For each field that has ambiguity, set a lower confidence score.

Rules:
- If the departure date is relative (e.g. "next month"), resolve to ISO-8601 assuming today is {today}.
- If no date is mentioned at all, set departure_date=null and dates_confidence=0.0.
- Set is_international=true only when source and destination are clearly in different countries.
- Set self_drive_intent=true when the user explicitly mentions renting a vehicle or driving.
- budget_tier: "budget" for hostel/cheapest/backpacker; "luxury" for five-star/premium; else "mid".
- For interests, extract: food, nightlife, history, adventure, photography, wellness, nature, art.
- Confidence rules: 1.0 = explicitly stated; 0.7 = strongly implied; 0.5 = inferred; 0.0 = absent.
- For travelers: confidence=1.0 if explicitly stated, 0.8 if implied solo (no mention), 0.5 if ambiguous.
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


def _apply_profile_prefill(parsed: _ParsedQuery, user_profile: UserProfile | None) -> None:
    """Silently fill missing fields from the user's saved profile (idempotent)."""
    if not user_profile:
        return
    if _is_blank(parsed.source_city.value) and user_profile.home_city:
        parsed.source_city = _FieldConfidence(value=user_profile.home_city, confidence=1.0)
    # Only override budget tier when LLM used the default "mid" — not when explicitly detected
    if parsed.budget_tier == "mid" and user_profile.budget_tier:
        parsed.budget_tier = str(user_profile.budget_tier)


def _compute_missing(parsed: _ParsedQuery) -> list[tuple[str, str | None]]:
    """Return list of (field, extracted_value_or_None) for fields needing clarification."""
    field_values: dict[str, str | None] = {
        "destination": parsed.destination.value,
        "source": parsed.source_city.value,
        "travelers": parsed.travelers.value,
        "dates": parsed.departure_date,
    }
    field_confidences: dict[str, float] = {
        "destination": parsed.destination.confidence,
        "source": parsed.source_city.confidence,
        "travelers": parsed.travelers.confidence,
        "dates": parsed.dates_confidence,
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
    return missing


def _parse_date_answer(dates_str: str) -> tuple[str | None, str | None, float]:
    """Parse a user-provided date string.

    Returns ``(departure_iso, return_iso_or_None, confidence)``.
    """
    dates_str = dates_str.strip()
    year = date.today().year

    # ISO format: "2026-07-15"
    try:
        dep = date.fromisoformat(dates_str)
        return dep.isoformat(), None, 1.0
    except ValueError:
        pass

    # "Month DD-DD" or "Month DD to DD" (e.g. "July 15-20", "July 15 to 20")
    m = re.match(r"([a-zA-Z]+)\s+(\d{1,2})\s*[-\u2013to]+\s*(\d{1,2})", dates_str, re.IGNORECASE)
    if m:
        month_key = m.group(1).lower()[:3]
        month = _MONTH_MAP.get(month_key)
        if month:
            try:
                dep = date(year, month, int(m.group(2)))
                ret = date(year, month, int(m.group(3)))
                return dep.isoformat(), ret.isoformat(), 0.9
            except ValueError:
                pass

    # "Month DD" (e.g. "July 15")
    m2 = re.match(r"([a-zA-Z]+)\s+(\d{1,2})", dates_str, re.IGNORECASE)
    if m2:
        month_key = m2.group(1).lower()[:3]
        month = _MONTH_MAP.get(month_key)
        if month:
            try:
                dep = date(year, month, int(m2.group(2)))
                return dep.isoformat(), None, 0.8
            except ValueError:
                pass

    # Can't parse precisely — but user gave SOME date info; treat as high enough confidence
    return None, None, 0.7


def _apply_answers(parsed: _ParsedQuery, answers: dict[str, str]) -> None:
    """Inject user's clarification answers directly into ``parsed`` at confidence=1.0."""
    if dest := answers.get("destination", "").strip():
        parsed.destination = _FieldConfidence(value=dest, confidence=1.0)
    if source := answers.get("source", "").strip():
        parsed.source_city = _FieldConfidence(value=source, confidence=1.0)
    if travelers_str := answers.get("travelers", "").strip():
        try:
            int(travelers_str)  # validate it's a number
            parsed.travelers = _FieldConfidence(value=travelers_str, confidence=1.0)
        except ValueError:
            pass
    if dates_str := answers.get("dates", "").strip():
        dep_iso, ret_iso, conf = _parse_date_answer(dates_str)
        if dep_iso:
            parsed.departure_date = dep_iso
            if ret_iso:
                parsed.return_date = ret_iso
        parsed.dates_confidence = conf


def _apply_defaults(parsed: _ParsedQuery) -> None:
    """Fallback: set reasonable defaults for still-missing fields after max rounds."""
    if _is_blank(parsed.destination.value):
        parsed.destination = _FieldConfidence(value="unknown destination", confidence=0.5)
    if not parsed.departure_date:
        parsed.departure_date = (date.today() + timedelta(days=30)).isoformat()
        parsed.dates_confidence = 0.5
    if _is_blank(parsed.travelers.value) or parsed.travelers.confidence < 0.4:
        parsed.travelers = _FieldConfidence(value="1", confidence=0.8)


class OrchestratorAgent:
    def __init__(self, llm: object | None = None) -> None:
        self._llm = llm or get_llm("orchestrator")

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        raw_query: str = state.get("query", "")
        session_id: str = state.get("session_id", "")
        clarification_round: int = state.get("clarification_round", 0)
        user_profile: UserProfile | None = state.get("user_profile")

        query = html.unescape(raw_query).strip()[:500]
        log = logger.bind(agent="orchestrator", session_id=session_id)
        log.info("agent_start", query=query[:80])

        # Fast-path keyword check (re-evaluated if query changes via interrupt answer)
        self_drive_kw = any(kw in query.lower() for kw in _SELF_DRIVE_KEYWORDS)

        parsed: _ParsedQuery | None = None
        rounds_taken = 0

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
                answers: dict[str, str] = interrupt(
                    {"prompts": [p.model_dump() for p in prompts], "round": _round}
                )
                new_q = html.unescape(answers.get("query", "")).strip()[:500]
                if new_q:
                    query = new_q
                    self_drive_kw = any(kw in query.lower() for kw in _SELF_DRIVE_KEYWORDS)
                parsed = None  # force re-parse with cleaned query
                rounds_taken += 1
                continue

            # ── LLM parse (only on first pass or after query change) ─────────
            if parsed is None:
                today = date.today().isoformat()
                chain = self._llm.with_structured_output(_ParsedQuery)  # type: ignore[union-attr]
                try:
                    parsed = chain.invoke(
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
                    answers = interrupt(
                        {"prompts": [p.model_dump() for p in prompts], "round": _round}
                    )
                    new_q = html.unescape(answers.get("query", "")).strip()[:500]
                    if new_q:
                        query = new_q
                        self_drive_kw = any(kw in query.lower() for kw in _SELF_DRIVE_KEYWORDS)
                    rounds_taken += 1
                    continue

            # ── UserProfile pre-fill (idempotent) ────────────────────────────
            _apply_profile_prefill(parsed, user_profile)

            # ── Compute missing / low-confidence fields ──────────────────────
            missing = _compute_missing(parsed)
            if not missing:
                break  # all required fields satisfied

            # ── Interrupt: pause graph and await client answers ──────────────
            log.info(
                "clarification_required",
                fields=[f for f, _ in missing],
                round=_round,
            )
            prompts = [_build_clarification_prompt(f, ev) for f, ev in missing]
            answers = interrupt({"prompts": [p.model_dump() for p in prompts], "round": _round})
            _apply_answers(parsed, answers)
            rounds_taken += 1

        else:
            # Max rounds exhausted — proceed with best-effort defaults
            log.warning(
                "max_clarification_rounds_exhausted",
                rounds=settings.max_clarification_rounds,
            )
            if parsed is not None:
                _apply_defaults(parsed)

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
            "source": parsed.source_city.confidence,
            "travelers": parsed.travelers.confidence,
            "dates": parsed.dates_confidence,
        }

        # ── Build TripDates ───────────────────────────────────────────────────
        trip_dates: TripDates | None = None
        if parsed.departure_date:
            try:
                dep = date.fromisoformat(parsed.departure_date)
                ret = (
                    date.fromisoformat(parsed.return_date)
                    if parsed.return_date
                    else dep + timedelta(days=max(1, parsed.trip_days - 1))
                )
                trip_dates = TripDates(departure=dep, return_date=ret)
            except ValueError:
                dep = date.today() + timedelta(days=30)
                trip_dates = TripDates(departure=dep, return_date=dep + timedelta(days=2))
        else:
            dep = date.today() + timedelta(days=30)
            trip_dates = TripDates(
                departure=dep,
                return_date=dep + timedelta(days=max(1, parsed.trip_days - 1)),
            )

        tier = (
            BudgetTier(parsed.budget_tier)
            if parsed.budget_tier in BudgetTier.__members__.values()
            else BudgetTier.mid
        )
        budget = BudgetPreference(tier=tier)

        try:
            travelers = max(1, int(parsed.travelers.value or 1))
        except (ValueError, TypeError):
            travelers = 1

        destination = (parsed.destination.value or "").strip()
        source = (parsed.source_city.value or "").strip()

        # International heuristic: override LLM if both cities are known Indian cities
        src_domestic = source.lower() in _INDIAN_CITIES
        dst_domestic = destination.lower() in _INDIAN_CITIES
        is_intl = parsed.is_international
        if src_domestic and dst_domestic:
            is_intl = False

        self_drive = parsed.self_drive_intent or self_drive_kw

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

_DAYS_PATTERN = re.compile(r"\b(\d+)\s*days?\b", re.IGNORECASE)


def quick_extract_days(query: str) -> int | None:
    """Return number of trip days from a query string if mentioned."""
    m = _DAYS_PATTERN.search(query)
    return int(m.group(1)) if m else None
