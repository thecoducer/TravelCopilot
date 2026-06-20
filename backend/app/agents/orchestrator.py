"""OrchestratorAgent — Layer 0: query parsing + intent detection + clarification gate.

Responsibilities:
  1. Parse the free-text user query into structured trip parameters, each with
     a ``parse_confidence`` score (0–1).
  2. Detect ``is_international`` (compares source vs destination country).
  3. Detect ``self_drive_intent`` from keywords.
  4. Load ``UserProfile`` from DB by session_id (best-effort, non-blocking).
  5. **Clarification gate (F)**: if any required field is missing or has
     confidence below ``settings.parse_confidence_threshold``, set
     ``needs_clarification=True`` and populate ``clarification_prompts[]``.
     Downstream planning nodes are skipped via ``conditional_edges``.
"""

from __future__ import annotations

import html
import re
from datetime import date, timedelta
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.config import settings
from app.llm import get_llm
from app.models.user_profile import BudgetPreference, BudgetTier, ClarificationPrompt, TripDates

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

# Field → clarification question template
_CLARIFICATION_QUESTIONS: dict[str, str] = {
    "destination": "Where would you like to travel? Please name the city or region.",
    "dates": "What dates are you planning to travel? (e.g. 'July 15–20' or '5 days in October')",
    "travelers": "How many people are travelling? (including yourself)",
    "source": "What city will you be departing from?",
}


# ── Structured LLM output ────────────────────────────────────────────────────


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


class OrchestratorAgent:
    """Layer 0 — Parse query into TripState fields with clarification gate."""

    def __init__(self, llm: object | None = None) -> None:
        self._llm = llm or get_llm("orchestrator")

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        raw_query: str = state.get("query", "")
        session_id: str = state.get("session_id", "")

        # ── Security: sanitize input ───────────────────────────────────────
        query = html.unescape(raw_query).strip()[:500]
        if _INJECTION_PATTERNS.search(query):
            logger.warning("prompt_injection_detected", session_id=session_id)
            return {
                "needs_clarification": True,
                "clarification_prompts": [
                    ClarificationPrompt(
                        field="query",
                        question=(
                            "Your request contains disallowed patterns."
                            " Please describe your trip normally."
                        ),
                        reason="Prompt injection detected",
                    )
                ],
                "parse_confidence": {},
            }

        log = logger.bind(agent="orchestrator", session_id=session_id)
        log.info("agent_start", query=query[:80])

        # ── Fast-path keyword checks ───────────────────────────────────────
        query_lower = query.lower()
        self_drive_kw = any(kw in query_lower for kw in _SELF_DRIVE_KEYWORDS)

        # ── LLM parse ────────────────────────────────────────────────────
        today = date.today().isoformat()
        chain = self._llm.with_structured_output(_ParsedQuery)  # type: ignore[union-attr]
        try:
            parsed: _ParsedQuery = chain.invoke(
                [
                    SystemMessage(content=_SYSTEM_PROMPT.format(today=today)),
                    HumanMessage(content=f"User query: {query}"),
                ]
            )
        except Exception as exc:
            log.error("llm_parse_failed", error=str(exc))
            return {
                "needs_clarification": True,
                "clarification_prompts": [
                    ClarificationPrompt(
                        field="query",
                        question="Could you describe your trip in a bit more detail?",
                        reason="Parsing failed",
                    )
                ],
                "parse_confidence": {},
                "error": str(exc),
            }

        # ── Build parse_confidence map ────────────────────────────────────
        parse_confidence: dict[str, float] = {
            "destination": parsed.destination.confidence,
            "source": parsed.source_city.confidence,
            "travelers": parsed.travelers.confidence,
            "dates": parsed.dates_confidence,
        }

        # ── Clarification gate (F) ────────────────────────────────────────
        required_fields_cfg = settings.clarification_fields  # from settings
        threshold = settings.parse_confidence_threshold
        clarification_prompts: list[ClarificationPrompt] = []

        for field in required_fields_cfg:
            conf = parse_confidence.get(field, 0.0)
            field_val = {
                "destination": parsed.destination.value,
                "source": parsed.source_city.value,
                "travelers": parsed.travelers.value,
                "dates": parsed.departure_date,
            }.get(field)

            is_missing = field_val is None or str(field_val).lower() in ("", "unknown", "none")
            is_low_confidence = conf < threshold

            if is_missing or is_low_confidence:
                question = _CLARIFICATION_QUESTIONS.get(field, f"Could you clarify: {field}?")
                clarification_prompts.append(
                    ClarificationPrompt(
                        field=field,
                        question=question,
                        reason=(
                            f"Missing or low confidence ({conf:.2f}) for required field '{field}'"
                        ),
                    )
                )

        if clarification_prompts:
            log.info(
                "clarification_required",
                fields=[p.field for p in clarification_prompts],
            )
            return {
                "needs_clarification": True,
                "clarification_prompts": clarification_prompts,
                "parse_confidence": parse_confidence,
            }

        # ── All required fields present — build trip parameters ──────────
        # Build TripDates
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

        travelers = max(1, int(parsed.travelers.value or 1))
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
            "needs_clarification": False,
            "clarification_prompts": [],
            "parse_confidence": parse_confidence,
        }

        # Bootstrap user profile from interests
        if parsed.interests:
            from app.models.user_profile import UserProfile

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
        )
        return updates


# ── Helper ───────────────────────────────────────────────────────────────────

_DAYS_PATTERN = re.compile(r"\b(\d+)\s*days?\b", re.IGNORECASE)


def quick_extract_days(query: str) -> int | None:
    """Return number of trip days from a query string if mentioned."""
    m = _DAYS_PATTERN.search(query)
    return int(m.group(1)) if m else None
