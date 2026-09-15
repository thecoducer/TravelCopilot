# TravelCopilot Agent Guide

This file is the fast orientation guide for coding agents working in this repository. Read it before exploring broadly. The root `README.md` contains user-facing setup instructions; this file contains implementation context and routing rules.

## Project purpose

TravelCopilot is a chat-first, multi-agent trip planner. A user query is parsed into structured trip requirements, searched/enriched through LangGraph agents, and compiled into a route-aware itinerary. The backend is FastAPI + LangGraph + Pydantic. The frontend is Next.js + React. LiteLLM keeps model-provider selection configurable.

The development strategy is mock-first. `MOCK_EXTERNAL_APIS=true` selects mock or replay-backed tool adapters so tests and local development do not call paid travel APIs. Real adapters live beside the mocks and are enabled/configured separately.

## First files to read

1. `README.md` for setup, ports, and commands.
2. `Makefile` for the canonical development and validation commands.
3. `plan.md` for the intended graph, agent layers, state flow, and design decisions.
4. `dev-roadmap.md` for phase status and planned work.
5. The relevant module below, then its nearest tests.

For frontend work, also read `frontend/AGENTS.md`. It contains generated Next.js-specific guidance. `frontend/CLAUDE.md` points back to it.

## Repository map

```text
backend/
  app/
    main.py                 FastAPI app, lifespan, health, metrics, routers
    config.py               Pydantic settings and shared runtime constants
    db.py                   Async SQLAlchemy engine/session setup
    migrations.py           Startup migration runner
    llm.py                  LiteLLM/provider initialization and usage hooks
    checkpointer.py         LangGraph PostgreSQL checkpointer lifecycle
    agents/                 Agent nodes; each owns one planning responsibility
    graph/state.py           TypedDict graph state contract
    graph/graph.py           LangGraph construction and execution entry points
    models/                 Pydantic domain and API models
    routers/                HTTP endpoints (`trip.py`, `user.py`)
    services/               Orchestration, streaming, cache, PDF, FX, and user services
    tools/base.py            Base tool protocol and shared tool contracts
    tools/factory.py         Mock/real adapter selection
    tools/mock/              Deterministic fixtures and replay-friendly tools
    tools/real/              Provider integrations and pure implementations
  migrations/                Numbered SQL migrations
  tests/unit/                 Focused unit tests
  tests/integration/         Graph and service integration tests
  tests/test_smoke.py        Basic application/config smoke coverage
  tool_responses/             Local recorded responses; ignored by Git
frontend/
  src/app/                   Next.js routes and app-level UI
  src/components/            Reusable React components
  src/hooks/                 Client-side hooks
  src/lib/                   API clients and shared frontend utilities
  public/                    Static assets
specs/                        Detailed product and integration specifications
infra/                        Deployment/infrastructure material
```

## Runtime architecture

The graph is the backend's controlling abstraction. At a high level:

- `OrchestratorAgent` parses the natural-language request, loads profile context, and handles clarification requirements.
- `StopsDiscoveryAgent` shapes a provisional single- or multi-stop route before downstream searches.
- `VisaAgent` runs for international trips.
- Transport, stay, and local-experience search agents call tools and write raw supply data to state.
- Analysis agents optimize transport, evaluate stays, handle self-drive requests, and plan the budget.
- Enrichment agents cover food, reviews, safety, and destination realities.
- `ItineraryCompilerAgent` synthesizes and validates the final itinerary.

Consult `plan.md` before changing graph edges, state keys, clarification interrupts, or agent ordering. Route-aware fields such as stops, route legs, and per-stop/per-leg results must remain compatible with the simple one-destination flow.

## Important contracts

### Configuration

- Settings are loaded from the root `.env` through `backend/app/config.py`.
- `.env.example` is the shareable configuration template; `.env` is local-only.
- `MOCK_EXTERNAL_APIS` controls the `ToolFactory` mode.
- Do not hardcode provider credentials, URLs, budgets, or policy thresholds in agents. Add configurable values to settings or the appropriate constants section.

### Tools

Agents should depend on the `BaseTool` contract and receive tools through the factory. Do not import provider-specific adapters directly into an agent. Keep mock and real implementations behaviorally compatible, including result shapes and error/fallback behavior.

When adding a tool:

1. Define or update the shared contract.
2. Add the mock/replay implementation.
3. Add the real adapter or an explicit stub if the integration is not ready.
4. Register it in `ToolFactory`.
5. Add focused unit tests and fixtures.

### Graph state and models

Use typed state fields and Pydantic models at agent boundaries. Preserve existing state keys for backward compatibility when adding route-aware fields. Avoid passing unvalidated free-form dictionaries between agents unless the surrounding contract explicitly requires it.

### API and streaming

HTTP routes live in `backend/app/routers/`. Trip execution and streaming behavior is delegated to services, especially `trip_service.py`, `chat_turn_service.py`, and `trip_stream_service.py`. Keep transport concerns in routers and planning behavior in services/agents.

The app exposes `/health`, `/ready`, and `/metrics`; Swagger is available at `/docs` when the backend is running.

## Local commands

From the repository root:

```bash
make dev                 # Build and start the full Docker Compose stack
make dev-down            # Stop the stack
make dev-logs            # Follow backend/frontend logs
make test                # Backend tests with coverage
make lint                # Ruff and mypy
make frontend-test       # Vitest
make frontend-lint       # ESLint
make frontend-typecheck  # TypeScript check
make verify              # Full validation and artifact build
```

Backend-only commands use `uv`:

```bash
cd backend
uv sync --all-groups
uv run pytest tests/ -v
uv run ruff check app/ tests/
uv run mypy app/
```

Frontend-only commands use npm:

```bash
cd frontend
npm install
npm run dev       # Port 3001
npm run test
npm run lint
npm run typecheck
npm run build
```

The Compose backend applies migrations during startup. `make migrate` is available for explicitly applying the numbered SQL migrations against the local PostgreSQL container.

## Change guidance

- Make the smallest change at the layer that owns the behavior.
- Read the nearest implementation and neighboring test before editing.
- Preserve async boundaries and dependency injection patterns.
- Prefer structured logging through the existing `structlog` setup.
- Do not introduce real network calls into default tests or mock mode.
- Avoid changing generated files, caches, `.env`, `node_modules`, `.next`, or recorded tool responses unless the task explicitly requires it.
- Keep Python compatible with 3.12, follow Ruff's configured line length of 100, and run focused tests after edits.
- For frontend changes, follow existing Next.js conventions and the instructions in `frontend/AGENTS.md`.
- Do not commit changes unless explicitly requested.

## Validation routing

- Agent/model/state change: run the nearest backend unit tests, then `make lint` when practical.
- Graph or service integration change: run the relevant integration test and inspect logs for startup/migration issues.
- Router/API change: run its tests and verify the route through `/docs` or a focused HTTP test.
- Frontend component/hook change: run the relevant Vitest test plus `npm run lint` and `npm run typecheck` when practical.
- Cross-stack change: use `make verify` if dependencies and Docker resources are available.

## Common pitfalls

- Host PostgreSQL uses port `5433`; containers use the internal PostgreSQL port `5432`.
- The browser reaches the backend at `http://localhost:8000`, while containers reach it through Compose service names.
- The frontend is exposed on host port `3001`; its container listens on port `3000`.
- Langfuse is exposed on port `3000`, so it must not be confused with the frontend host port.
- Keep `MOCK_EXTERNAL_APIS=true` while developing unless real provider credentials are intentionally configured.
- A failing `/ready` response can be expected when real provider credentials are absent; `/health` is the basic local liveness check.
- Startup migrations are intentionally best-effort and logged. Check backend logs if database-backed features do not work.
