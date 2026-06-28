# Multi-Agent AI Trip Planner — Full System Design Plan

> Version 6 — Updated 2026-06-15
> Status: Approved, ready for implementation
> Dev Roadmap: See `dev-roadmap.md`

---

## TL;DR

A production-grade LangGraph multi-agent trip planning system built for real users to plan end-to-end domestic and international trips. Chat-first UI. LLM-agnostic via LiteLLM. Multi-modal transport via Google Routes API + SerpAPI + LLM hub reasoning. Agents are organised into 6 clear execution layers with explicit dependencies. Full observability: OpenTelemetry → Cloud Trace + local Jaeger, Langfuse (open-source, self-hostable) for LLM tracing and evals, Prometheus → Cloud Monitoring. Deploys to Google Cloud Run with Cloud SQL + Memorystore via Terraform.

**Development strategy**: Mock-first → Real APIs → Frontend last. All external APIs (SerpAPI, Tavily, Google Maps) are mocked via fixture JSON during development. A `ToolFactory` controlled by `MOCK_EXTERNAL_APIS` env flag swaps mock ↔ real tools with zero agent code changes. Backend is Postman-testable before any frontend work begins.

---

## Google Agentic AI Best Practices Applied

Based on Google's Agent whitepaper and ReAct framework:

1. **ReAct loop per agent**: Every agent follows Reason → Act → Observe → Reason. Each tool call is a discrete Act; results are fed back as Observe before the next reasoning step. Never fire-and-forget.
2. **Memory tiers in TripState**: Short-term (current graph state), episodic (session history in Redis), long-term (UserProfile in DB). Agents read from all three tiers.
3. **Tool abstraction layer**: All external calls go through a typed `BaseTool` protocol. Tools are injected into agents — never imported directly. Agents are fully testable with mock tools.
4. **Self-refining**: `ItineraryCompilerAgent` runs a self-critique pass after compiling — checks transit times, schedule gaps, pace — and revises before finalising.
5. **Guardrails**: Input sanitization at OrchestratorAgent (no prompt injection), Pydantic validation at every agent boundary, LiteLLM `BudgetManager` per-trip spend cap.
6. **Single responsibility**: Search agents = pure tool calls (no LLM). Analyst agents = pure LLM reasoning (no API calls). One job per agent.
7. **Graceful degradation**: Every agent has a fallback chain. E.g. flight search: SerpAPI → Tavily web search → LLM general knowledge.
8. **Conditional activation**: VisaAgent only fires for international trips. SelfDriveSearchAgent only fires when self-drive intent detected. Reduces cost and latency.

---

## Architecture Overview

```mermaid
graph TD
    %% ── Styling ──────────────────────────────────────────────────
    classDef control fill:#1e1e2e,stroke:#cba6f7,stroke-width:2px,color:#cdd6f4
    classDef gate fill:#313244,stroke:#f38ba8,stroke-width:2px,color:#f38ba8,stroke-dasharray:5
    classDef layer1 fill:#1e3a5f,stroke:#89b4fa,stroke-width:2px,color:#cdd6f4
    classDef layer2 fill:#1a4731,stroke:#a6e3a1,stroke-width:2px,color:#cdd6f4
    classDef layer3 fill:#4a3728,stroke:#fab387,stroke-width:2px,color:#cdd6f4
    classDef layer4 fill:#3b2d4a,stroke:#cba6f7,stroke-width:2px,color:#cdd6f4
    classDef layer5 fill:#4a2d3b,stroke:#f5c2e7,stroke-width:2px,color:#cdd6f4
    classDef terminal fill:#313244,stroke:#a6e3a1,stroke-width:3px,color:#a6e3a1

    %% ── Entry ────────────────────────────────────────────────────
    START((START)):::control --> orchestrator

    %% ── Layer 0: Routing & Orchestration ─────────────────────────
    orchestrator["🎯 OrchestratorAgent\n─────────────────\nparse query → structured params\ndetect is_international\ndetect self_drive_intent\nclarification gate check"]:::control

    %% ── Conditional Routing ──────────────────────────────────────
    orchestrator -->|"needs_clarification\n== true"| clarification
    orchestrator -->|"needs_clarification\n== false"| ready_to_plan

    clarification["⚠️ Clarification Node\n─────────────────\nterminal · emits SSE\nclarification_prompts[]"]:::gate
    clarification --> END_NODE((END)):::terminal

    ready_to_plan["✅ ready_to_plan\n─────────────────\npass-through fan-out"]:::control

    %% ── Layer 1: Destination Intelligence (parallel) ─────────────
    ready_to_plan --> destination_context
    ready_to_plan --> scam_safety
    ready_to_plan --> visa

    destination_context["🌍 DestinationContextAgent\n─────────────────\nLLM · Tavily search\nseasonality · crowds\ncosts · weather · risks"]:::layer1

    scam_safety["🛡️ ScamSafetyAgent\n─────────────────\nLLM · Tavily search\nscams · safety tips\nemergency contacts"]:::layer1

    visa["🛂 VisaAgent\n─────────────────\nLLM · Tavily + Places\nintl trips only\nvisa type · process · fees"]:::layer1

    %% ── Layer 2: Supply Search (parallel) ────────────────────────
    ready_to_plan --> transport_search
    ready_to_plan --> stay_search
    ready_to_plan --> local_experiences

    transport_search["✈️ TransportSearchAgent\n─────────────────\ntools only · no LLM\nflights · trains · buses\nSerpAPI + Google Routes"]:::layer2

    stay_search["🏨 StaySearchAgent\n─────────────────\ntools only · no LLM\nhotels · stays\nSerpAPI Google Hotels"]:::layer2

    local_experiences["🎭 LocalExperiencesAgent\n─────────────────\ntools only · no LLM\nattractions · activities\nGoogle Places + Tavily"]:::layer2

    %% ── Layer 3: Analysis ────────────────────────────────────────
    transport_search --> transport_optimizer
    transport_search --> self_drive_search
    stay_search --> stay_analyst

    transport_optimizer["🔀 TransportOptimizerAgent\n─────────────────\nLLM reasoning\nbest route selection\nbudget-filtered alternatives"]:::layer3

    stay_analyst["📊 StayAnalystAgent\n─────────────────\nLLM reasoning\nranked shortlist · rationale\npersonalization scoring"]:::layer3

    self_drive_search["🚗 SelfDriveSearchAgent\n─────────────────\nconditional · LLM\nrentals · fuel estimate\nonly if self_drive_intent"]:::layer3

    %% ── Layer 1 + Layer 3 → BudgetPlanner (barrier join) ─────────
    destination_context --> budget_planner
    scam_safety --> budget_planner
    visa --> budget_planner
    transport_optimizer --> budget_planner
    stay_analyst --> budget_planner
    self_drive_search --> budget_planner

    %% ── Layer 3 + Layer 2 → Reviews ──────────────────────────────
    stay_analyst --> reviews
    local_experiences --> reviews

    %% ── Layer 2 → FoodDiscovery ──────────────────────────────────
    local_experiences --> food_discovery

    %% ── Layer 4: Enrichment ──────────────────────────────────────
    budget_planner["💰 BudgetPlannerAgent\n─────────────────\nLLM · barrier join\naggregate all costs\nbudget verdict + tips"]:::layer4

    reviews["⭐ ReviewsAgent\n─────────────────\nLLM · Places API\nreviews + photos\nfor stays + experiences"]:::layer4

    food_discovery["🍜 FoodDiscoveryAgent\n─────────────────\ntools only · no LLM\nrestaurants · cafes\nstreet food per day"]:::layer4

    %% ── Layer 5: Synthesis ───────────────────────────────────────
    budget_planner --> itinerary_compiler
    reviews --> itinerary_compiler
    food_discovery --> itinerary_compiler

    itinerary_compiler["📋 ItineraryCompilerAgent\n─────────────────\nLLM · geo-cluster\ncompile · self-critique\ndeterministic gate · finalise"]:::layer5

    itinerary_compiler --> END_NODE
```

---

## Agent Layer Architecture

```
LAYER 0 — ROUTING & ORCHESTRATION
  └── OrchestratorAgent
        Dual role: (1) parse user query → structured params,
        (2) route via LangGraph conditional_edges to fire agent groups.
        This IS the LangGraph supervisor/router node.

LAYER 1 — DESTINATION INTELLIGENCE  (all parallel, no supply data needed)
  ├── DestinationContextAgent  seasonality · crowd · practical costs · local constraints
  ├── ScamSafetyAgent          safety · scams · advisories
  └── VisaAgent                international trips only

LAYER 2 — SUPPLY SEARCH  (all parallel, pure tool calls — no LLM)
  ├── TransportSearchAgent     flights + trains + buses (SerpAPI + Google Routes API)
  ├── StaySearchAgent          hotels + stays (SerpAPI Google Hotels)
  └── LocalExperiencesAgent    attractions + activities + tours (Google Places + Tavily)

LAYER 3 — ANALYSIS  (parallel, LLM-heavy, each waits for its Layer 2 parent)
  ├── TransportOptimizerAgent  (after TransportSearch) — picks best route, explains reasoning
  ├── StayAnalystAgent         (after StaySearch) — picks best stay, explains reasoning
  └── SelfDriveSearchAgent     (conditional, after TransportSearch) — rentals + fuel estimate

LAYER 4 — ENRICHMENT  (parallel, after Layer 3 + LocalExperiences complete)
  ├── ReviewsAgent             Google Places reviews + photos for stays + experiences
  ├── FoodDiscoveryAgent       meal-time food search per day cluster: restaurants, cafes, street food
  └── BudgetPlannerAgent       aggregate all costs → budget verdict + savings tips

LAYER 5 — SYNTHESIS
  └── ItineraryCompilerAgent   geo-cluster → compile → self-critique → finalise
```

---

## Shared TripState (`graph/state.py`)

```python
class TripState(TypedDict):
    # ── Input ──────────────────────────────────────────────────────
    query:             str
    session_id:        str
    source:            str
    destination:       str
    dates:             TripDates
    budget:            BudgetPreference
    travelers:         int
    user_profile:      UserProfile | None
    is_international:  bool          # set by OrchestratorAgent
    self_drive_intent: bool          # set by OrchestratorAgent

    # ── Clarification gate (set by OrchestratorAgent) ──────────────
    needs_clarification:  bool                    # True when critical fields missing/low-confidence
    clarification_prompts: list[ClarificationPrompt]  # questions to ask the user
    parse_confidence:     dict[str, float]        # per-field confidence (0–1) from the parse

    # ── Layer 1: Intelligence ──────────────────────────────────────
    destination_context_report: DestinationContextReport | None
    scam_safety_report: ScamSafetyReport | None
    visa_report:       VisaReport | None

    # ── Layer 2: Supply Search ─────────────────────────────────────
    transport_hubs:        list[str]           # from hub-ID LLM call
    transport_legs_raw:    dict[str, list]     # keyed by "KOL→DEL"
    stays_raw:             list[StayOption]
    experiences_raw:       list[Experience]

    # ── Layer 3: Analysis ──────────────────────────────────────────
    transport_recommendation: TransportRecommendation | None
    stays_pick:            StayOption | None
    stays_rationale:       str
    self_drive_report:     SelfDriveReport | None

    # ── Layer 4: Enrichment ────────────────────────────────────────
    reviews_summary:        dict[str, ReviewSummary]  # keyed by place name
    food_recommendations: dict[str, list[FoodVenue]]  # keyed by day ISO date
    budget_report:          BudgetReport | None

    # ── Output ─────────────────────────────────────────────────────
    itinerary:    Itinerary | None
    token_usage:  dict[str, AgentTokenUsage]
    messages:     list[BaseMessage]
    next_agent:   str
    error:        str | None
```

---

## Phase 1 — Core Infrastructure

### 1. Project Layout

```
trip-planner/
├── backend/
│   ├── app/
│   │   ├── agents/          # one file per agent
│   │   ├── tools/
│   │   │   ├── base.py      # BaseTool protocol
│   │   │   ├── factory.py   # ToolFactory — reads MOCK_EXTERNAL_APIS, returns mock or real
│   │   │   ├── mock/        # mock implementations — read from fixtures, no network calls
│   │   │   │   ├── serpapi_tools.py
│   │   │   │   ├── transit_tools.py
│   │   │   │   ├── places_tools.py
│   │   │   │   ├── tavily_tools.py
│   │   │   │   ├── visa_tools.py
│   │   │   │   ├── rental_tools.py
│   │   │   │   ├── geo_tools.py
│   │   │   │   ├── fx_tools.py
│   │   │   │   └── hub_tools.py
│   │   │   └── real/        # real API implementations (stubs → filled in Phase 5)
│   │   │       ├── serpapi_tools.py
│   │   │       ├── transit_tools.py
│   │   │       ├── places_tools.py
│   │   │       ├── tavily_tools.py
│   │   │       ├── visa_tools.py
│   │   │       ├── rental_tools.py
│   │   │       ├── geo_tools.py   # ClusterByProximityTool implemented fully (pure math)
│   │   │       ├── fx_tools.py    # CurrencyConvertTool — live FX rates, cached
│   │   │       └── hub_tools.py
│   │   ├── graph/           # state.py, graph.py, router.py
│   │   ├── models/          # Pydantic models only — zero business logic
│   │   ├── routers/         # FastAPI route handlers only
│   │   ├── services/        # pdf_service, cache_service
│   │   ├── observability/   # otel.py, langfuse.py, metrics.py
│   │   ├── config.py        # all config from env via pydantic-settings
│   │   └── main.py
│   ├── migrations/
│   │   └── 001_initial.sql  # full schema DDL — run via `make migrate`
│   ├── evals/
│   │   ├── datasets/        # domestic_trips.jsonl, international_trips.jsonl, edge_cases.jsonl
│   │   ├── golden/          # human-verified ground truth for REAL-API runs (visa, transit existence, opening hours)
│   │   ├── evaluators/      # 7 pure-Python evaluator scripts (mock-mode) + golden_accuracy (real-mode)
│   │   ├── baselines.json   # baseline scores for regression detection (mock-mode)
│   │   └── run_evals.py     # CI eval runner (--mode mock | golden)
│   ├── tests/
│   │   ├── fixtures/        # realistic JSON fixture files per destination/scenario
│   │   ├── unit/            # per-agent tests with mock tools injected
│   │   └── integration/     # full graph tests (MOCK_EXTERNAL_APIS=true)
│   ├── postman/
│   │   ├── TripPlanner.postman_collection.json
│   │   ├── local.postman_environment.json
│   │   └── README.md
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── app/             # Next.js App Router pages
│   │   ├── components/
│   │   ├── lib/             # sse.ts, api.ts, mapUtils.ts
│   │   └── types/           # TypeScript types mirroring backend Pydantic models
│   └── Dockerfile
├── infra/                   # Terraform for GCP
│   ├── cloud_run.tf
│   ├── cloud_sql.tf
│   ├── memorystore.tf
│   ├── artifact_registry.tf
│   └── variables.tf
├── docker-compose.yml       # local dev: postgres + redis + langfuse + jaeger + backend
├── docker-compose.override.yml  # local overrides (e.g. skip frontend)
├── Makefile                 # targets: dev, test, lint, evals, evals-golden, migrate
└── .env.example
```

### 2. Config (`config.py`) — everything from env, zero hardcoding

```python
class Settings(BaseSettings):
    llm_provider:            str   = "openai"
    llm_model:               str   = "gpt-4o"
    llm_budget_per_trip_usd: float = 0.50

    # When True: all tools use fixture JSON — no network calls, no API quota used.
    # Set False only in Phase 5+ when real API keys are available.
    mock_external_apis: bool = True

    serpapi_key:        str = ""   # required when mock_external_apis=False
    google_maps_key:    str = ""   # Routes API + Places API + Maps JS API + Static Maps + Distance Matrix
    tavily_key:         str = ""
    fx_api_key:         str = ""   # currency exchange-rate provider (e.g. exchangerate.host / OXR)

    # Critical fields that trigger the clarification gate when missing/low-confidence.
    clarification_required_fields: list[str] = ["destination", "dates", "travelers"]
    parse_confidence_threshold:    float     = 0.6

    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host:       str = "http://localhost:3000"  # self-hosted; swap to https://cloud.langfuse.com for cloud
    otel_endpoint:       str = ""  # empty = local Jaeger; Cloud Trace OTLP in prod

    database_url: str
    redis_url:    str
    gcp_project_id: str = ""
    gcp_region:     str = "asia-south1"

    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()
```

### 3. LiteLLM factory + UsageLogger

```python
class UsageLogger(litellm.CustomLogger):
    def log_success_event(self, kwargs, response_obj, start_time, end_time):
        agent_name = kwargs["metadata"].get("agent_name", "unknown")
        session_id = kwargs["metadata"].get("session_id", "")
        cost = litellm.completion_cost(response_obj)
        # write to Redis: f"usage:{session_id}:{agent_name}"

litellm.callbacks = [UsageLogger()]

def get_llm(agent_name: str, session_id: str) -> BaseChatModel:
    return LiteLLM(
        model=f"{settings.llm_provider}/{settings.llm_model}",
        metadata={"agent_name": agent_name, "session_id": session_id}
    )
```

### 4. BaseTool protocol + ToolFactory

**`tools/base.py`** — protocol all tools must implement:
```python
class BaseTool(Protocol):
    name:        str
    description: str
    async def run(self, **kwargs) -> dict: ...
```

**`tools/factory.py`** — reads `settings.mock_external_apis`, returns the correct implementation:
```python
class ToolFactory:
    def __init__(self, mock: bool = settings.mock_external_apis):
        self._mock = mock

    def get(self, tool_name: str) -> BaseTool:
        module = "mock" if self._mock else "real"
        # dynamically import from tools.mock.* or tools.real.*
        ...
```

All agents receive `list[BaseTool]` via constructor injection. In unit tests, `ToolFactory(mock=True)` is passed — zero network calls, zero patching needed. In Phase 5, flipping `MOCK_EXTERNAL_APIS=false` in `.env` and providing real API keys is the only change required.

**Fixture files** (`tests/fixtures/`) contain realistic hardcoded JSON per destination and scenario (flights, hotels, places, food venues, scams, visa, rentals). Mock tools read from these files based on input params.

### 5. LangGraph StateGraph wiring (`graph/graph.py`)

All 14 agent nodes wired with parallel edges per layer. `OrchestratorAgent` uses `conditional_edges` to route based on `state["next_agent"]`. Conditional nodes (`VisaAgent`, `SelfDriveSearchAgent`) skipped via routing when flags are false.

**Clarification gate**: after the OrchestratorAgent parse, a `conditional_edge` checks `state["needs_clarification"]`. If `True`, the graph routes to a terminal `clarification` node that emits a `needs_clarification` SSE event with `clarification_prompts[]` and halts — no downstream agents fire, no API quota spent. The user answers, the frontend re-POSTs `/api/trip/plan` with the merged query, and the graph runs to completion. If `False`, routing proceeds to Layer 1 + Layer 2 as normal.

---

## Phase 2 — Agent Implementation

> **Rule**: Layer 2 agents = pure tool calls, zero LLM. Layer 3+ analysts = pure LLM, zero direct API calls.

---

### LAYER 0 — OrchestratorAgent (`agents/orchestrator.py`)

**This is both the orchestrator AND the LangGraph router/supervisor.**

- **On first call**: LLM parses free-text query into structured trip params (source, destination, dates, budget, travelers), and returns a `parse_confidence` score (0–1) per field
- Sets `is_international` by comparing origin vs destination country
- Detects `self_drive_intent` from keywords: "rent a bike", "scooter", "self-drive", "motorcycle", "hire a car", or destination type (Goa, hill stations, road trip)
- Loads `UserProfile` from DB by session UUID if exists
- **Clarification gate (F)**: before any downstream agent fires, checks every field in `settings.clarification_required_fields` (default: `destination`, `dates`, `travelers`). If any is missing, ambiguous, or has `parse_confidence` below `settings.parse_confidence_threshold` (default 0.6), it sets `needs_clarification = True` and populates `clarification_prompts[]` — one concise question per missing/uncertain field (e.g. *"What dates are you travelling? I need them to check weather, prices, and availability."*). The graph then routes to the `clarification` node and halts. **The system never silently guesses critical inputs.** Optional fields (budget, interests) fall back to profile defaults and do **not** trigger the gate.
- **On every subsequent call**: uses `conditional_edges` to route to the correct next layer — does NOT re-call LLM for routing, only for initial parse
- Writes `next_agent` to state

---

### LAYER 1 — Destination Intelligence

**DestinationContextAgent** (`agents/destination_context_agent.py`)
- Tavily searches: crowds `"{destination} crowded {month} {year}"`, peak season `"is {destination} peak season {month}"`, festivals `"{destination} events {dates}"`, costs `"average daily cost {destination} 2026"`, hidden fees `"tourist tax hidden fees {destination}"`
- LLM synthesizes `DestinationContextReport`:
  - `is_peak_season`: bool
  - `season_label`: e.g. "Peak season", "Shoulder season", "Off season"
  - `season_reason`: e.g. "Cherry blossom season — expect 2–3h queues at major attractions"
  - `crowd_level`: Low / Moderate / High / Extreme
  - `crowd_notes`: specific crowd hotspots and busy times of day
  - `real_daily_cost`: estimated per-person per-day spend in destination currency
  - `currency_code`: ISO 4217 currency of the destination country (e.g. `"JPY"`, `"INR"`, `"BDT"`, `"EUR"`)
  - `cost_warnings[]`: e.g. "Venice day-tripper tax €5/person", "Hotel tax not included in listed prices"
  - `seasonal_weather_summary`: brief seasonal expectation for the travel window
  - `seasonal_risks[]`: e.g. "Typhoon season may affect ferries", "Mountain roads can close after early snowfall"
- No score, no verdict, no recommendation — the decision to travel is entirely the user’s

**ScamSafetyAgent** (`agents/scam_safety_agent.py`)
- Tavily: `"tourist scams {destination} 2026"`, `"safety tips {destination}"`, fetches travel.state.gov + gov.uk/foreign-travel-advice
- LLM synthesizes `ScamSafetyReport`: `advisory_level`, `top_scams[]` (name, description, how-to-avoid), `safe_areas[]`, `emergency_contacts` (police, ambulance, tourist helpline)

**VisaAgent** (`agents/visa_agent.py`) ← *international trips only*
- Tools:
  1. `tavily_search("visa requirements {passport_country} nationals {destination_country} 2026")` — official requirements, eligibility, type (tourist / e-visa / on arrival / visa-free)
  2. `tavily_search("how to apply {destination_country} visa from {passport_country} step by step")` — application procedure
  3. `tavily_search("visa processing time {destination_country} {passport_country} 2026")` — typical turnaround
  4. `tavily_search("visa application centre {destination_country} in {home_city}")` — discovers whichever company handles that corridor (VFS Global, BLS International, TLScontact, iData, ACSIS, or official consulate direct)
  5. `google_place_search("{destination_country} embassy", home_city)` → nearest embassy/consulate with address, phone, hours
  6. `google_place_search("{visa_centre_company} {destination_country}", home_city)` → nearest application centre office, run after step 4 identifies the company
- LLM synthesizes `VisaReport`:
  - `visa_required`: bool + type (tourist / e-visa / on arrival / visa-free)
  - `application_process[]`: numbered step-by-step guide
  - `documents_required[]`: checklist
  - `processing_timeline`: e.g. "5–15 business days; apply 6 weeks before travel"
  - `fees`: official visa fee + service charge if third-party centre used
  - `dos_and_donts[]`
  - `nearest_embassy`: name, address, phone, opening_hours, appointment_url
  - `application_centre`: name of the company (e.g. VFS Global, BLS International, TLScontact — whichever handles this corridor), address, phone, opening_hours, booking_url
  - `apply_online_url`: direct link to official visa portal or third-party booking page
  - `validity_notes`: e.g. "180-day multiple entry, max 90 days per stay"
  - `sources[]`: **(G)** every URL the LLM grounded its answer on (official government / embassy / application-centre pages), each with `title`, `url`, and `published_or_fetched_date`. Prefer official `.gov` / consulate domains; web-search results that are not from an official or recognised application-centre domain are excluded from `sources[]`.
  - `last_verified_at`: datetime the visa data was fetched/synthesised — surfaced in the UI as "Checked on {date}"
  - `confidence`: `high` / `medium` / `low` — `low` when no official-domain source could be grounded
  - `disclaimer`: fixed text — *"Visa rules change frequently and depend on your exact nationality and circumstances. This is guidance only — always confirm with the official consulate or embassy before booking travel."*
- **Visa is advisory, never authoritative.** The agent never asserts a requirement without at least one source in `sources[]`; if no official-domain source is found, `confidence="low"` and the UI shows a prominent "Could not verify against an official source — confirm directly" warning.

---

### LAYER 2 — Supply Search (pure tool calls, no LLM)

**TransportSearchAgent** (`agents/transport_search_agent.py`)

*Step A — Hub identification (one cheap LLM call, stored in `transport_hubs`):*
LLM enumerates plausible route combinations using geographic knowledge:
```
"Kolkata → Leh" → [("KOL","LEH","flight"), ("KOL","DEL","train"),("DEL","LEH","flight"), ("KOL","DEL","flight"),("DEL","LEH","flight")]
```

*Step B — Parallel tool calls per leg:*
- **Flights**: SerpAPI `engine: "google_flights"` — real-time prices per flight leg
- **Trains + Buses**: Google Routes API `mode=transit&transit_mode=train|bus` — returns `LONG_DISTANCE_TRAIN`, `BUS`, `RAIL` with operator, departure/arrival, fare. Covers IRCTC (India), European rail, intercity buses globally. $200/month free credit.
- **Bus fallback**: Tavily `"bus from {origin} to {dest} schedule fare"` for smaller operators
- Writes `state["transport_legs_raw"]` keyed by leg string e.g. `"KOL→DEL"`

**StaySearchAgent** (`agents/stay_search_agent.py`)
- Tool: SerpAPI `engine: "google_hotels"` filtered by `user_profile.hotel_style` and `budget_tier`
- Returns top 10 options with price, rating, location, amenities
- Writes `state["stays_raw"]`

**LocalExperiencesAgent** (`agents/local_experiences_agent.py`) ← *new*
- Tools:
  - `google_places_search(destination, types=["tourist_attraction","museum","art_gallery","park","amusement_park","zoo","night_club","spa"])` filtered by `user_profile.interests`
  - Tavily: `"top experiences {destination}"`, `"hidden gems {destination} locals recommend"`, `"best things to do {destination} 2026"`
- Returns structured `Experience[]`: name, type, description, duration_hours, price_range, lat/lng, photos[], google_maps_url, opening_hours, best_time_to_visit, `source` ("google_places" | "tavily")
- **Tavily grounding check (D)**: Any experience sourced from Tavily (not Google Places) is verified via `google_place_search(name, destination)` before being added. If no Google Places match found, the experience is dropped silently. This eliminates hallucinated venues entering the itinerary.
- Writes `state["experiences_raw"]`
- *This feeds both ReviewsAgent (for enrichment) and ItineraryCompilerAgent (for day planning)*

---

### LAYER 3 — Analysis (parallel, LLM-heavy)

**TransportOptimizerAgent** (`agents/transport_optimizer_agent.py`)
- Receives `transport_legs_raw` + `user_profile`
- LLM reasons: total cost per combination, total door-to-door time, comfort vs cost per `budget_tier`, night train flag (saves one night's accommodation)
- **Strict budget filtering**: Eliminates any route combination that is disproportionately expensive vs the user's `budget_tier`. A budget traveller will never see business-class flight options; a mid-tier traveller will not see premium first-class options as the primary recommendation.
- Example (India domestic route): *"KOL→LEH direct: ₹8,500, 3.5h. KOL→DEL Rajdhani + DEL→LEH: ₹6,050, 21h. Direct saves 17.5h for ₹2,450 extra — strongly recommended for ≤5 day trips."* (Currency in the example is INR because both source and destination are in India. The actual currency is always resolved from source/destination countries.)
- Writes `TransportRecommendation` (top-ranked route) with:
  - `recommended_legs[]`: mode, operator, duration, cost, booking_url, `price_cached_at` (datetime), `price_disclaimer` (e.g. *"Price captured 3h ago — verify before booking"*) per leg
  - `total_cost`, `total_duration`, `currency_code`
  - `rationale` + `personalization_reason` (1 sentence tied to user profile, e.g. *"Chosen for your budget-tier preference and minimal transit time"*)
  - `non_obvious_insight` (only when cheaper combo exists)
  - `route_waypoints[]`
- Also writes `transport_alternatives[]` — top 2 alternative routes, budget-filtered, each with the same structure. Shown in `TransportOptionsPanel` so user can compare and switch.

**StayAnalystAgent** (`agents/stay_analyst_agent.py`)
- LLM ranks `stays_raw` by price/rating/location/amenities weighted by user profile
- **Strict budget filtering before ranking**: Removes any option whose `price_per_night` is incompatible with `user_profile.budget_tier` before the LLM ever sees them. Budget tier thresholds are configurable (e.g. budget ≤ destination avg × 0.8, mid ≤ avg × 1.5, luxury = no cap). A user who says "budget trip with standard hotels" will never see a 5-star luxury property in the options.
- Selects top 3–5 options from the filtered list
- Writes `stays_shortlist[]` — all curated options with `personalization_reason` per option (e.g. *"Best value in your budget with walkable access to Day 2’s activity cluster"*) and `price_disclaimer` (datetime of price capture)
- Writes `stays_pick` — the single LLM-recommended default (first item in shortlist, flagged as recommended)

**SelfDriveSearchAgent** (`agents/self_drive_search_agent.py`) ← *conditional*
- Triggered when `self_drive_intent == True`
- Tools: `google_places_search(dest, type="car_rental")`, Tavily for community-recommended local operators, Google Distance Matrix API for total round-trip km, Tavily for live fuel prices
- Fuel formula: `total_km ÷ avg_mileage × fuel_price_per_litre` (defaults: scooter 40km/L, motorcycle 30km/L, hatchback 15km/L, SUV 12km/L)
- Writes `SelfDriveReport`: `rental_options[]`, `recommended_vehicle`, `total_km_estimate`, `fuel_cost_estimate`, `toll_estimate`, `road_condition_notes`, `local_driving_tips[]`

---

### LAYER 4 — Enrichment (parallel)

**ReviewsAgent** (`agents/reviews_agent.py`)
- Waits for: `stays_shortlist` (from StayAnalyst — fetches reviews for all shortlisted options, not just the default pick) + `experiences_raw` (from LocalExperiences)
- Tools: `google_place_search(name, location)` → place_id; `google_place_details(place_id)` → `rating`, `user_ratings_total`, `reviews[]`, `photos[]`, `opening_hours`, `website`, `google_maps_url`
- Fetches for: all shortlisted hotels + top experiences for each day
- LLM synthesizes per place: `pros[]`, `cons[]`, sentiment
- Photo URLs + `google_maps_url` stored for frontend carousels and map pins
- Writes `state["reviews_summary"]`

**FoodDiscoveryAgent** (`agents/food_discovery_agent.py`) ← *new*
- Waits for: `experiences_raw` (needs neighbourhood context from day clusters, so this is not a raw Layer 2 search)
- Tools: `google_places_search(location, included_types=["restaurant","cafe","meal_takeaway"], min_rating=4.0)` filtered by `user_profile.dietary_restrictions` and `budget_tier`, Tavily for `"best food in {neighbourhood} {destination} locals recommend"` and `"best street food in {destination} {neighbourhood}"`
- Finds top food venues per neighbourhood (mapped to each day's activity cluster)
- Returns: breakfast, lunch, dinner, coffee/snack suggestions per day — each with name, category, cuisine, price range, rating, address, google_maps_url, photos[]
- Writes `state["food_recommendations"]` keyed by day ISO date

**BudgetPlannerAgent** (`agents/budget_planner_agent.py`) ← *new*
- Waits for: `transport_recommendation` (Layer 3) + `stays_pick` (Layer 3) + `destination_context_report` (Layer 1) + `visa_report` if applicable + `self_drive_report` if applicable
- Tools: `CurrencyConvertTool` **(H)** — converts any per-leg or per-category amount between currencies using a live FX rate (cached 12h). Returns `rate` and `fetched_at` so the conversion is auditable.
- Aggregates all costs:
  - Transport: sum of `recommended_legs[].cost`
  - Accommodation: `stays_pick.price_per_night × trip_days`
  - Food: `destination_context_report.real_daily_cost × 0.35 × trip_days` in destination currency (est. 35% of daily spend on food)
  - Activities: estimated from `experiences_raw` price ranges
  - Visa fees: from `visa_report.fees` if international
  - Self-drive: from `self_drive_report.fuel_cost_estimate + toll_estimate` if applicable
- Compares total vs `user_profile.budget_tier` / stated budget
- LLM produces `BudgetReport`:
  - `currency_code`: ISO 4217 code resolved from source + destination countries (e.g. `"INR"` for India domestic, `"JPY"` for destination Japan, `"BDT"` for destination Bangladesh). For international trips, transport legs may span multiple currencies — each leg carries its own `currency_code`; **the `CurrencyConvertTool` (H) normalises every amount into the destination currency for the summary total**, with an optional source-currency equivalent.
  - `total_estimated_cost`: number in destination currency (all mixed-currency inputs converted via FX before summing)
  - `total_in_source_currency`: optional equivalent in the traveller's home currency
  - `fx_rates_used`: map of `{ "JPY→INR": 0.56, ... }` actually applied, each with `fetched_at` — makes the conversion auditable and reproducible
  - `fx_disclaimer`: *"Converted at the interbank rate captured on {date}; your card/bank rate will differ."*
  - `per_category_breakdown`: keyed by category, each amount in `currency_code`
  - `per_day_breakdown[]`: per-day estimate in `currency_code`
  - `vs_budget_verdict`: on-budget / over / under
  - `cost_saving_tips[]`: generated by LLM if over budget
- Writes `state["budget_report"]`

---

### LAYER 5 — Synthesis

**ItineraryCompilerAgent** (`agents/itinerary_agent.py`)
- Receives all state fields — all layers must be complete
- Tool: `cluster_by_proximity(experiences[]) → list[DayCluster]` — k-means on lat/lng, k = trip_days
- Tool: `validate_day_duration(day_cluster, travel_dates) → list[str]` **(B)** — sums `duration_minutes + estimated_transit_to_next` per slot. Flags any slot exceeding 10h or any day exceeding 14h total. Pure Python, no LLM. Compiler uses flags to trim activities before LLM synthesis.
- Tool: `enforce_opening_hours(places[], travel_dates) → list[Conflict]` **(A)** — cross-checks each place’s `opening_hours` against its assigned day and time slot. Returns list of conflicts (e.g. place closed on Tuesday, closes at 12pm but in afternoon slot). Compiler resolves each conflict by moving the place to a valid slot or swapping to an alternative experience before LLM synthesis.
- LLM compiles final `Itinerary` with all `personalization_reason` fields **(C)** populated:
  - `reality_banner` (peak season status, crowd level, seasonal conditions, hidden fees)
  - `transport_section`: `recommended` (default route), `alternatives[]` (2 budget-filtered options) — each with `personalization_reason`, `price_disclaimer`
  - `accommodation_section`: `recommended` (default stay), `alternatives[]` (remaining shortlist, budget-filtered) — each with `personalization_reason`, `price_disclaimer`, full reviews
  - `visa_section` (if international)
  - `days[]`: each with ISO date; `morning/afternoon/evening` slots; each slot has a `primary` Place **and** `alternatives[]` (1–2 swap options for that slot, same neighbourhood, open at that time, matching user interests). Each `Place` has name, description, duration_minutes, photos[], google_maps_url, more_images_url, youtube_search_url, reviews_summary, lat, lng, geotag, `personalization_reason`
  - `food_recommendations[]` per day
  - `self_drive_section` (if applicable)
  - `safety_briefing`
  - `budget_breakdown` (based on recommended picks; recalculates automatically in frontend if user swaps options)
- **Self-critique pass + deterministic final gate (A+B+I)**: after the first compile, a secondary LLM call refines soft qualities only — *"Are there awkward schedule gaps? Are any outdoor-heavy segments poorly matched to the likely season? Is the pace suitable for the traveler count?"* — and may reorder or swap activities. **The hard constraints are then enforced deterministically, not by the LLM**: `enforce_opening_hours()` (A) and `validate_day_duration()` (B) are **re-run on the final compiled itinerary** as the authoritative gate. If either returns any unresolved conflict (a closed venue, a slot >10h, or a day >14h), the compiler auto-resolves (slot-swap / activity replacement / trim) and re-runs the gate — looping on the **tools' output, never the LLM's opinion** — up to a bounded number of iterations. An LLM revision can never reintroduce a violation, because the Python checks have the final say. If the gate still cannot be satisfied after the iteration cap, the offending slot is left empty with an explicit `unresolved_note` rather than shipping a wrong time.
- After compile: reads token usage from Redis, rolls up `token_usage["total"]`, emits `usage_summary` SSE event

---

## Phase 3 — FastAPI Backend

### Endpoints

```
POST /api/trip/plan              → SSE stream, runs full LangGraph
PUT  /api/user/profile           → upsert UserProfile
GET  /api/user/profile           → read UserProfile
GET  /api/trip/{session_id}      → full itinerary JSON
PUT  /api/trip/{id}/itinerary    → persist manual edits (drag-drop reorder)
POST /api/trip/{id}/pdf          → WeasyPrint → application/pdf
GET  /api/trip/public/{slug}     → public shareable (no auth)
GET  /api/trip/{id}/usage        → token + cost breakdown
POST /api/trip/{id}/feedback     → user thumbs up/down → langfuse.score()
GET  /health                     → liveness probe for Cloud Run
GET  /metrics                    → Prometheus metrics
```

**OpenAPI spec** auto-generated at `GET /docs` (Swagger UI) and `GET /openapi.json`. Export `openapi.json` to `backend/openapi.json` for frontend TypeScript type generation.

**Postman collection** at `backend/postman/TripPlanner.postman_collection.json` covers every endpoint. Run with `local.postman_environment.json` (`base_url=http://localhost:8000`).

SSE event types: `agent_start`, `agent_done` (with preview text), `needs_clarification` (with `clarification_prompts[]` — graph halts, user answers, re-POST), `complete` (with itinerary_id), `usage_summary`

### Redis Cache TTLs

| Data | TTL | Key pattern |
|---|---|---|
| SerpAPI flights | 4h | `flights:{origin}:{dest}:{date}` |
| Google Routes API transit | 6h | `transit:{origin}:{dest}:{mode}` |
| SerpAPI hotels | 2h | `hotels:{location}:{checkin}:{checkout}` |
| Google Places details + photos | 48h | `place:{place_id}` |
| Tavily scam/safety/reality | 24h | `tavily:{dest}:{month}:{query_hash}` |
| Rental results | 12h | `rentals:{destination}` |
| FX exchange rates | 12h | `fx:{base}:{quote}` |
| Token usage per session | 7d | `usage:{session_id}:{agent_name}` |

---

## Phase 4 — Observability, Evals, Metrics

### Distributed Tracing (`observability/otel.py`)

OpenTelemetry Python SDK → export via OTLP to Google Cloud Trace. Every agent node wrapped in a span:

```python
with tracer.start_as_current_span(f"agent.{agent_name}") as span:
    span.set_attribute("session_id", session_id)
    span.set_attribute("agent.name", agent_name)
    span.set_attribute("agent.layer", agent_layer)
    span.set_attribute("llm.model", settings.llm_model)
    span.set_attribute("llm.cost_usd", cost)
    result = await agent.run(state)
    span.set_attribute("agent.success", True)
```

Root span `trip.plan` → child spans per agent layer → child spans per agent. Full waterfall in Cloud Trace.

**Locally**: `OTEL_ENDPOINT` set to `http://jaeger:4317` → export to **Jaeger** (added to `docker-compose.yml`, UI at `http://localhost:16686`). Zero code changes to switch to Cloud Trace in prod — only the `OTEL_EXPORTER_OTLP_ENDPOINT` env var changes.

FastAPI auto-instrumented via `opentelemetry-instrumentation-fastapi`.

### LLM Tracing + Evals (`observability/langfuse.py`)

**Langfuse** — open-source, MIT licensed, self-hostable. Free cloud tier: 50,000 events/month (10× LangSmith's free tier).

**Self-hosting locally (zero cost):**
```bash
git clone https://github.com/langfuse/langfuse
cd langfuse
docker compose up   # → http://localhost:3000
```

Add to `docker-compose.yml` as a dev service alongside postgres and redis — all in one `docker-compose up`.

**Integration with LangGraph** — one callback handler, zero changes to agent code:

```python
from langfuse.langchain import CallbackHandler

langfuse_handler = CallbackHandler(
    public_key=settings.langfuse_public_key,
    secret_key=settings.langfuse_secret_key,
    host=settings.langfuse_host,
)

# Pass to every LangGraph invocation:
graph.invoke(state, config={"callbacks": [langfuse_handler]})
```

Every LLM call across all agents is traced automatically: prompt, completion, model, latency, cost, token counts — visible as a nested trace tree in the Langfuse UI.

**LiteLLM integration** — additionally register Langfuse as a LiteLLM callback for cost tracking at the LLM gateway level:

```python
import litellm
litellm.success_callback = ["langfuse"]
litellm.failure_callback = ["langfuse"]
```

**User feedback capture** — Langfuse has built-in thumbs up/down scoring per trace. Wire the frontend "Was this itinerary useful?" button to `POST /api/trip/{id}/feedback` → `langfuse.score()`. Real user signal for eval improvement.

**Eval datasets** (`evals/datasets/`):
- `domestic_trips.jsonl` — 20 queries + expected output field assertions
- `international_trips.jsonl` — 20 queries with visa check assertions
- `edge_cases.jsonl` — ambiguous queries, multi-city, missing info

**Golden ground-truth set (J)** (`evals/golden/`) — small, human-verified, run against **real APIs** (`MOCK_EXTERNAL_APIS=false`):
- `visa_truth.jsonl` — known passport×destination pairs with the *correct* requirement, type, and an official source URL
- `transit_truth.jsonl` — routes where a train/bus is known to exist (catches the "Google Transit has no IRCTC data → invented fare" failure)
- `opening_hours_truth.jsonl` — named venues with verified weekly hours (catches stale/hallucinated hours)
- `fx_truth.jsonl` — currency pairs sanity-checked against a reference rate within a tolerance band
- Purpose: mock evals verify **structure & logic**; the golden set verifies **factual correctness of the content a user actually relies on**. Kept deliberately small (≤ ~15 cases) so it is cheap to run on a schedule / pre-release.

**Custom evaluators** (`evals/evaluators/`) — pure Python, no Langfuse-specific code:
- `itinerary_completeness.py` — all required fields populated
- `route_logic.py` — transit times realistic given distances
- `visa_accuracy.py` — visa type correct for 10 known passport/destination pairs
- `hallucination_check.py` — LLM-as-judge for fabricated place names
- `budget_accuracy.py` — budget totals add up correctly (incl. FX-normalised multi-currency totals)
- `restaurant_relevance.py` — restaurants match dietary restrictions from profile
- `clarification_trigger.py` **(F)** — queries missing a critical field (dates/destination/travelers) must yield `needs_clarification=True` and **must not** produce an itinerary; complete queries must **not** trigger it (guards against over-prompting)
- `golden_accuracy.py` **(J, real-API mode only)** — compares live output against `evals/golden/*` ground truth: visa requirement/type match, transit-route existence, opening-hours match, FX within tolerance. Run with `--mode golden`; gates pre-release, not every PR (to avoid burning API quota).

**`run_evals.py`** — CI eval runner using `langfuse.Langfuse` client:

```python
from langfuse import Langfuse

lf = Langfuse(
    public_key=settings.langfuse_public_key,
    secret_key=settings.langfuse_secret_key,
    host=settings.langfuse_host,
)
# run evaluators → post scores to Langfuse via lf.score()
# compare against baselines.json — exit non-zero if any score regresses >5%
```

Runs on every PR in Cloud Build → **blocks merge if any eval score regresses >5%**.

`run_evals.py` takes a `--mode` flag:
- `--mode mock` (default, every PR): runs the 7 evaluators against fixtures, zero API quota, regression-gated on `baselines.json`.
- `--mode golden` (scheduled / pre-release): sets `MOCK_EXTERNAL_APIS=false` and runs `golden_accuracy.py` against `evals/golden/*` with real APIs, asserting factual correctness against human-verified ground truth. Any visa/transit/opening-hours/FX mismatch fails the run — this is the gate that actually protects user-facing accuracy.

**`evals/baselines.json`** — stores initial passing scores after first clean eval run. Committed to repo. Updated manually when intentional quality improvements are made.

### Prometheus Metrics (`observability/metrics.py`)

Scraped by Google Cloud Managed Prometheus, dashboards in Cloud Monitoring:

```
trip_planning_duration_seconds   histogram — labelled by num_agents_triggered
agent_duration_seconds           histogram — labelled by agent_name, layer
agent_error_total                counter   — labelled by agent_name, error_type
llm_tokens_total                 counter   — labelled by agent_name, provider, model
llm_cost_usd_total               counter   — labelled by agent_name
api_cache_hits_total             counter   — labelled by api_name, hit/miss
trip_reality_crowd_level             counter   — labelled by crowd_level (Low/Moderate/High/Extreme)
trip_is_peak_season                  counter   — labelled by is_peak_season (true/false)
active_planning_sessions         gauge
```

Alerts: P95 latency > 30s, any agent error rate > 5%, LLM cost > $10/day.

### Structured Logging

`structlog` JSON output. Every log line includes `session_id`, `agent_name`, `layer`, `trace_id`. Auto-exported to Cloud Logging from Cloud Run stdout.

---

## Phase 5 — Next.js Frontend

**Stack**: Next.js 14 App Router · Tailwind CSS · shadcn/ui · Google Maps JS API

### Chat-first landing (`app/page.tsx`)
- Single chat input — no account required. Session UUID in `localStorage`.
- Optional "Quick Plan" structured form link.
- Community public itineraries grid in background (SEO + inspiration).

### PreferenceSetup (`components/PreferenceSetup.tsx`)
5-question dismissible overlay after first message: airlines, hotel style, interests, dietary restrictions, budget tier. Calls `PUT /api/user/profile`.

### ClarificationPrompt (`components/ClarificationPrompt.tsx`) ← *new* **(F)**
When the planning stream emits a `needs_clarification` event (a critical field — destination, dates, or travellers — was missing or ambiguous), the feed pauses and this component renders the `clarification_prompts[]` as a short inline question set (e.g. *"What dates are you travelling?"*, *"How many travellers?"*). On submit it merges the answers into the original query and re-POSTs `/api/trip/plan`. The system asks rather than guesses, so the user never receives a confidently-wrong plan built on assumed inputs.

### AgentProgressFeed (`components/AgentProgressFeed.tsx`)
SSE timeline with per-agent icons grouped by layer:
```
Layer 0: 🗺️ Orchestrator         ✅ Mumbai → Tokyo, 5 days, Oct 13–17
Layer 1: 📊 Trip Conditions        ✅ Peak season · High crowds · Mostly sunny
         🌤️ Weather               ✅ 18–24°C, no weather warnings
         ⚠️ Safety Check          ✅ 3 scams flagged
         📋 Visa Check            ✅ Tourist visa required, 5–15 days
Layer 2: ✈️🚂 Transport Search   ✅ 6 route options found
         🏨 Stay Search           ✅ 18 hotels found
         🎯 Experiences Search    ✅ 34 activities found
Layer 3: ✈️ Transport Optimizer   ✅ Direct ANA NH830 recommended
         🏨 Stay Analyst          ✅ Park Hyatt Tokyo selected
Layer 4: ⭐ Reviews               ✅ Reviews for 15 places
         🍽️ Restaurants           ✅ 3 restaurants per day
         💰 Budget                ✅ 1,85,000 INR total — within budget
Layer 5: 📅 Building itinerary    ✅ 5-day plan ready
         🔢 5,842 tokens · ~$0.05 ▾ Breakdown
```

### TripConditionsPanel (`components/TripConditionsPanel.tsx`)
Replaces the old scored banner. Shows factual, neutral travel conditions for the user’s dates:
- **Season badge**: “Peak season” / “Shoulder season” / “Off season” (no colour-coded verdict)
- **Crowd level**: Low / Moderate / High / Extreme with a plain label and specific notes (e.g. “Expect 2–3h queues at Senso-ji”)
- **Weather summary**: condition overview for travel dates, plus any active weather warnings
- **Hidden fees**: itemised list of any taxes, surcharges, or tourist levies
- No gauge, no score, no Go/Caution/Reconsider — purely informational

### RouteMap (`components/RouteMap.tsx`)
Google Maps JS API showing full journey:
- ✈️ Flights: dashed arc (great-circle)
- 🚂 Trains: solid blue polyline (transit layer)
- 🚌 Buses: solid green
- 🚗 Drives: solid orange
- Numbered markers ①②③ per stop — click for city card with arrival/departure
- Data from `route_waypoints[]`

### ItineraryView — day tabs + drag-drop (`@dnd-kit/sortable`)

### DayCard (`components/DayCard.tsx`)
- Header: `"Day 2 · Tue, Oct 14"` + weather icon + temperature
- Mini-map thumbnail (Google Static Maps) with day's locations as numbered pins
- Morning / Afternoon / Evening time slots
- Inline contextual chat (collapsible, pre-seeded questions per day)

### PlaceCard (`components/PlaceCard.tsx`)
- Photo carousel (Google Places photos)
- Geotag chip: `📍 Shibuya Crossing, Tokyo` → Google Maps link
- Rating badge + pros/cons bullets
- Duration chip + opening hours
- Embedded links: 🗺️ Maps · 🔍 Images · 📺 YouTube · 📖 Read more

### StayCard — photos + rationale + price disclaimer

Instead of a single hotel card, the itinerary shows a **`StayOptionsPanel`** — an expandable card set showing all shortlisted options, ordered by the agent's recommendation:
- Each card: photos, rating, price per night, `personalization_reason`, pros/cons, `price_disclaimer`, [View on Google Hotels] link
- **Recommended badge** on the agent's top pick
- User can read all options and decide. No action needed in-app — this is informational. Booking happens on the hotel's own site.
- All options are guaranteed to match `user_profile.hotel_style` and `budget_tier` — no luxury option will appear for a budget traveller.

### TransportOptionsPanel (`components/TransportOptionsPanel.tsx`) ← *new*
Shows the recommended route plus 2 budget-filtered alternatives side-by-side:
- Each option: legs summary, total cost, total duration, `personalization_reason`, `price_disclaimer` per leg
- **Recommended badge** on the agent's top pick
- `TransportInsightCallout` (amber) when `non_obvious_insight` is present
- Booking links per mode (IRCTC / Omio / Google Flights etc.)

### ActivityOptionsInSlot — swap alternatives per time slot
Each morning/afternoon/evening slot in `DayCard` shows a **primary `PlaceCard`** plus a collapsible **"Alternatives"** section with 1–2 swap options:
- Same neighbourhood, open at that time, matching user interests
- Each alternative shows photo, rating, duration, `personalization_reason`
- User can mentally swap — purely informational, no in-app booking

### TransportLegCard — per leg with booking links by mode:
- Flights: [Google Flights]
- Trains (India): [IRCTC] · (Europe): [Omio] · (Asia): [12Go]
- Buses: [RedBus] or regional equivalent

### FoodCard (`components/FoodCard.tsx`) ← *new*
- Per-day food recommendations (breakfast / lunch / dinner / coffee / snacks)
- Google Places rating, venue category, cuisine type, price range, distance from day's activities
- Embedded links: 🗺️ Maps · 📺 Reviews on YouTube

### BudgetBreakdownPanel (`components/BudgetBreakdownPanel.tsx`) ← *new*
- Collapsible panel showing per-category cost table
- Progress bar vs stated budget
- Green / amber / red verdict badge
- Cost-saving tips list if over budget
- For international trips: shows the destination-currency total plus the home-currency equivalent, with the `fx_disclaimer` (*"Converted at the interbank rate on {date}; your bank rate will differ"*) and the `fetched_at` date of the FX rate used

### VisaPanel (`components/VisaPanel.tsx`)
- Visa type badge: green (visa-free) / blue (e-visa / on arrival) / amber (visa required) / red (restricted)
- Step-by-step application guide, documents checklist, timeline, fees
- Embassy / consulate card: name, address, phone, hours, appointment link
- Application centre card: shows whichever company handles that corridor (VFS Global, BLS International, TLScontact, etc.) — name, address, phone, hours, booking link. Label is dynamic, not hardcoded as "VFS".
- [Apply Online] button → `apply_online_url`
- **Sources & freshness (G)**: a "Sources" list links each grounding URL (official government / embassy / centre pages) with its date; a "Checked on {last_verified_at}" stamp is always shown; a fixed disclaimer reads *"Visa rules change frequently — always confirm with the official consulate before booking."* When `confidence="low"` (no official source found), a prominent amber warning replaces the green confidence state and tells the user to verify directly.

### SelfDrivePanel — rental options, fuel calculator widget, road tips

### ScamSafetyPanel — amber/red accent, advisory badge, scam list, emergency contacts

### PlanningCostBadge — total tokens + USD, expandable per-agent breakdown table

### PDF Download + Share buttons

---

## Phase 6 — Google Cloud Deployment

```mermaid
graph LR
    Users -->|HTTPS| LB["Cloud Load Balancer\n+ Cloud CDN"]
    LB --> FE["Cloud Run\nNext.js Frontend"]
    LB --> API["Cloud Run\nFastAPI Backend"]
    API --> PDF["Cloud Run\nWeasyPrint PDF"]
    API --> DB["Cloud SQL\nPostgreSQL 15"]
    API --> Cache["Memorystore\nRedis 7"]
    API --> Trace["Cloud Trace\n(OTel OTLP)"]
    API --> Logs["Cloud Logging"]
    API --> Mon["Cloud Monitoring\n(Prometheus)"]
    API --> LF["Langfuse\n(LLM traces + evals)"]
    CB["Cloud Build\nCI/CD"] --> AR["Artifact Registry\n(Docker images)"]
    AR --> FE & API & PDF
    SM["Secret Manager"] -.->|inject at runtime| API
```

| Service | GCP Product | Notes |
|---|---|---|
| Backend API | Cloud Run (FastAPI) | Auto-scales 0→N, pay-per-use |
| Frontend | Cloud Run (Next.js) | Or Firebase Hosting for static export |
| Database | Cloud SQL PostgreSQL 15 | Private IP, auto-backups, IAM auth |
| Cache | Cloud Memorystore Redis 7 | Managed, private VPC |
| PDF service | Cloud Run (separate container) | WeasyPrint isolated — heavy binary |
| Container images | Artifact Registry | All Docker images stored + scanned |
| CI/CD | Cloud Build | PR → test → eval → build → deploy |
| Secrets | Secret Manager | All API keys injected at runtime via `--set-secrets` |
| Logs | Cloud Logging | Auto from Cloud Run stdout JSON |
| Traces | Cloud Trace | OTel OTLP exporter |
| Metrics | Cloud Monitoring | Managed Prometheus scrapes `/metrics` |
| CDN | Cloud CDN + Load Balancer | Frontend assets cached globally |

**Region**: `asia-south1` (Mumbai) — primary Indian user base, lowest latency.

**Terraform** (`infra/`): single `terraform apply` provisions everything. Workspaces: `dev`, `staging`, `prod`.

**CI/CD** (`cloudbuild.yaml`):
```
On PR:    unit tests → eval regression (Langfuse) → build images
On merge: deploy to Cloud Run blue/green → smoke tests → promote
```

---

## Phase 7 — Data Layer

```sql
CREATE TABLE user_profiles (
    session_id   UUID PRIMARY KEY,
    profile_json JSONB NOT NULL,
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE trips (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id       UUID NOT NULL,
    slug             VARCHAR(80) UNIQUE,
    public           BOOLEAN DEFAULT FALSE,
    query            TEXT,
    is_international BOOLEAN DEFAULT FALSE,
    state_json       JSONB,
    itinerary_json   JSONB,
    crowd_level      VARCHAR(10),       -- Low / Moderate / High / Extreme
    is_peak_season   BOOLEAN,
    token_usage_json JSONB,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_trips_session ON trips(session_id);
CREATE INDEX idx_trips_public  ON trips(public) WHERE public = TRUE;
CREATE INDEX idx_trips_crowd ON trips(crowd_level);
```

---

## Execution Order & Parallelism

```mermaid
sequenceDiagram
    participant U as User
    participant FE as Next.js UI
    participant OA as OrchestratorAgent
    participant L1 as Layer 1 (parallel)
    participant L2 as Layer 2 (parallel)
    participant L3 as Layer 3 (parallel)
    participant L4 as Layer 4 (parallel)
    participant L5 as ItineraryCompiler

    U->>FE: "5 days Tokyo from Mumbai"
    FE->>OA: POST /api/trip/plan (SSE)
    OA-->>FE: SSE agent_start
    OA->>L1: fire all Layer 1 agents
    OA->>L2: fire all Layer 2 agents
    Note over L1,L2: Layers 1 & 2 run fully in parallel

    L1-->>FE: SSE: TripReality done (Peak season · High crowds)
    L1-->>FE: SSE: Weather done (sunny 18-24°C)
    L1-->>FE: SSE: ScamSafety done (3 scams)
    L1-->>FE: SSE: Visa done (tourist visa required)
    L2-->>FE: SSE: TransportSearch done
    L2-->>FE: SSE: StaySearch done
    L2-->>FE: SSE: LocalExperiences done

    L2->>L3: TransportSearch → TransportOptimizer
    L2->>L3: StaySearch → StayAnalyst
    L2->>L3: TransportSearch → SelfDriveSearch (if intent)
    Note over L3: Layer 3 agents run in parallel

    L3-->>FE: SSE: TransportOptimizer done (ANA NH830)
    L3-->>FE: SSE: StayAnalyst done (Park Hyatt)

    L3->>L4: StayAnalyst + LocalExperiences → ReviewsAgent
    L3->>L4: LocalExperiences → FoodDiscoveryAgent
    L3->>L4: TransportOptimizer + StayAnalyst + L1 → BudgetPlanner
    Note over L4: Layer 4 agents run in parallel

    L4-->>FE: SSE: Reviews done
    L4-->>FE: SSE: FoodDiscovery done
    L4-->>FE: SSE: Budget done (within budget, amounts in destination currency)

    L4->>L5: all results → ItineraryCompiler
    Note over L5: geo-cluster → compile → self-critique → finalise
    L5-->>FE: SSE: complete (itinerary_id)
    L5-->>FE: SSE: usage_summary (5,842 tokens · $0.05)
    FE-->>U: render full itinerary
```

**Text summary:**

```
Step 1:  OrchestratorAgent               (sequential — parse + detect + route)

Step 2:  ┌─── Layer 1 + Layer 2 — fully parallel ──────────────────────────────┐
         │  Layer 1:  DestinationContextAgent                                   │
         │            ScamSafetyAgent                                           │
         │            VisaAgent           (is_international only)               │
         │  Layer 2:  TransportSearchAgent                                      │
         │            StaySearchAgent                                           │
         │            LocalExperiencesAgent                                     │
         └──────────────────────────────────────────────────────────────────────┘

Step 3:  TransportOptimizerAgent         (after TransportSearch)
         StayAnalystAgent                (after StaySearch)
         SelfDriveSearchAgent            (conditional, after TransportSearch)
         — parallel with each other

Step 4:  ReviewsAgent                    (after StayAnalyst + LocalExperiences)
         FoodDiscoveryAgent              (after LocalExperiences; needs day-cluster context)
         BudgetPlannerAgent              (after TransportOptimizer + StayAnalyst + Layer 1)
         — parallel with each other

Step 5:  ItineraryCompilerAgent          (after all Step 4 complete)
           → geo-cluster activities by proximity
           → compile full Itinerary Pydantic model
           → LLM self-critique (soft qualities only: gaps, pace, rain)
           → deterministic final gate: re-run enforce_opening_hours() + validate_day_duration()
             on the compiled plan, auto-resolve, loop on the tools' output until clean
           → roll up token_usage from Redis
           → emit usage_summary SSE event
```

---

## Complete File List

| Path | Purpose |
|---|---|
| `backend/app/graph/state.py` | `TripState` TypedDict — all 14 agent fields |
| `backend/app/graph/graph.py` | LangGraph `StateGraph` wiring — all layers + parallel edges |
| `backend/app/graph/router.py` | `conditional_edges` routing logic + clarification gate (halt when `needs_clarification`) |
| `backend/app/models/user_profile.py` | `UserProfile`, `TripDates`, `BudgetPreference`, `ClarificationPrompt` |
| `backend/app/models/itinerary.py` | `Itinerary`, `Day`, `Place`, `FoodVenue`, `Experience` |
| `backend/app/models/transport.py` | `TransportRecommendation`, `RouteLeg`, `RouteWaypoint` |
| `backend/app/models/reports.py` | `DestinationContextReport`, `ScamSafetyReport`, `VisaReport` (+ `sources[]`, `last_verified_at`, `confidence`, `disclaimer`), `SelfDriveReport`, `BudgetReport` (+ FX fields) |
| `backend/app/config.py` | `Settings` (pydantic-settings) + LiteLLM factory + `UsageLogger` |
| `backend/app/agents/orchestrator.py` | Router + orchestrator — parse + parse_confidence + clarification gate + detect intent + conditional_edges |
| `backend/app/agents/destination_context_agent.py` | Layer 1: seasonality · crowd level · hidden fees · seasonal conditions |
| `backend/app/agents/scam_safety_agent.py` | Layer 1: Tavily + advisories |
| `backend/app/agents/visa_agent.py` | Layer 1: visa requirements + embassy + application centre discovery (international only) |
| `backend/app/agents/transport_search_agent.py` | Layer 2: hub ID + SerpAPI flights + Google Routes API transit |
| `backend/app/agents/stay_search_agent.py` | Layer 2: SerpAPI Google Hotels |
| `backend/app/agents/local_experiences_agent.py` | Layer 2: Google Places activities + Tavily |
| `backend/app/agents/transport_optimizer_agent.py` | Layer 3: LLM multi-modal reasoning |
| `backend/app/agents/stay_analyst_agent.py` | Layer 3: LLM stay pick + rationale |
| `backend/app/agents/self_drive_search_agent.py` | Layer 3: rentals + fuel + distance (conditional) |
| `backend/app/agents/reviews_agent.py` | Layer 4: Google Places reviews + photos |
| `backend/app/agents/food_discovery_agent.py` | Layer 4: per-day-cluster food discovery across restaurants, cafes, and street food |
| `backend/app/agents/budget_planner_agent.py` | Layer 4: cost aggregation + FX-normalised totals + budget verdict |
| `backend/app/agents/itinerary_agent.py` | Layer 5: geo-cluster + compile + self-critique + deterministic final gate |
| `backend/app/tools/base.py` | `BaseTool` protocol |
| `backend/app/tools/factory.py` | `ToolFactory` — reads `MOCK_EXTERNAL_APIS`, returns mock or real tool instance |
| `backend/app/tools/mock/serpapi_tools.py` | Mock: `MockFlightSearchTool`, `MockHotelSearchTool` (reads fixtures) |
| `backend/app/tools/mock/transit_tools.py` | Mock: `MockTransitSearchTool` |
| `backend/app/tools/mock/places_tools.py` | Mock: `MockPlaceSearchTool`, `MockPlaceDetailsTool` |
| `backend/app/tools/mock/tavily_tools.py` | Mock: `MockTavilySearchTool` |
| `backend/app/tools/mock/visa_tools.py` | Mock: `MockVisaCentreSearchTool`, `MockEmbassySearchTool` |
| `backend/app/tools/mock/rental_tools.py` | Mock: `MockRentalSearchTool`, `MockFuelPriceTool` |
| `backend/app/tools/mock/geo_tools.py` | Mock: `MockClusterByProximityTool`, `MockDistanceMatrixTool` |
| `backend/app/tools/mock/fx_tools.py` | Mock: `MockCurrencyConvertTool` (reads `fx_rates.json` fixture) |
| `backend/app/tools/mock/hub_tools.py` | Mock: `MockIdentifyHubsTool` |
| `backend/app/tools/real/serpapi_tools.py` | Real: `FlightSearchTool`, `HotelSearchTool` (SerpAPI) |
| `backend/app/tools/real/transit_tools.py` | Real: `TransitSearchTool` (Google Routes API — transit mode) |
| `backend/app/tools/real/places_tools.py` | Real: `PlaceSearchTool`, `PlaceDetailsTool` (Google Places API) |
| `backend/app/tools/real/tavily_tools.py` | Real: `TavilySearchTool` |
| `backend/app/tools/real/visa_tools.py` | Real: `VisaCentreSearchTool` (Tavily-based, discovers correct company per corridor), `EmbassySearchTool` — both return grounding `sources[]` for `VisaReport` |
| `backend/app/tools/real/rental_tools.py` | Real: `RentalSearchTool`, `FuelPriceTool` |
| `backend/app/tools/real/geo_tools.py` | Real: `ClusterByProximityTool` (pure math — fully implemented), `DistanceMatrixTool`, `ValidateDayDurationTool` (B), `EnforceOpeningHoursTool` (A) — (A)+(B) are the deterministic final gate (I) |
| `backend/app/tools/real/fx_tools.py` | Real: `CurrencyConvertTool` (H) — live FX rates, cached 12h, returns `rate` + `fetched_at` |
| `backend/app/tools/real/hub_tools.py` | Real: `IdentifyHubsTool` (LLM geographic reasoning) |
| `backend/app/routers/trip.py` | All trip endpoints + SSE `StreamingResponse` |
| `backend/app/routers/user.py` | Profile endpoints |
| `backend/app/services/pdf_service.py` | WeasyPrint + Jinja2 HTML template |
| `backend/app/services/cache_service.py` | Redis wrapper with TTL helpers per data type |
| `backend/app/observability/otel.py` | OpenTelemetry tracer + per-agent span wrapper |
| `backend/app/observability/langfuse.py` | Langfuse callback handler init, `lf.score()` helper |
| `backend/app/observability/metrics.py` | Prometheus metric definitions |
| `backend/app/db.py` | SQLAlchemy async engine + session |
| `backend/app/main.py` | FastAPI app, OTel middleware, lifespan |
| `backend/migrations/001_initial.sql` | Full schema DDL — run via `make migrate` |
| `backend/evals/datasets/domestic_trips.jsonl` | 20 domestic eval queries + expected field assertions |
| `backend/evals/datasets/international_trips.jsonl` | 20 international eval queries with visa assertions |
| `backend/evals/datasets/edge_cases.jsonl` | 10 edge case queries (ambiguous, multi-city, missing info) |
| `backend/evals/golden/visa_truth.jsonl` | (J) Human-verified visa requirement/type + official source per passport×destination pair |
| `backend/evals/golden/transit_truth.jsonl` | (J) Routes where a train/bus is known to exist |
| `backend/evals/golden/opening_hours_truth.jsonl` | (J) Named venues with verified weekly opening hours |
| `backend/evals/golden/fx_truth.jsonl` | (J) Currency pairs with reference rate + tolerance band |
| `backend/evals/evaluators/itinerary_completeness.py` | All required fields populated |
| `backend/evals/evaluators/route_logic.py` | Transit times realistic given distances |
| `backend/evals/evaluators/visa_accuracy.py` | Visa type correct for 10 known passport/destination pairs |
| `backend/evals/evaluators/hallucination_check.py` | LLM-as-judge: no fabricated place names |
| `backend/evals/evaluators/budget_accuracy.py` | Per-category costs sum to total (within 5% tolerance), incl. FX-normalised totals |
| `backend/evals/evaluators/restaurant_relevance.py` | Restaurants respect `dietary_restrictions` from profile |
| `backend/evals/evaluators/clarification_trigger.py` | (F) Missing critical field → `needs_clarification=True`, no itinerary; complete query → not triggered |
| `backend/evals/evaluators/golden_accuracy.py` | (J, real-API) Live output vs `evals/golden/*` ground truth — visa/transit/hours/FX |
| `backend/evals/baselines.json` | Baseline eval scores for CI regression detection (mock-mode) |
| `backend/evals/run_evals.py` | CI eval runner (`--mode mock` per-PR │ `--mode golden` pre-release) → posts scores to Langfuse, exits 1 if regression |
| `backend/tests/fixtures/` | Realistic JSON fixtures per destination/scenario (flights, hotels, places, weather, scams, visa, rentals, FX) |
| `backend/tests/unit/` | Per-agent unit tests with mock tools injected |
| `backend/tests/integration/` | Full graph tests (4 scenarios, MOCK_EXTERNAL_APIS=true) |
| `backend/postman/TripPlanner.postman_collection.json` | All endpoints with test assertions |
| `backend/postman/local.postman_environment.json` | Local env (`base_url=http://localhost:8000`) |
| `Makefile` | Targets: `dev`, `test`, `lint`, `evals`, `evals-golden`, `migrate` |
| `frontend/src/app/page.tsx` | Chat-first landing |
| `frontend/src/app/itinerary/[id]/page.tsx` | Full itinerary result page |
| `frontend/src/app/i/[slug]/page.tsx` | Public shareable itinerary |
| `frontend/src/components/PreferenceSetup.tsx` | 5-question onboarding overlay |
| `frontend/src/components/AgentProgressFeed.tsx` | SSE timeline feed grouped by layer |
| `frontend/src/components/ClarificationPrompt.tsx` | (F) Renders `needs_clarification` questions; collects answers; re-POSTs `/api/trip/plan` |
| `frontend/src/components/TripConditionsPanel.tsx` | Season badge · crowd level · weather · hidden fees (no score) |
| `frontend/src/components/RouteMap.tsx` | Google Maps JS route visualisation |
| `frontend/src/components/ItineraryView.tsx` | Day tabs + drag-drop |
| `frontend/src/components/DayCard.tsx` | Date + weather + mini-map + time slots |
| `frontend/src/components/PlaceCard.tsx` | Place + photos + geotag + embedded links |
| `frontend/src/components/StayOptionsPanel.tsx` | Shortlisted stays (budget-filtered) with recommended badge, personalization reason, price disclaimer |
| `frontend/src/components/TransportOptionsPanel.tsx` | Recommended route + 2 alternatives with personalization reason, price disclaimer, booking links |
| `frontend/src/components/TransportLegCard.tsx` | Transport leg + booking links |
| `frontend/src/components/TransportInsightCallout.tsx` | Amber callout for non-obvious routes |
| `frontend/src/components/RestaurantCard.tsx` | Restaurant per meal per day |
| `frontend/src/components/BudgetBreakdownPanel.tsx` | Per-category cost table + verdict |
| `frontend/src/components/PackingPanel.tsx` | Weather-based packing checklist |
| `frontend/src/components/VisaPanel.tsx` | Visa + embassy + application centre panel (company name is dynamic) + sources, "Checked on {date}", and confirm-with-consulate disclaimer |
| `frontend/src/components/SelfDrivePanel.tsx` | Rentals + fuel calculator |
| `frontend/src/components/ScamSafetyPanel.tsx` | Safety briefing |
| `frontend/src/components/PlanningCostBadge.tsx` | Token + cost summary |
| `frontend/src/lib/sse.ts` | `useAgentStream` SSE hook |
| `frontend/src/lib/api.ts` | Typed API client |
| `frontend/src/lib/mapUtils.ts` | Google Maps helpers, polyline utils |
| `frontend/src/types/index.ts` | TypeScript types mirroring Pydantic models |
| `infra/cloud_run.tf` | Cloud Run services |
| `infra/cloud_sql.tf` | PostgreSQL instance |
| `infra/memorystore.tf` | Redis instance |
| `infra/variables.tf` | GCP variables |
| `docker-compose.yml` | Local dev |
| `cloudbuild.yaml` | CI/CD pipeline |
| `.env.example` | All required env vars |

---

## Environment Variables (`.env.example`)

```env
# LLM — swap provider with two vars
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o
LLM_BUDGET_PER_TRIP_USD=0.50

# Development mode — set true during Phases 0-4, false when real API keys are available (Phase 5+)
MOCK_EXTERNAL_APIS=true

# APIs — leave blank when MOCK_EXTERNAL_APIS=true; fill in for Phase 5+
SERPAPI_KEY=
GOOGLE_MAPS_KEY=          # Directions + Places + Maps JS + Static Maps + Distance Matrix
TAVILY_KEY=
FX_API_KEY=              # currency exchange-rate provider (e.g. exchangerate.host / Open Exchange Rates)

# Clarification gate — critical fields that must be present before planning starts
CLARIFICATION_REQUIRED_FIELDS=destination,dates,travelers
PARSE_CONFIDENCE_THRESHOLD=0.6

# Observability
# Langfuse — open-source LLM tracing + evals (self-hosted locally, cloud in prod)
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=http://localhost:3000   # local; https://cloud.langfuse.com for cloud tier
OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317   # local Jaeger; replace with Cloud Trace OTLP in prod

# Data
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/tripplanner
REDIS_URL=redis://localhost:6379

# GCP (prod — injected via Secret Manager)
GCP_PROJECT_ID=
GCP_REGION=asia-south1
```

---

## Verification Checklist

1. `docker-compose up` → 5 services healthy (postgres, redis, langfuse, jaeger, backend), `GET /health` 200
2. `MOCK_EXTERNAL_APIS=true` (default): full planning run completes with zero network calls to SerpAPI/Tavily/Google Maps — fixture data flows through all 14 agents correctly
3. **Domestic**: "3 days Osaka from Kolkata, mid-October, food + nightlife" → StayOptionsPanel shows 3–5 budget-filtered hotels, all matching standard tier, no luxury properties; `personalization_reason` visible on each; `price_disclaimer` shown
4. **Budget filtering**: Submit with `budget_tier=budget` → verify zero luxury or premium-class options appear in any StayOptionsPanel, TransportOptionsPanel, or activity slots
5. **Opening hours**: All places in every slot are open on the assigned travel date and time — `enforce_opening_hours()` output shows zero unresolved conflicts
6. **Duration check**: No day slot exceeds 10h total (activities + transit) — `validate_day_duration()` output shows zero overloaded flags
6b. **Deterministic final gate (I)**: re-running `enforce_opening_hours()` and `validate_day_duration()` on the *final* compiled itinerary returns zero conflicts; deliberately inject a closed-venue/overpacked case and confirm the compiler auto-resolves it (the Python tools, not the LLM, have the final say)
6c. **Clarification gate (F)**: "plan a trip to Tokyo" (no dates, no travellers) → stream emits `needs_clarification` with prompts for dates + travellers and produces **no** itinerary; after answering and re-POSTing, a full itinerary is returned. A complete query never triggers the gate.
3. **International**: "5 days Tokyo from Mumbai" → VisaPanel: Japan tourist visa, docs checklist, nearest Japanese embassy Mumbai, nearest application centre (e.g. VFS Global for Japan in India), ~5 business days processing; centre name is dynamically discovered, not hardcoded
3b. **Visa sources & disclaimer (G)**: the VisaPanel shows a non-empty `sources[]` (at least one official-domain URL), a "Checked on {date}" stamp, and the confirm-with-consulate disclaimer; a corridor with no official source resolves to `confidence="low"` with a prominent verify-directly warning
4. TripConditionsPanel shows season badge (e.g. “Peak season”), crowd level, weather summary, hidden fees — no score or verdict displayed
4. **Route optimization**: "Kolkata to Leh" → TransportInsightCallout shows direct vs via-Delhi cost+time; RouteMap shows polyline with ① KOL ② LEH (or via hub)
5. **Self-drive**: "rent a scooter in Goa" → SelfDrivePanel with Goa scooter rentals, fuel estimate, road tips
6. Day 1 card: ISO date shown, mini-map with pins, photo carousels, geotag chips, Google/YouTube links
7. Budget: BudgetBreakdownPanel shows per-category table (transport / stay / food / activities / visa) + per-day estimate + vs-budget verdict
7b. **FX (H)**: for an international trip, the budget total is shown in destination currency with a home-currency equivalent; `fx_rates_used` (with `fetched_at`) and the FX disclaimer are present; `budget_accuracy` eval confirms FX-normalised per-category amounts sum to the total within 5%
8. Drag day-2 activity to day-1 → `PUT /api/trip/{id}/itinerary` persists
9. Set trip public → `GET /i/{slug}` returns without auth
11. `PlanningCostBadge` shows total tokens + LLM cost in USD (LLM providers always bill in USD); trip budget totals shown in destination currency in BudgetBreakdownPanel
12. Langfuse: full LLM traces with prompt/completion/cost per agent visible at `http://localhost:3000`
13. `POST /api/trip/{id}/feedback` with `{"rating": 1}` → score appears in Langfuse trace
14. Jaeger: waterfall with all 14 agent spans and layer labels visible at `http://localhost:16686`
13. `GET /metrics` Prometheus metrics visible in Cloud Monitoring
14. `run_evals.py`: all 6 evaluators pass; score regression blocks CI
14b. **Golden evals (J)**: `run_evals.py --mode golden` against real APIs passes `golden_accuracy` — visa requirement/type, transit-route existence, opening hours, and FX all match the human-verified `evals/golden/*` ground truth within tolerance
15. PDF: route map, day plans with dates, food recommendations, budget table, safety section, visa section (if international)

---

## Key Decisions

- **No luxury shown to budget travellers**: `StayAnalystAgent` hard-filters by `budget_tier` before ranking. `TransportOptimizerAgent` eliminates disproportionate options before LLM reasoning. A user who says "standard hotel, budget trip" will only ever see options that match. This is enforced at the data layer, not the LLM prompt layer.
- **Multi-option itinerary**: Instead of a single AI-picked stay/route, the user receives a curated shortlist filtered to their profile — top 3–5 stays, top 3 transport options, 1–2 activity swap alternatives per slot. The AI flags its recommendation but the final choice is the user’s. No confirmation UI pause — the options are inline in the finalised itinerary.
- **Opening hours enforcement (A)**: `enforce_opening_hours()` tool runs before LLM synthesis. No place is assigned to a slot when it is closed. Conflicts resolved by slot-swap or activity replacement, not silently dropped.
- **Duration budget check (B)**: `validate_day_duration()` tool sums activity durations + transit times per slot. Flags overloaded days before the LLM sees them, preventing implausibly packed schedules.
- **Personalization rationale (C)**: Every recommended hotel, transport route, and activity slot carries a `personalization_reason` field — a 1-sentence explanation tied to the user’s stated profile. Makes the personalization visible, not invisible.
- **Tavily grounding check (D)**: Tavily-sourced experiences verified via Google Places before entering the itinerary. Unverifiable venue names dropped silently. Eliminates hallucinated place names.
- **Price freshness disclaimer (E)**: Every `RouteLeg` and `StayOption` carries `price_cached_at` (datetime) and a human-readable `price_disclaimer`. Shown in the UI so users verify before booking.
- **Clarification gate (F)**: The OrchestratorAgent never silently guesses critical inputs. If destination, dates, or traveller count are missing or low-confidence, the graph halts at a `clarification` node, emits a `needs_clarification` SSE event, and asks the user — before spending any API quota or generating a plan built on assumptions. Optional fields fall back to profile defaults.
- **Visa is advisory with sources (G)**: `VisaReport` always carries `sources[]` (preferring official `.gov`/consulate domains), a `last_verified_at` timestamp, a `confidence` level, and a fixed "confirm with the consulate" disclaimer. The system never asserts a visa requirement without a grounding source; if no official source is found, confidence is `low` and the UI warns the user prominently. High-stakes information is framed as guidance, never authority.
- **FX normalisation (H)**: A dedicated `CurrencyConvertTool` (live rates, cached 12h) converts every mixed-currency amount into the destination currency before the budget total is summed. `BudgetReport` records the exact `fx_rates_used` with their `fetched_at` and shows an FX disclaimer — so multi-currency totals are correct, auditable, and honestly caveated.
- **Deterministic final gate (I)**: The LLM self-critique handles only soft qualities (gaps, pace, rain). The hard constraints — opening hours (A) and per-day duration (B) — are enforced by re-running the pure-Python tools on the *final* compiled itinerary and looping on the **tools' output, not the LLM's opinion**. An LLM revision can never reintroduce a closed-venue or overpacked-day violation.
- **Golden-set accuracy evals (J)**: Mock evals (regression-gated every PR) verify structure and logic; a small, human-verified `evals/golden/*` set run against **real APIs** (`run_evals.py --mode golden`, pre-release) verifies the *factual correctness* of what the user relies on — visa rules, transit-route existence, opening hours, and FX rates. This is the gate that protects real-world reliability, not just internal consistency.
- **6-layer agent architecture**: Layers make dependencies explicit, parallelism maximal, and testing per-layer clean. Layer 1 + Layer 2 always run in parallel. Each subsequent layer waits only for its direct dependencies.
- **DestinationContextAgent dedicated**: seasonality, crowd pressure, practical costs, and local constraints are planning context, not raw supply search. Keeping them together produces a clear destination brief without pretending a near-term forecast is reliable months in advance.
- **LocalExperiencesAgent as a first-class agent**: Extracting activity search from the compiler into its own Layer 2 agent means the compiler has structured experience data to geo-cluster, ReviewsAgent has specific targets to enrich, and FoodDiscoveryAgent knows which neighbourhoods each day covers.
- **FoodDiscoveryAgent dedicated**: food planning is not limited to formal restaurants. Per-neighbourhood, per-meal-type, dietary-restriction-aware discovery across restaurants, cafes, takeaways, and street-food spots produces meaningfully better output than a generic LLM suggestion.
- **BudgetPlannerAgent dedicated**: Real users have budgets. Aggregating costs from 4+ agents into a single verdict with day-by-day breakdown requires its own agent — the compiler shouldn't be doing financial aggregation.
- **Transport search: SerpAPI + Google Routes API + LLM hub reasoning**: Covers real-time flight prices, structured train/bus data (IRCTC, European rail, intercity buses), and combinatorial route intelligence.
- **Langfuse for LLM tracing + evals**: Open-source (MIT), self-hostable for $0 via Docker Compose alongside postgres and redis in `docker-compose.yml`. Free cloud tier: 50,000 events/month. Integrated via a single `CallbackHandler` passed to every LangGraph invocation — zero agent code changes. Also registered as a LiteLLM callback for cost tracking at the gateway level. User feedback (thumbs up/down) wired via `lf.score()` for real user signal. Evaluator logic is pure Python — completely portable if switching observability tool later.
- **Mock-first development**: `MOCK_EXTERNAL_APIS=true` flag + `ToolFactory` + fixture JSON files allow all 14 agents to be built, tested, and evaluated without any API keys or network calls. Flip to `false` + add real keys in Phase 5 — zero agent code changes required.
- **BaseTool protocol + DI**: Agents are testable without any API calls. `ToolFactory(mock=True)` injected in tests — no monkey-patching.
- **Shareable itineraries from day one**: `slug` + `public` in schema; community discovery page is post-MVP but no migration needed when built.
- **Secret Manager in prod**: Zero secrets in code, Dockerfiles, or build artifacts.

---

## Post-MVP Additions

| Item | Type | Purpose |
|---|---|---|
| `BudgetOptimizerAgent` | Agent | Re-ranks transport/stay options if total exceeds stated budget |
| `LocalEventsAgent` | Agent | Eventbrite / Google Events API — concerts, festivals during travel dates |
| `TrainBookingAgent` | Agent | Deep-links to IRCTC / Omio / 12go.asia for direct booking |
| `AccessibilityAgent` | Agent | Wheelchair access, dietary options, quiet hours per attraction |
| Firebase Auth | Feature | User accounts for cross-device trip persistence + trip history |
| Community page | Feature | Public itinerary discovery grid — SEO flywheel |
| Multi-city support | Feature | OrchestratorAgent parses multi-destination queries into sequential sub-trips |
| A2A Protocol | Infra | Google Agent-to-Agent for external agent system interoperability |
| Eval regression dashboard | Observability | Langfuse eval score trends over time + user feedback analysis |