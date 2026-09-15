# TravelCopilot

TravelCopilot is a chat-first, multi-agent AI trip planner. It turns a natural-language travel request into a route-aware itinerary with transport, stays, local experiences, food, safety, visa, and budget guidance.

The repository contains a FastAPI/LangGraph backend and a Next.js frontend. Travel data providers and LLM providers are configured through environment variables.

## Example trip request

A user could ask:

> Plan a 7-day trip from Mumbai to Japan for two people in October. We enjoy local food, scenic neighborhoods, and relaxed sightseeing, with a mid-range budget. Include visa information and avoid overly packed days.

TravelCopilot can find and organize:

- Route options, flights, trains, buses, and local transport
- Hotels and stays matched to budget and preferences
- Attractions, neighborhoods, activities, and local experiences
- Restaurants, cafes, cuisine options, and dietary considerations
- Visa requirements, application steps, fees, and application centers for international trips
- Weather, seasonal conditions, packing suggestions, and destination realities
- Safety guidance, common scams, crowd considerations, and venue or area risks
- Budget estimates, currency conversion, cost breakdowns, and savings suggestions
- A day-by-day itinerary that balances travel time, activities, meals, and rest

## What runs locally

| Service | URL | Purpose |
| --- | --- | --- |
| Frontend | http://localhost:3001 | Next.js travel-planning UI |
| Backend API | http://localhost:8000 | FastAPI application |
| API docs | http://localhost:8000/docs | Swagger UI |
| API schema | http://localhost:8000/openapi.json | OpenAPI JSON |
| Health check | http://localhost:8000/health | Backend liveness check |
| Langfuse | http://localhost:3000 | Local LLM tracing and evaluations |
| PostgreSQL | localhost:5433 | Application database |
| Redis | localhost:6379 | Cache and runtime state |

## Prerequisites

### Required for the Docker workflow

- Git: [git-scm.com/downloads](https://git-scm.com/downloads)
- A Docker-compatible runtime with Docker Compose:
  - [Docker Desktop](https://docs.docker.com/desktop/), or
  - [OrbStack](https://orbstack.dev/) on macOS. OrbStack is a lighter Docker-compatible alternative and exposes the usual `docker` and `docker compose` commands.

Docker Desktop is convenient but can use substantial memory and disk space. OrbStack is a good macOS choice for this project; after installing it, verify that `docker version` and `docker compose version` work in a new terminal.

The Docker workflow builds Python and Node environments inside containers. You do not need a host Python or Node installation just to start the complete stack.

### Recommended for local checks and faster iteration

- Python 3.12: [python.org/downloads](https://www.python.org/downloads/) or [pyenv](https://github.com/pyenv/pyenv)
- Node.js 20 or newer, which includes npm: [nodejs.org](https://nodejs.org/) or [nvm](https://github.com/nvm-sh/nvm)
- `uv`, the Python environment and package manager used by the Makefile: [docs.astral.sh/uv](https://docs.astral.sh/uv/)
- GNU Make, normally available on macOS through the Xcode Command Line Tools:

  ```bash
  xcode-select --install
  ```

Suggested macOS setup with Homebrew:

```bash
brew install python@3.12 node make
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Restart the terminal after installing `uv`, then verify the tools:

```bash
git --version
docker version
docker compose version
python3 --version
node --version
npm --version
uv --version
make --version
```

## Install the project

Clone the repository and enter its directory:

```bash
git clone <repository-url>
cd TravelCopilot
```

Create the local environment file. The command does not overwrite an existing `.env`:

```bash
cp .env.example .env
```

Configure the provider settings in `.env` before starting the application:

```dotenv
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o
MOCK_EXTERNAL_APIS=false
```

Install frontend dependencies only if you plan to run frontend commands on the host:

```bash
make frontend-install
```

Install and lock backend dependencies only if you plan to run backend commands on the host:

```bash
cd backend
uv sync --all-groups
cd ..
```

## Configure live travel APIs

The backend uses third-party providers for search, places, routing, and currency data. Create accounts, enable the required services, add billing where the provider requires it, and then place the resulting keys in `.env`. Never commit `.env` or expose these keys in frontend code.

### SerpApi: flights and hotels

1. Create an account at [SerpApi](https://serpapi.com/users/sign_up).
2. Open the [SerpApi dashboard](https://serpapi.com/dashboard) and copy your private API key.
3. Review [SerpApi pricing and plans](https://serpapi.com/pricing) and add a paid plan if the free quota is not enough.
4. Set the key in `.env`:

  ```dotenv
  SERPAPI_KEY=your_serpapi_key
  ```

TravelCopilot uses SerpApi for flight and hotel searches. The endpoint is configured by `SERPAPI_SEARCH_URL`.

### Tavily: web research and destination intelligence

1. Create an account at [Tavily](https://app.tavily.com/sign-in).
2. In the Tavily dashboard, create or copy an API key. See the [Tavily API documentation](https://docs.tavily.com/documentation/api-credits) for credits and usage.
3. Add a paid plan or credits when the included quota is insufficient.
4. Set the key in `.env`:

  ```dotenv
  TAVILY_API_KEY=your_tavily_key
  ```

TravelCopilot uses Tavily for destination research, visa-centre research, safety information, and other web-grounded results. The endpoint is configured by `TAVILY_SEARCH_URL`.

### Google Cloud: Places, routes, and geocoding

1. Sign in to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create or select a Google Cloud project from the project picker.
3. Attach a billing account. Review [Google Maps Platform pricing](https://mapsplatform.google.com/pricing/) and set [budget alerts](https://cloud.google.com/billing/docs/how-to/budgets).
4. Enable these APIs from **APIs & Services > Library**:
  - [Places API (New)](https://console.cloud.google.com/marketplace/product/google/places.googleapis.com)
  - [Routes API](https://console.cloud.google.com/marketplace/product/google/routes.googleapis.com)
  - [Geocoding API](https://console.cloud.google.com/marketplace/product/google/geocoding-backend.googleapis.com)
5. Open **APIs & Services > Credentials**, choose **Create credentials > API key**, and restrict the key to the APIs above. See [Google API key best practices](https://cloud.google.com/docs/authentication/api-keys).
6. Set the key in `.env`:

  ```dotenv
  GOOGLE_CLOUD_API_KEY=your_google_cloud_api_key
  ```

The project-specific Google endpoints are already listed in `.env.example` as `GOOGLE_PLACES_SEARCH_URL`, `GOOGLE_PLACES_DETAILS_URL`, `GOOGLE_ROUTES_URL`, `GOOGLE_ROUTE_MATRIX_URL`, and `GOOGLE_GEOCODE_URL`.

### Currency exchange

Budget conversion uses Open Exchange Rates when configured. Create an account at [Open Exchange Rates](https://openexchangerates.org/signup), choose a plan from its [pricing page](https://openexchangerates.org/), and set:

```dotenv
FX_API_KEY=your_open_exchange_rates_app_id
```

This provider is optional if the selected flow does not require live currency conversion.

## Configure an LLM provider

TravelCopilot uses LiteLLM so the provider and model can be changed through `LLM_PROVIDER` and `LLM_MODEL`. Choose one provider, create an account, add billing or credits according to that provider's terms, create an API key, and add only the matching key to `.env`.

| Provider | `LLM_PROVIDER` | Account, billing, and key links | Key variable |
| --- | --- | --- | --- |
| OpenAI | `openai` | [Platform](https://platform.openai.com/), [billing](https://platform.openai.com/settings/organization/billing/overview), [API keys](https://platform.openai.com/api-keys) | `OPENAI_API_KEY` |
| Anthropic Claude | `anthropic` | [Console](https://console.anthropic.com/), [billing](https://console.anthropic.com/settings/billing), [API keys](https://console.anthropic.com/settings/keys) | `ANTHROPIC_API_KEY` |
| Google Gemini | `gemini` | [Google AI Studio](https://aistudio.google.com/), [API keys](https://aistudio.google.com/app/apikey), [Gemini API billing](https://ai.google.dev/gemini-api/docs/billing) | `GOOGLE_API_KEY` |
| Groq | `groq` | [Groq Console](https://console.groq.com/), [API keys](https://console.groq.com/keys), [billing](https://console.groq.com/settings/billing) | `GROQ_API_KEY` |
| OpenRouter | `openrouter` | [OpenRouter](https://openrouter.ai/), [credits](https://openrouter.ai/credits), [API keys](https://openrouter.ai/settings/keys) | `OPENROUTER_API_KEY` |

Example using OpenAI:

```dotenv
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o
OPENAI_API_KEY=your_openai_api_key
```

Example using Anthropic:

```dotenv
LLM_PROVIDER=anthropic
LLM_MODEL=claude-3-5-sonnet-20241022
ANTHROPIC_API_KEY=your_anthropic_api_key
```

Model names and availability change over time. Use each provider's current model catalogue and pricing page when selecting a model. For a local model without a hosted API bill, [Ollama](https://ollama.com/) can be used when the selected LiteLLM integration and local model are available:

```dotenv
LLM_PROVIDER=ollama
LLM_MODEL=llama3
LLM_API_BASE=http://host.docker.internal:11434
```

## Enable live services

After creating the keys above, update `.env` with the travel providers and exactly one LLM provider. Then set:

```dotenv
MOCK_EXTERNAL_APIS=false
```

## Run the complete project

Start PostgreSQL, Redis, Langfuse, the backend, and the frontend:

```bash
make dev
```

The first run downloads base images and builds both application images, so it can take a few minutes. The backend applies database migrations during startup. The frontend is then available at:

**http://localhost:3001**

Open the backend API documentation at **http://localhost:8000/docs** and confirm that **http://localhost:8000/health** returns a JSON response with `"status": "ok"`.

Stop the stack with `Ctrl+C`, or from another terminal run:

```bash
make dev-down
```

Useful operational commands:

```bash
make dev-logs       # Follow backend and frontend logs
make help           # List available Make targets
docker compose ps   # Show container status
docker compose logs backend
```

### Run services separately

For frontend-only development after the backend stack is running:

```bash
make frontend-dev
```

This also serves the UI at **http://localhost:3001**.

For a host-side backend development server:

```bash
cd backend
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Keep PostgreSQL and Redis running through Docker when using this mode. The host backend reads the root `.env`, where the database uses port `5433`.

## Tests, linting, and builds

The Makefile is the canonical command reference:

```bash
make test             # Backend tests
make lint             # Backend Ruff + mypy checks
make format           # Format backend code
make frontend-test    # Frontend Vitest tests
make frontend-lint    # Frontend ESLint checks
make frontend-typecheck
make frontend-build
make verify           # Full format, lint, test, and build pipeline
```

`make verify` can modify backend formatting and apply automatic lint fixes. Run it on a clean working tree or inspect the diff afterward.

## Configuration and API modes

- `.env.example` documents all local settings. Never commit `.env` or API keys.
- `MOCK_EXTERNAL_APIS=false` selects live provider adapters. Set it in `.env` after configuring the required credentials.
- `MOCK_EXTERNAL_APIS=true` selects recorded-response tools when you need a provider-free development or test run.
- The LLM is selected with `LLM_PROVIDER` and `LLM_MODEL`; the supported provider examples are listed in `.env.example` and `backend/app/config.py`.
- Langfuse is local and is exposed on port `3000`. Its credentials and host settings are configured in `.env`.

## Repository layout

```text
backend/
  app/
    agents/       LangGraph agent implementations
    graph/        TripState and graph construction
    models/       Pydantic request, report, and itinerary models
    routers/      FastAPI route modules
    services/     Application services and integrations
    tools/        Base tool protocol, factory, mocks, and real adapters
  migrations/     SQL schema migrations
  tests/          Unit, integration, and smoke tests
frontend/
  src/app/        Next.js routes and pages
  src/components/ Reusable UI components
  src/hooks/      React hooks
  src/lib/        Frontend API and utility modules
specs/            Detailed behavior and production integration specs
infra/            Infrastructure and deployment configuration
Makefile          Canonical development, test, lint, and build commands
plan.md           System architecture and agent graph design

dev-roadmap.md    Phase-by-phase implementation roadmap
```

## Troubleshooting

### Port already in use

Stop the process using the port, or stop the existing Compose stack:

```bash
docker compose down
docker compose ps
```

The expected host ports are `3001` for the frontend, `8000` for the backend, `3000` for Langfuse, `5433` for PostgreSQL, and `6379` for Redis.

### Containers do not become healthy

Check service logs and status:

```bash
docker compose ps
docker compose logs --tail=100 postgres redis backend
```

If you intentionally need a completely fresh local database, remove the Compose volumes. This deletes local PostgreSQL and Redis data:

```bash
docker compose down -v
```

Then run `make dev` again.

### Docker runtime is out of resources

Reduce the memory/CPU allocation in Docker Desktop, or try OrbStack on macOS. Also remove unused images and volumes only when you understand the impact:

```bash
docker system df
docker image prune
```

## Further reading

- [System design plan](plan.md)
- [Development roadmap](dev-roadmap.md)
- [Production real-tool integration spec](specs/production-real-tool-integration-spec.md)
- [Stops discovery agent spec](specs/stops-discovery-agent-spec.md)
- [API cost governance and multi-stop guardrails](specs/api-cost-governance-and-multi-stop-guardrails-spec.md)
- [Agent orientation guide](AGENTS.md)

## Disclaimer

Third-party API charges and quota usage are controlled by the provider accounts, not by Docker or TravelCopilot.
