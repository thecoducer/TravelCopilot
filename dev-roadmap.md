# Multi-Agent AI Trip Planner — Engineering Dev Roadmap

> Created: 2026-06-15  
> Last updated: 2026-06-20  
> Based on: System Design Plan v6  
> Strategy: Mock-first → Real APIs → Frontend last

**Phase 0 status**: ✅ All code items complete. 3 runtime-verification items (docker up, psql, log check) pending first `docker-compose up`.  
**Phase 1 status**: ✅ Complete. 113/113 tests passing, 0 ruff violations, 0 mypy errors.  
**Phase 2 status**: ✅ Complete. 149 tests passing (135 unit + 14 integration). All 14 agents wired, clarification gate (F), grounding (G/D), budget filters, deterministic opening-hours + duration gates (A/B/I), `stays_shortlist` with personalization, transport alternatives.  
**Phase 3 status**: ✅ Core complete. SSE endpoint with Langfuse + clarification event, DB persistence, PDF service (WeasyPrint + Jinja2), feedback endpoint, Prometheus metrics, request-ID middleware. Postman collection pending.

**Key design decisions enacted in Phase 1:**
- Itinerary is options-based: every time slot, stay, and food choice has 2–3 ranked options with `recommendation_reason` and `best_for` tags
- Multi-stop trips use `TripSegment` (one per location) — each segment carries its own `StayOptions`, `permits_required`, `altitude_meters`, `connectivity` note
- AI clarification: `ClarificationRequest` model; `Itinerary.clarifications_needed[]` surfaces gaps before the user gets a fixed plan
- Fixtures aligned to real SerpAPI / Google Places / Tavily API response shapes — Phase 5 parsers will be drop-in
- `ClusterByProximityTool` uses haversine distance matrix + `AgglomerativeClustering` (sklearn) rather than Euclidean k-means
- All tool `run()` methods typed `-> dict[str, Any]`; mypy strict mode passes cleanly

---

## Guiding Principles

- **Mock-first**: Every external API (SerpAPI, Tavily, Google Maps) is mocked during Phases 1–4. Real APIs are drop-in replacements in Phase 5. Zero wasted API quota during development.
- **Backend-first**: All FastAPI endpoints are Postman-testable before any frontend work begins.
- **Agent-first within backend**: Agents and graph are fully functional before endpoints are wired.
- **Evals from day one**: Langfuse and eval datasets set up in Phase 3 — not as an afterthought.
- **Each phase produces a working, testable artifact** — nothing is half-built at end of phase.

---

## Phase 0 — Project Scaffolding

> **Goal**: Empty repo → runnable skeleton with all services up, folder structure in place, config loading, and mock tool stubs created.
> **Done when**: `docker-compose up` starts all services; `GET /health` returns 200; `python -c "from app.config import settings; print(settings.llm_model)"` works.

### P0-1 · Repository & Tooling Setup
- [x] Initialise Git repo with `.gitignore` (Python, Node, `.env`, `__pycache__`)
- [x] Create monorepo structure: `backend/`, `frontend/`, `infra/`
- [x] Add `backend/pyproject.toml` with dependencies: `fastapi`, `uvicorn`, `langgraph`, `langchain`, `litellm`, `pydantic-settings`, `sqlalchemy[asyncio]`, `asyncpg`, `redis[hiredis]`, `structlog`, `opentelemetry-sdk`, `opentelemetry-instrumentation-fastapi`, `langfuse`, `pytest`, `pytest-asyncio`
- [x] Add `backend/.python-version` pinned to 3.12
- [x] Add `frontend/package.json` stub (no implementation yet — just initialise)
- [x] Add `Makefile` with targets: `make dev`, `make test`, `make lint`, `make evals`, `make evals-golden`

### P0-2 · Docker Compose (local dev)
- [x] Write `docker-compose.yml` with services:
  - `postgres` (PostgreSQL 15, port 5432, persistent volume)
  - `redis` (Redis 7, port 6379)
  - `langfuse` (Langfuse self-hosted, port 3000) — use official `langfuse/langfuse` image
  - `backend` (FastAPI, port 8000, hot-reload via `--reload`, mounts `backend/` as volume)
- [x] Add `docker-compose.override.yml` for local dev overrides (e.g. skip frontend)
- [ ] Verify `docker-compose up` starts all 4 services cleanly

### P0-3 · Environment Config
- [x] Create `.env.example` with all keys from plan (no real values)
- [x] Create `.env` from example — fill in `DATABASE_URL`, `REDIS_URL`, `LANGFUSE_*` (local), dummy strings for API keys (will be replaced in Phase 5)
- [x] Implement `backend/app/config.py` — `Settings` class via `pydantic-settings`, reads from `.env`
- [x] Add `MOCK_EXTERNAL_APIS=true` flag to `Settings` — when true, all tools return mock data
- [x] Add `FX_API_KEY` to `Settings` (currency exchange-rate provider — blank in mock mode)
- [x] Add clarification-gate settings: `CLARIFICATION_REQUIRED_FIELDS=destination,dates,travelers`, `PARSE_CONFIDENCE_THRESHOLD=0.6`
- [x] Write smoke test: `assert settings.llm_provider == "openai"`

### P0-4 · Database Setup
- [x] Implement `backend/app/db.py` — SQLAlchemy async engine + `AsyncSession` factory
- [x] Write raw SQL migration file `backend/migrations/001_initial.sql` with full schema (user_profiles, trips tables + all indexes)
- [x] Add `make migrate` target that runs migration SQL against local postgres
- [ ] Verify tables created: `psql` → `\dt` shows all 3 tables

### P0-5 · Structured Logging
- [x] Configure `structlog` in `backend/app/main.py` — JSON output, log level from env
- [x] Add `trace_id`, `session_id`, `agent_name` as log context fields
- [ ] Verify log output is valid JSON in `docker-compose logs backend`

---

## Phase 1 — Data Models + Mock Tool Layer

> **Goal**: All Pydantic models defined. All external tools implemented twice — once as mock (returns hardcoded realistic fixtures), once as real (stubs with `raise NotImplementedError`). `BaseTool` protocol enforced.
> **Done when**: Every tool can be instantiated in both mock and real mode; `MOCK_EXTERNAL_APIS=true` → all tools return fixture data without any network call.

### P1-1 · BaseTool Protocol + Tool Factory
- [x] Implement `backend/app/tools/base.py` — `BaseTool` Protocol with `name`, `description`, `async def run(**kwargs) -> dict`
- [x] Implement `ToolFactory` in `backend/app/tools/factory.py` — reads `settings.mock_external_apis`, returns mock or real tool instance for each tool name
- [x] Write unit test: `ToolFactory(mock=True).get("search_flights")` returns `MockFlightSearchTool`

### P1-2 · Pydantic Models — User & Core
- [x] `backend/app/models/user_profile.py`: `UserProfile`, `TripDates`, `BudgetPreference`, `ClarificationPrompt` (`field`, `question`, `reason`)
- [x] `backend/app/models/itinerary.py`: `Itinerary`, `TripSegment`, `Day`, `TimeSlotOptions`, `ActivityOption`, `Place`, `FoodVenue`, `FoodOptions`, `StayOptions`, `ClarificationRequest`, `Experience`
- [x] `backend/app/models/transport.py`: `TransportRecommendation`, `RouteLeg`, `RouteWaypoint`, `StayOption`
- [x] `backend/app/models/reports.py`: `DestinationContextReport`, `ScamSafetyReport`, `VisaReport`, `SelfDriveReport`, `BudgetReport`, `ReviewSummary`, `AgentTokenUsage`
  - [x] `VisaReport` includes **(G)** `sources[]` (`title`, `url`, `published_or_fetched_date`), `last_verified_at`, `confidence` (`high`/`medium`/`low`), `disclaimer`
  - [x] `BudgetReport` includes **(H)** `total_in_source_currency`, `fx_rates_used` (map of pair → `{rate, fetched_at}`), `fx_disclaimer`
- [ ] Add clarification fields to `TripState` in `state.py`: `needs_clarification: bool`, `clarification_prompts: list[ClarificationPrompt]`, `parse_confidence: dict[str, float]` ← Phase 2 (state.py not yet created)
- [x] Write model validation tests for every Pydantic model (required fields, type coercion), incl. `VisaReport.sources` and `BudgetReport.fx_rates_used`

### P1-3 · Mock Tool Fixtures
- [x] Create `backend/tests/fixtures/` directory with realistic JSON fixture files:
  - `flights_kolkata_leh.json` — 3 domestic flight options (SerpAPI google_flights format)
  - `flights_kolkata_lisbon.json` — 3 international flight options (SerpAPI format)
  - `hotels_leh.json` — 8 hotel options with ratings, prices (SerpAPI google_hotels format)
  - `hotels_lisbon.json` — 8 hotel options
  - `places_leh_attractions.json` — 12 attractions with lat/lng (Google Places new API format)
  - `places_lisbon_attractions.json` — 12 attractions
  - `food_leh.json` — 9 food venues across restaurants, cafes, street food (Google Places format)
  - `transit_kolkata_delhi.json` — train + bus options (Google Routes API format)
  - `scams_leh.json` — 4 scam entries (Tavily format)
  - `scams_lisbon.json` — 3 scam entries (Tavily format)
  - `visa_india_portugal.json` — full visa report (VFS Global; `application_centre`, `sources[]`, `last_verified_at`, `confidence`)
  - `rentals_leh.json` — 5 rental options
  - `fx_rates.json` — reference exchange rates (JPY/EUR/USD/GBP → INR) with `fetched_at`

### P1-4 · Mock Tool Implementations
- [x] `backend/app/tools/mock/serpapi_tools.py` — `MockFlightSearchTool`, `MockHotelSearchTool` (read from fixtures based on origin/dest/location)
- [x] `backend/app/tools/mock/transit_tools.py` — `MockTransitSearchTool` (read from fixtures)
- [x] `backend/app/tools/mock/places_tools.py` — `MockPlaceSearchTool`, `MockPlaceDetailsTool` (read from fixtures)
- [x] `backend/app/tools/mock/tavily_tools.py` — `MockTavilySearchTool` (returns fixture for scam/reality/visa queries based on destination)
- [x] `backend/app/tools/mock/visa_tools.py` — `MockVisaCentreSearchTool` (returns fixture with application centre company name, address, booking URL — company varies by corridor; returns `sources[]` and `last_verified_at`), `MockEmbassySearchTool`
- [x] `backend/app/tools/mock/rental_tools.py` — `MockRentalSearchTool`, `MockFuelPriceTool`
- [x] `backend/app/tools/mock/geo_tools.py` — `MockClusterByProximityTool`, `MockDistanceMatrixTool`
- [x] `backend/app/tools/mock/fx_tools.py` — `MockCurrencyConvertTool` (reads `fx_rates.json`; returns converted amount + `rate` + `fetched_at`) **(H)**
- [x] `backend/app/tools/mock/hub_tools.py` — `MockIdentifyHubsTool` (returns hardcoded plausible hubs for common routes)

### P1-5 · Real Tool Stubs (raise NotImplementedError)
- [x] `backend/app/tools/real/serpapi_tools.py` — stubs for `FlightSearchTool`, `HotelSearchTool`
- [x] `backend/app/tools/real/transit_tools.py` — stub for `TransitSearchTool`
- [x] `backend/app/tools/real/places_tools.py` — stubs for `PlaceSearchTool`, `PlaceDetailsTool`
- [x] `backend/app/tools/real/tavily_tools.py` — stub for `TavilySearchTool`
- [x] `backend/app/tools/real/visa_tools.py` — stubs for `VisaCentreSearchTool` (Tavily-based, discovers correct company per corridor — VFS Global, BLS International, TLScontact, iData, etc.), `EmbassySearchTool`
- [x] `backend/app/tools/real/rental_tools.py` — stubs for `RentalSearchTool`, `FuelPriceTool`
- [x] `backend/app/tools/real/geo_tools.py` — `ClusterByProximityTool` (pure math, no external API — implement fully now), `DistanceMatrixTool` stub
- [x] `backend/app/tools/real/fx_tools.py` — stub for `CurrencyConvertTool` (raise `NotImplementedError`) **(H)**
- [x] `backend/app/tools/real/hub_tools.py` — stub for `IdentifyHubsTool`

### P1-6 · Cache Service
- [x] Implement `backend/app/services/cache_service.py` — Redis wrapper with `get(key)`, `set(key, value, ttl)`, `delete(key)`
- [x] Add TTL constants matching plan (flights 4h, hotels 2h, places 48h, FX 12h, etc.)
- [x] Write unit test with mock Redis client

---

## Phase 2 — LangGraph Graph + All Agents (mock tools)

> **Goal**: Full 14-agent LangGraph graph is wired and executes end-to-end using mock tools. Every agent produces correct typed output written to TripState. Graph runs without errors from OrchestratorAgent through ItineraryCompilerAgent.
> **Done when**: `python -c "from app.graph.graph import run_graph; import asyncio; asyncio.run(run_graph({'query': '3 days Osaka from Kolkata'}))"` returns a complete `Itinerary` object.

### P2-1 · TripState + Graph Skeleton
- [x] Implement `backend/app/graph/state.py` — full `TripState` TypedDict with all fields from plan (incl. `needs_clarification`, `clarification_prompts`, `parse_confidence`, `stays_shortlist`, `transport_alternatives`)
- [x] Implement `backend/app/graph/graph.py` — `StateGraph` with all 14 nodes + `clarification` + `ready_to_plan` fan-out node
- [x] `conditional_edges` routing after orchestrator: `needs_clarification=True` → `clarification` → END; else → `ready_to_plan` → fan-out to all L1+L2
- [x] Add `clarification` terminal node **(F)**
- [x] Add `run_graph(query, session_id)` entrypoint function
- [x] Verify graph compiles: `graph.compile()` raises no errors

### P2-2 · LiteLLM Config + UsageLogger
- [x] `get_llm(agent_name, session_id)` factory in `app/llm.py` returns `LiteLLMChatModel`
- [x] `LiteLLMChatModel(BaseChatModel)` — custom wrapper around `litellm.acompletion()`; supports `.with_structured_output()` via tool-call JSON schema; zero extra packages needed
- [x] Swap any provider with 2 env vars: `LLM_PROVIDER=anthropic LLM_MODEL=claude-3-5-sonnet-20241022`
- [x] `UsageLogger(litellm.CustomLogger)` — writes per-agent token counts to Redis in daemon thread
- [x] `litellm.callbacks = [UsageLogger()]` registered at module load
- [x] `litellm.success_callback = ["langfuse"]` registered at module load when Langfuse keys set
- [x] `_sync_api_keys()` populates LiteLLM's expected env vars from pydantic-settings
- [x] `build_graph(llm=)` injects fake LLM into all agents for testability

### P2-3 · LAYER 0 — OrchestratorAgent
- [x] Implement `backend/app/agents/orchestrator.py`
- [x] LLM prompt: extract `source`, `destination`, `dates`, `travelers`, `budget` with per-field `_FieldConfidence` objects (0–1)
- [x] Set `is_international` via `_INDIAN_CITIES` heuristic + LLM fallback
- [x] Detect `self_drive_intent` from keyword list + LLM
- [x] Security: sanitize input (HTML-unescape, 500-char limit, prompt-injection pattern detection)
- [x] **Clarification gate (F)**: missing/low-confidence required fields → `needs_clarification=True` + `clarification_prompts[]`
- [x] Unit test: fully-specified query → `needs_clarification=False`
- [x] Unit test: `self_drive_intent` keyword detection
- [x] Unit test: vague query → `needs_clarification=True` + prompts
- [x] Integration test (F): graph halts at clarification node, no itinerary produced

### P2-4 · LAYER 1 — Destination Intelligence Agents
- [x] Implement `backend/app/agents/destination_context_agent.py` (3 Tavily queries, `DestinationContextReport`)
- [x] Implement `backend/app/agents/scam_safety_agent.py` (2 Tavily queries, `ScamSafetyReport`)
- [x] Implement `backend/app/agents/visa_agent.py`
  - [x] Conditional: no-op for domestic trips
  - [x] **(G)** `_classify_sources()` — official-domain regex → `confidence` level
  - [x] **(G)** `visa_required` never asserted without sources; no sources → `confidence="low"` early return
  - [x] `sources[]`, `last_verified_at`, `confidence`, `disclaimer` all populated
  - [x] Unit tests: domestic skip, international visa report, sources + confidence

### P2-5 · LAYER 2 — Supply Search Agents (no LLM)
- [x] Implement `backend/app/agents/transport_search_agent.py` (hub ID + parallel flight/transit calls)
- [x] Implement `backend/app/agents/stay_search_agent.py` (SerpAPI hotels → `StayOption` list)
- [x] Implement `backend/app/agents/local_experiences_agent.py`
  - [x] **(D)** Tavily grounding check: Tavily names verified via `MockPlaceSearchTool` before inclusion; unconfirmed dropped silently

### P2-6 · LAYER 3 — Analysis Agents (all complete)
- [x] Implement `backend/app/agents/transport_optimizer_agent.py`
  - [x] `_budget_filter()` strips premium/business legs before LLM sees them
  - [x] `_OptimiserOutput` schema returns recommended + up to 2 budget-filtered alternatives
  - [x] Every `RouteLeg` has `price_cached_at` + non-empty `price_disclaimer`
  - [x] Integration test: transport recommendation populated in full graph run
- [x] Implement `backend/app/agents/stay_analyst_agent.py`
  - [x] `_budget_filter()` removes hotels outside price-tier thresholds before LLM ranking
  - [x] `stays_shortlist[]` — each option has `personalization_reason` + `price_disclaimer`
  - [x] `stays_pick` = first shortlist item (recommended default)
  - [x] Integration test: stays_shortlist populated when fixture data available
- [x] Implement `backend/app/agents/self_drive_search_agent.py`
  - [x] No-op (returns `{"self_drive_report": None}`) when `self_drive_intent=False`
  - [x] Fuel cost estimate: total_km / mileage x fuel_price
  - [x] Integration test: `self_drive_report` populated when `self_drive_intent=True`
### P2-7 · LAYER 4 — Enrichment Agents
- [x] Implement `backend/app/agents/reviews_agent.py` — fetches for ALL `stays_shortlist` hotels + top 8 experiences
- [x] Implement `backend/app/agents/food_discovery_agent.py` — neighbourhood-grouped, diet-filtered
- [x] Implement `backend/app/agents/budget_planner_agent.py`
  - [x] **(H)** FX normalisation via `MockCurrencyConvertTool`; `fx_rates_used` + `fx_disclaimer` populated
  - [x] All 6 cost categories in `per_category_breakdown`

### P2-8 · LAYER 5 — ItineraryCompilerAgent
- [x] Implement `backend/app/agents/itinerary_compiler_agent.py`
  - [x] Inject `MockClusterByProximityTool` + real `ClusterByProximityTool` (sklearn)
  - [x] Inject `MockEnforceOpeningHoursTool` + real `EnforceOpeningHoursTool` **(A)**
  - [x] Inject `MockValidateDayDurationTool` + real `ValidateDayDurationTool` **(B)**
  - [x] Pre-gate: resolve opening-hours + duration issues before first LLM call
  - [x] First LLM: compile `Itinerary` with `recommendation_reason` + `best_for` per activity **(C)**
  - [x] Second LLM: soft self-critique (gaps, rain days, pace)
  - [x] **(I)** Deterministic final gate: re-run A+B on compiled result, up to 3 iterations; `_resolve_conflicts()` auto-removes closed venues + trims slots; `unresolved_note` if still bad
  - [x] `_inject_shortlist()` wires `stays_shortlist` into `TripSegment.stay_options`
  - [x] `_inject_transport()` wires `TransportSection` with recommended + alternatives
  - [x] Integration test (I): closed venue + overpacked day → deterministic gate removes the closed venue

### P2-9 · Full Graph Integration Test
- [x] Write `backend/tests/integration/test_full_graph.py` (14 integration test cases)
- [x] Case 1 (domestic): itinerary returned, 3 days, no clarification
- [x] Case 2 (international + visa): `visa_report` populated, `is_international=True`
- [x] Case 3 (self-drive): `self_drive_report` populated, `visa_report=None`
- [x] Case 4 (route): `transport_recommendation` has `price_disclaimer` on every leg
- [x] Case 5 (budget): shortlisted stays have `personalization_reason` + `price_disclaimer`
- [x] Case 6 (duration): no day slot exceeds 10h
- [x] Case 7 (clarification gate F): vague query → `needs_clarification=True`, no itinerary
- [x] Case 8 (visa sources G): `visa_report.confidence` is set
- [x] Tool-level: `EnforceOpeningHoursTool` real implementation test
- [x] Tool-level: `ValidateDayDurationTool` real implementation test
- [x] Deterministic gate: closed venue injected → resolved by Python (not LLM)
- [x] All cases: zero network calls (mock tools + fake LLM), < 2s total

---

## Phase 3 — FastAPI Endpoints + Postman Testing

> **Goal**: All REST endpoints and SSE endpoint are implemented, documented, and testable end-to-end via Postman with mock data flowing through the entire graph.
> **Done when**: Postman collection runs all requests successfully with `MOCK_EXTERNAL_APIS=true`; SSE stream shows all agent events; PDF downloads correctly.

### P3-1 · FastAPI App Setup
- [x] `backend/app/main.py` — lifespan startup: LiteLLM/Langfuse callback registration
- [x] CORS middleware (dev: all origins; prod: restricted)
- [x] Request-ID middleware: `X-Request-ID` injected into structlog context
- [x] OTel middleware via `FastAPIInstrumentor` (when endpoint configured)
- [x] `GET /health` → `{"status": "ok", "version": "0.1.0"}`
- [x] `GET /metrics` — Prometheus metrics via `prometheus_client`
- [x] `backend/app/observability/metrics.py` — all 8 metric definitions

### P3-2 · Trip Planning Endpoint (SSE)
- [x] `POST /api/trip/plan` — SSE stream with `agent_start`, `agent_done` (with layer + preview), `needs_clarification` **(F)**, `complete`, `usage_summary`, `error`
- [x] Langfuse `CallbackHandler` injected into every graph invocation
- [x] `_persist_trip()` — DB upsert to `trips` table (best-effort, non-blocking)
- [x] `needs_clarification` event returns prompts array + halts stream cleanly (no `complete`)
- [ ] Postman test: POST with `"3 days Osaka from Kolkata"` → verify all agent events + `complete`
- [ ] Postman test (F): `"plan a trip to Tokyo"` → `needs_clarification` event + no `complete`

### P3-3 · User Profile Endpoints
- [x] `PUT /api/user/profile` — SQLAlchemy upsert to `user_profiles` table
- [x] `GET /api/user/profile` — reads from `user_profiles` by `X-Session-ID` header
- [ ] Postman test pending

### P3-4 · Trip CRUD Endpoints
- [x] `GET /api/trip/{session_id}` — latest trip by session from DB
- [x] `PUT /api/trip/{id}/itinerary` — JSON patch for drag-drop reorders
- [x] `GET /api/trip/public/{slug}` — public itinerary (404 if not public)
- [x] `GET /api/trip/{id}/usage` — token usage from DB
- [ ] Postman tests pending

### P3-5 · PDF Endpoint
- [x] `backend/app/services/pdf_service.py` — `render_pdf()` with WeasyPrint + graceful stub fallback when not installed
- [x] `backend/app/services/templates/itinerary.html.j2` — Jinja2 template: reality banner, transport, stay shortlist, day plans (morning/afternoon/evening slots), restaurants, budget table, visa section, self-drive section, safety briefing, packing tips
- [x] `POST /api/trip/{id}/pdf` — fetches itinerary from DB, renders PDF, returns `application/pdf`
- [ ] Postman test pending

### P3-6 · Feedback Endpoint (for Langfuse scoring)
- [x] `POST /api/trip/{id}/feedback` — calls `langfuse.score_trip()` which posts to Langfuse
- [x] `backend/app/observability/langfuse.py` — `get_langfuse_handler()` + `score_trip()` helpers
- [ ] Postman test: POST feedback → verify score in Langfuse UI

### P3-7 · OpenAPI Docs Verification
- [ ] Visit `http://localhost:8000/docs` — verify all endpoints documented with correct request/response schemas
- [ ] Export OpenAPI spec: `http://localhost:8000/openapi.json` — save to `backend/openapi.json` for frontend reference

### P3-8 · Postman Collection
- [ ] Create `backend/postman/TripPlanner.postman_collection.json` covering all endpoints
- [ ] Add environment file `backend/postman/local.postman_environment.json` with `base_url=http://localhost:8000`
- [ ] Document collection in `backend/postman/README.md` with test order and expected outputs

---

## Phase 4 — Observability + Evals Setup

> **Goal**: Langfuse shows full LLM traces for every agent call. Eval datasets written, all mock-mode evaluators pass, `run_evals.py --mode mock` exits 0; a small real-API golden set verifies factual accuracy via `run_evals.py --mode golden`.
> **Done when**: After running a full planning request, Langfuse UI shows nested trace tree; `make evals` exits 0 and prints scores; `make evals-golden` passes against human-verified ground truth.

### P4-1 · Langfuse Integration
- [ ] Implement `backend/app/observability/langfuse.py` — init `CallbackHandler`, `lf.score()` helper function
- [ ] Register Langfuse `CallbackHandler` in every `graph.invoke()` call
- [ ] Register `litellm.success_callback = ["langfuse"]` in `main.py` lifespan
- [ ] Run full planning request → open Langfuse at `http://localhost:3000` → verify:
  - [ ] Trace created per planning request
  - [ ] All LLM calls appear as nested spans with prompt + completion visible
  - [ ] Token counts and cost visible per agent call
  - [ ] Session ID attached to trace

### P4-2 · OpenTelemetry
- [ ] Implement `backend/app/observability/otel.py` — OTel tracer setup, `agent_span()` context manager
- [ ] Set `OTEL_EXPORTER_OTLP_ENDPOINT` to your OTLP collector endpoint when tracing is enabled
- [ ] Wrap every agent `run()` call with `agent_span(name, layer)` context manager
- [ ] Run full planning request → verify `trip.plan` root span with 14 child spans labelled by agent name and layer in your configured tracing backend

### P4-3 · Prometheus Metrics
- [ ] Implement `backend/app/observability/metrics.py` — define all metrics from plan
- [ ] Instrument: `trip_planning_duration_seconds` (histogram, timer around full graph run)
- [ ] Instrument: `agent_duration_seconds` (histogram, timer around each agent node)
- [ ] Instrument: `agent_error_total` (counter, increment on agent exception)
- [ ] Instrument: `llm_tokens_total` (counter, from UsageLogger)
- [ ] Instrument: `llm_cost_usd_total` (counter, from UsageLogger)
- [ ] Instrument: `api_cache_hits_total` (counter, from cache_service)
- [ ] Verify `GET /metrics` returns all metric names

### P4-4 · Eval Datasets
- [ ] Create `backend/evals/datasets/domestic_trips.jsonl` — 20 entries, each: `{ "input": { "query": "..." }, "expected": { "is_international": false, "has_transport": true, ... } }`
- [ ] Create `backend/evals/datasets/international_trips.jsonl` — 20 entries including visa assertions
- [ ] Create `backend/evals/datasets/edge_cases.jsonl` — 10 entries: ambiguous queries, multi-city mentions, missing dates, conflicting info (each with `expected.needs_clarification` where applicable)
- [ ] Dataset coverage: India domestic routes (5), India international (8), Europe (4), Asia-Pacific (5), edge cases (10) = 32 total
- [ ] **(J)** Create human-verified golden ground-truth files in `backend/evals/golden/` (run against REAL APIs, kept ≤ ~15 cases total):
  - [ ] `visa_truth.jsonl` — passport×destination pairs with correct requirement/type + official source URL
  - [ ] `transit_truth.jsonl` — routes where a train/bus is known to exist (catches missing-IRCTC-data → invented fare)
  - [ ] `opening_hours_truth.jsonl` — named venues with verified weekly hours
  - [ ] `fx_truth.jsonl` — currency pairs with a reference rate + tolerance band

### P4-5 · Eval Evaluators
- [ ] `backend/evals/evaluators/itinerary_completeness.py` — check `days[]` non-empty, each day has 3 slots, transport non-None, accommodation non-None, budget_breakdown non-None
- [ ] `backend/evals/evaluators/route_logic.py` — for each day, verify total activity duration ≤ 12 hours; verify transit times between sequential activities are > 0
- [ ] `backend/evals/evaluators/visa_accuracy.py` — for 10 known passport+destination pairs, assert `visa_required` matches known ground truth (hardcoded reference table)
- [ ] `backend/evals/evaluators/hallucination_check.py` — LLM-as-judge prompt: given itinerary, check for place names that clearly don't exist; return score 0–1
- [ ] `backend/evals/evaluators/budget_accuracy.py` — verify `per_category_breakdown` values sum to `total_estimated_cost` (within 5% tolerance), including FX-normalised multi-currency totals **(H)**
- [ ] `backend/evals/evaluators/restaurant_relevance.py` — if `dietary_restrictions` set in profile, verify none of the recommended restaurants violate them (e.g. no beef restaurants for vegetarian profile)
- [ ] `backend/evals/evaluators/clarification_trigger.py` **(F)** — queries missing a critical field yield `needs_clarification=True` and **no** itinerary; complete queries do **not** trigger it
- [ ] `backend/evals/evaluators/golden_accuracy.py` **(J, real-API only)** — compare live output to `evals/golden/*`: visa requirement/type match, transit-route existence, opening-hours match, FX within tolerance
- [ ] Unit test each evaluator with a hand-crafted passing and failing `Itinerary` fixture

### P4-6 · Eval Runner
- [ ] Implement `backend/evals/run_evals.py` with a `--mode {mock,golden}` flag:
  - [ ] `--mode mock` (default, every PR): load each dataset, run `run_graph()` with mock tools, run the mock-mode evaluators (incl. `clarification_trigger`), zero API quota
  - [ ] `--mode golden` **(J)**: set `MOCK_EXTERNAL_APIS=false`, run `run_graph()` against real APIs for `evals/golden/*`, run `golden_accuracy` (visa/transit/opening-hours/FX vs ground truth)
  - [ ] Post score to Langfuse via `lf.score()`
  - [ ] Compare to baseline (stored in `backend/evals/baselines.json`)
  - [ ] Exit code 1 if any mock score regresses > 5%, or if any golden assertion fails
- [ ] Create `backend/evals/baselines.json` — set initial baselines after first clean run
- [ ] Add `make evals` target — runs `python evals/run_evals.py --mode mock`
- [ ] Add `make evals-golden` target — runs `python evals/run_evals.py --mode golden` (scheduled / pre-release; not every PR)
- [ ] Run `make evals` → all mock evaluators pass → Langfuse shows scores
- [ ] Run `make evals-golden` once real keys exist (Phase 5) → golden accuracy passes

---

## Phase 5 — Real API Integration (plug and play)

> **Goal**: Replace all mock tool implementations with real API calls. Set `MOCK_EXTERNAL_APIS=false`. All 4 integration test cases pass with real data. Zero changes to agent code or graph.
> **Done when**: `MOCK_EXTERNAL_APIS=false` with real API keys → `"3 days Osaka from Kolkata"` returns a real itinerary with real flights, real hotels, and grounded destination context.

### P5-1 · Obtain API Keys
- [ ] Sign up for SerpAPI (free plan: 100 searches/month for testing) → add `SERPAPI_KEY` to `.env`
- [ ] Enable Google Maps Platform in GCP project → enable **Routes API**, Places API, Maps JS API, Distance Matrix API → create API key → add `GOOGLE_MAPS_KEY` to `.env`
- [ ] Sign up for Tavily (free: 1,000 calls/month) → add `TAVILY_KEY` to `.env`
- [ ] Sign up for an FX rate provider (e.g. exchangerate.host — free, or Open Exchange Rates) → add `FX_API_KEY` to `.env` **(H)**
- [ ] Set LLM key (`OPENAI_API_KEY` or equivalent) in `.env`

### P5-2 · Implement Real SerpAPI Tools
- [ ] `backend/app/tools/real/serpapi_tools.py` — `FlightSearchTool.run()`: call SerpAPI `google_flights` engine, parse response into `list[dict]` matching fixture schema
- [ ] `backend/app/tools/real/serpapi_tools.py` — `HotelSearchTool.run()`: call SerpAPI `google_hotels` engine, parse response into `list[dict]`
- [ ] Wrap both tools with `cache_service` (4h TTL for flights, 2h for hotels)
- [ ] Test: call `FlightSearchTool.run(origin="CCU", dest="IXL", date="2026-10-14")` → returns real flight data

### P5-3 · Implement Real Google Routes API Transit Tool
- [ ] `backend/app/tools/real/transit_tools.py` — `TransitSearchTool.run()`: call Google Routes API with `travelMode=TRANSIT`, parse `transitDetails[]` from each route leg
- [ ] Handle pagination and multiple route alternatives
- [ ] Wrap with cache (6h TTL)
- [ ] Test: `TransitSearchTool.run(origin="Kolkata", dest="New Delhi", mode="train")` → returns Rajdhani express as an option

### P5-4 · Implement Real Google Places Tools
- [ ] `backend/app/tools/real/places_tools.py` — `PlaceSearchTool.run()`: call Places Text Search API, return structured results
- [ ] `backend/app/tools/real/places_tools.py` — `PlaceDetailsTool.run()`: call Places Details API with `fields=name,rating,reviews,photos,opening_hours,website,geometry`
- [ ] Handle photo URL construction (Places photo reference → full URL)
- [ ] Wrap both with cache (48h TTL for details)
- [ ] Test: `PlaceSearchTool.run(query="tourist attractions", location="Osaka")` → returns real attractions with lat/lng

### P5-5 · Implement Real Tavily Tool
- [ ] `backend/app/tools/real/tavily_tools.py` — `TavilySearchTool.run()`: call Tavily search API, return top 3–5 results as structured text
- [ ] Wrap with cache (24h TTL keyed by query hash + dest + month)
- [ ] Test: `TavilySearchTool.run(query="tourist scams in Tokyo 2026")` → returns real results

### P5-6 · Implement Real Visa Tools
- [ ] `backend/app/tools/real/visa_tools.py` — `VisaCentreSearchTool.run()`:
  - Step 1: Tavily search `"visa application centre {destination_country} in {home_city}"` to discover which company handles this corridor (VFS Global, BLS International, TLScontact, iData, ACSIS, or consulate direct)
  - Step 2: Google Places search `"{discovered_company_name} {destination_country}", home_city` to get address, hours, phone, maps URL
  - Returns structured `VisaCentreInfo`: `company_name`, `address`, `phone`, `opening_hours`, `booking_url`, `google_maps_url`
- [ ] `backend/app/tools/real/visa_tools.py` — `EmbassySearchTool.run()`: Google Places Search `"{country} embassy OR consulate in {home_city}"`
- [ ] **(G)** both tools return grounding `sources[]` (URLs + fetched date), preferring official `.gov`/consulate domains, so `VisaAgent` can populate `VisaReport.sources`, `last_verified_at`, and `confidence`
- [ ] Wrap both with Tavily cache (24h TTL keyed by `from_country+to_country+home_city`)
- [ ] Test: `VisaCentreSearchTool.run(dest_country="Japan", home_city="Mumbai")` → returns VFS Global details (the actual company handling India→Japan)
- [ ] Test: `VisaCentreSearchTool.run(dest_country="Germany", home_city="Mumbai")` → returns VFS Global or TLScontact depending on current contract
- [ ] Test: `VisaCentreSearchTool.run(dest_country="Singapore", home_city="Mumbai")` → returns `None` (visa-free; no centre needed)
- [ ] Test (G): returned payload includes at least one official-domain source URL and a fetched date

### P5-7 · Implement Real Rental + Distance Matrix Tools
- [ ] `backend/app/tools/real/rental_tools.py` — `RentalSearchTool.run()`: Google Places `type=car_rental` search + Tavily for local operators
- [ ] `backend/app/tools/real/rental_tools.py` — `FuelPriceTool.run()`: Tavily search for current fuel price
- [ ] `backend/app/tools/real/geo_tools.py` — `DistanceMatrixTool.run()`: Google Distance Matrix API for total trip distance
- [ ] Test: `RentalSearchTool.run(destination="Goa")` → returns real rental shops

### P5-8 · Implement Real Hub Tool
- [ ] `backend/app/tools/real/hub_tools.py` — `IdentifyHubsTool.run()`: LLM call with geographic knowledge prompt → returns list of route combos
- [ ] Test: `IdentifyHubsTool.run(origin="Kolkata", dest="Leh")` → includes "via Delhi"

### P5-9 · Implement Real FX Tool **(H)**
- [ ] `backend/app/tools/real/fx_tools.py` — `CurrencyConvertTool.run()`: call the FX provider, return `{ amount_converted, rate, fetched_at }`
- [ ] Wrap with cache (12h TTL keyed by `{base}:{quote}`)
- [ ] Test: `CurrencyConvertTool.run(amount=10000, base="JPY", quote="INR")` → returns a plausible INR amount with a `rate` and `fetched_at`

### P5-10 · End-to-end Real Data Testing
- [ ] Set `MOCK_EXTERNAL_APIS=false` in `.env`
- [ ] Run integration test case 1: `"3 days Osaka from Kolkata, mid-October"` with real APIs → complete itinerary returned
- [ ] Run integration test case 2: `"5 days Tokyo from Mumbai"` → real visa info (with `sources[]` + `last_verified_at`), grounded destination context
- [ ] Run integration test case 3: `"Kolkata to Leh 4 days"` → real flight options, non-obvious insight
- [ ] Run `make evals` with real APIs on small dataset subset (5 cases) — verify scores hold
- [ ] Run `make evals-golden` **(J)** → visa/transit/opening-hours/FX match the human-verified `evals/golden/*` ground truth
- [ ] Run full Postman collection with real APIs — all tests pass

---

## Phase 6 — Hardening, Error Handling & Performance

> **Goal**: System handles failures gracefully. All fallback chains work. API rate limits handled. Response times acceptable. Ready for real users.
> **Done when**: Deliberately broken API keys for one service don't break the whole graph; P95 planning time < 30s.

### P6-1 · Graceful Degradation + Fallbacks
- [ ] `TransportSearchAgent`: if SerpAPI quota exceeded → fallback to `TavilySearchTool` with `"flights {origin} to {dest} {date} price"` → fallback to LLM-only estimation with disclaimer
- [ ] `StaySearchAgent`: if SerpAPI fails → fallback to Tavily `"hotels in {destination} {checkin} {checkout}"`
- [ ] `ReviewsAgent`: if Google Places returns no results → skip review synthesis, return empty `pros/cons` without failing
- [ ] `VisaAgent`: if application centre search returns no results → return visa info with `application_centre=None` and a note to contact the embassy directly; never fail the whole plan
- [ ] **(G)** `VisaAgent`: if no official-domain source can be grounded → set `confidence="low"` and surface the verify-directly warning rather than presenting unverified rules as fact
- [ ] **(H)** `BudgetPlannerAgent`: if the FX provider fails → fall back to the last cached rate (mark stale in `fx_disclaimer`); if no rate at all, present per-currency subtotals without a converted grand total rather than inventing a rate
- [ ] All agents: catch tool exceptions → log error → write `state["error"]` → continue graph (non-critical agents) or emit `agent_error` SSE event

### P6-2 · API Rate Limiting Protection
- [ ] Add exponential backoff + jitter wrapper around all real tool HTTP calls
- [ ] Add per-session SerpAPI call counter in Redis — block if > 10 calls in single planning run
- [ ] Add global API budget tracker: if daily spend > `LLM_BUDGET_PER_TRIP_USD × 100`, emit warning log
- [ ] Test: set `SERPAPI_KEY=invalid` → graph completes with Tavily fallback data, SSE shows `agent_done` not `agent_error` for most agents

### P6-3 · Input Validation + Security
- [ ] OrchestratorAgent: sanitize `query` input — strip HTML, limit to 500 chars, reject obvious prompt injection patterns
- [ ] All endpoints: validate `session_id` is a valid UUID format
- [ ] Rate limit `POST /api/trip/plan` — max 5 requests per `session_id` per hour (Redis counter)
- [ ] Test: send `<script>alert(1)</script>` as query → sanitized, no XSS in output

### P6-4 · Performance Optimisation
- [ ] Profile full graph run with real APIs: identify slowest agents
- [ ] Verify Layer 1 + Layer 2 are running truly in parallel (use `asyncio.gather` properly in graph)
- [ ] Verify Layer 4 agents are parallel (not sequential)
- [ ] Cache warming: pre-cache popular destination data (top 20 cities) on deploy
- [ ] Measure P95 planning time across 10 runs — target < 30s. Document actual baseline.

### P6-5 · Logging & Error Monitoring
- [ ] Verify every agent logs `agent_completed` or `agent_failed` with `duration_ms`
- [ ] Verify `trace_id` from OTel appears in every log line
- [ ] Add Prometheus alert rules to `infra/alerts.yaml` (P95 > 30s, error rate > 5%, cost > $10/day)
- [ ] Test: trigger an intentional agent error → verify it appears in Prometheus `agent_error_total` and in Langfuse as a failed trace

---

## Phase 7 — Frontend

> **Goal**: Full Next.js frontend connected to all backend endpoints. Every UI component from plan implemented. End-to-end user journey works in browser.
> **Done when**: A user can type a trip query, watch agents progress, view the full itinerary with maps + photos + embedded links, download PDF.

### P7-1 · Next.js Setup
- [ ] Scaffold Next.js 14 App Router in `frontend/` — `npx create-next-app@latest`
- [ ] Install: `tailwindcss`, `shadcn/ui` (init), `@googlemaps/react-wrapper`, `@dnd-kit/sortable`, `embla-carousel-react`
- [ ] Create `frontend/src/types/index.ts` — TypeScript types matching all backend Pydantic models (auto-generate from `openapi.json` if possible)
- [ ] Create `frontend/src/lib/api.ts` — typed fetch client for all backend endpoints
- [ ] Create `frontend/src/lib/sse.ts` — `useAgentStream(sessionId)` hook consuming SSE

### P7-2 · Chat-first Landing Page
- [ ] `frontend/src/app/page.tsx` — single chat input, session UUID in localStorage, community itineraries background
- [ ] `frontend/src/components/PreferenceSetup.tsx` — 5-question overlay triggered after first message

### P7-3 · Agent Progress Feed
- [ ] `frontend/src/components/AgentProgressFeed.tsx` — SSE timeline grouped by layer with icons and status; `PlanningCostBadge` at end
- [ ] `frontend/src/components/ClarificationPrompt.tsx` **(F)** — on `needs_clarification`, pause the feed and render `clarification_prompts[]`; collect answers; merge into the query and re-POST `/api/trip/plan`

### P7-4 · Route Map
- [ ] `frontend/src/lib/mapUtils.ts` — great-circle arc helper, polyline colour by mode, numbered marker factory
- [ ] `frontend/src/components/RouteMap.tsx` — Google Maps JS API, flight arcs + train/bus polylines + numbered markers

### P7-5 · Itinerary View
- [ ] `frontend/src/app/itinerary/[id]/page.tsx` — fetch itinerary, render all panels
- [ ] `frontend/src/components/TripConditionsPanel.tsx` — season badge, crowd level, weather summary, hidden fees (no score or verdict)
- [ ] `frontend/src/components/ItineraryView.tsx` — day tabs, `@dnd-kit/sortable` reorder → PUT endpoint on drop
- [ ] `frontend/src/components/DayCard.tsx` — ISO date header, weather icon, mini-map thumbnail, time slots, inline chat

### P7-6 · Place, Stay, Transport Cards
- [ ] `frontend/src/components/PlaceCard.tsx` — photo carousel, geotag chip, rating, pros/cons, embedded links, `personalization_reason` annotation
- [ ] `frontend/src/components/StayOptionsPanel.tsx` — full shortlist of budget-filtered stays with recommended badge, `personalization_reason`, `price_disclaimer` per card, photos, pros/cons
- [ ] `frontend/src/components/TransportOptionsPanel.tsx` — recommended route + 2 alternatives with `personalization_reason`, `price_disclaimer` per leg, booking links, insight callout
- [ ] `frontend/src/components/TransportLegCard.tsx` — per-leg detail used inside TransportOptionsPanel
- [ ] `frontend/src/components/RestaurantCard.tsx` — per-meal per-day, cuisine, links
- [ ] Verify: with `budget_tier="budget"`, StayOptionsPanel shows zero luxury properties; TransportOptionsPanel shows zero premium-class options

### P7-7 · Info Panels
- [ ] `frontend/src/components/BudgetBreakdownPanel.tsx` — table, progress bar, verdict badge, tips; for international trips show destination + home-currency totals with `fx_disclaimer` and FX `fetched_at` **(H)**
- [ ] `frontend/src/components/PackingPanel.tsx` — categorised checklist, tick-off state in localStorage
- [ ] `frontend/src/components/VisaPanel.tsx` — type badge, process, embassy + application centre cards (label is dynamic — not hardcoded as "VFS"); render `sources[]` links, a "Checked on {last_verified_at}" stamp, the confirm-with-consulate disclaimer, and a prominent warning when `confidence="low"` **(G)**
- [ ] `frontend/src/components/SelfDrivePanel.tsx` — rental cards, fuel calculator widget
- [ ] `frontend/src/components/ScamSafetyPanel.tsx` — advisory badge, scam list, emergency contacts

### P7-8 · PDF + Share
- [ ] PDF download button → `POST /api/trip/{id}/pdf` → browser download
- [ ] Share button → `PATCH /api/trip/{id}` sets `public=true` → copy `app.domain/i/{slug}` to clipboard
- [ ] `frontend/src/app/i/[slug]/page.tsx` — public itinerary page (no auth)

### P7-9 · End-to-end Browser Test
- [ ] Manual test: full user journey in browser — type query → watch SSE progress → view itinerary → download PDF → share link
- [ ] Manual test (F): a vague query ("trip to Tokyo") → ClarificationPrompt appears asking for dates + travellers → answering resumes planning to a full itinerary
- [ ] Verify (G): VisaPanel shows sources, "Checked on {date}", and the confirm-with-consulate disclaimer; a low-confidence case shows the verify-directly warning
- [ ] Verify (H): for an international trip, BudgetBreakdownPanel shows destination + home-currency totals with the FX disclaimer and rate date
- [ ] Verify RouteMap renders with polylines and markers
- [ ] Verify DayCard mini-map loads for each day
- [ ] Verify photo carousels load for places and hotels
- [ ] Verify all embedded links (Google Maps, YouTube, IRCTC etc.) open correct URLs

---

## Phase 8 — GCP Production Deployment

> **Goal**: App running on Google Cloud Run, accessible via public URL. All infra provisioned by Terraform. Secrets in Secret Manager. CI/CD pipeline triggers on push.
> **Done when**: `terraform apply` succeeds; public URL returns the app; Cloud Build triggers on git push.

### P8-1 · Terraform Infra
- [ ] Write `infra/cloud_run.tf` — backend, frontend, PDF service Cloud Run definitions
- [ ] Write `infra/cloud_sql.tf` — PostgreSQL 15 instance, db, user, IAM binding
- [ ] Write `infra/memorystore.tf` — Redis 7 instance, VPC peering
- [ ] Write `infra/variables.tf` — `project_id`, `region`, `environment`, `db_tier`
- [ ] Write `infra/artifact_registry.tf` — Docker image repository
- [ ] Run `terraform plan` → review; `terraform apply` → provision all resources in `dev` workspace

### P8-2 · Secret Manager
- [ ] Store all API keys in Secret Manager: `SERPAPI_KEY`, `GOOGLE_MAPS_KEY`, `TAVILY_KEY`, `FX_API_KEY`, `LANGFUSE_SECRET_KEY`, `DATABASE_URL`, LLM key
- [ ] Update Cloud Run service definitions to inject secrets via `--set-secrets`
- [ ] Verify Cloud Run service starts with injected secrets (no secrets in container image)

### P8-3 · Cloud Build CI/CD
- [ ] Write `cloudbuild.yaml` with steps: `pytest` → `make evals` (mock-mode, subset, 10 cases) → `docker build` → `docker push` → `gcloud run deploy` (blue/green)
- [ ] Add a **scheduled** Cloud Build trigger (not per-PR) running `make evals-golden` **(J)** against real APIs — fails the pipeline / alerts if visa/transit/opening-hours/FX accuracy regresses vs `evals/golden/*`
- [ ] Connect Cloud Build to GitHub repo trigger (push to `main` branch)
- [ ] Run first automated deploy → verify Cloud Run service updates

### P8-4 · Production Observability
- [ ] Set `OTEL_EXPORTER_OTLP_ENDPOINT` to Cloud Trace OTLP endpoint in Secret Manager
- [ ] Set `LANGFUSE_HOST=https://cloud.langfuse.com` in prod (or deploy self-hosted Langfuse to Cloud Run)
- [ ] Create Cloud Monitoring dashboard with all Prometheus metrics
- [ ] Set up alert policies: P95 latency > 30s, error rate > 5%, daily LLM cost > $10
- [ ] Verify first production trip planning run appears in Cloud Trace and Langfuse

---

## Phase Checklist Summary

| Phase | Goal | Key Artifact |
|---|---|---|
| **0** | Scaffolding | `docker-compose up` → all services green |
| **1** | Models + mock tools | All tools work in mock mode; fixtures ready |
| **2** | All 14 agents + graph | Full graph runs end-to-end with mock data |
| **3** | FastAPI endpoints | Postman collection passes all requests |
| **4** | Observability + evals | Langfuse traces visible; `make evals` exits 0 |
| **5** | Real API integration | Real data flows through system; evals still pass |
| **6** | Hardening | Fallbacks work; P95 < 30s; rate limits protect |
| **7** | Frontend | Full browser UX works end-to-end |
| **8** | GCP production | Live on public URL; CI/CD automated |

---

## Definition of Done (per task)

- Code reviewed (self-review checklist: no hardcoded values, no secrets in code, Pydantic types used, async everywhere)
- Unit test written and passing
- No new `# TODO` comments left in code
- Relevant fixture or postman test updated if applicable