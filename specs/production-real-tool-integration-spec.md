# Production Real Tool Integration Specification

> Created: 2026-09-13
> Status: Proposed
> Scope: Real provider adapters, response recording and replay, resilient HTTP execution, agent grounding, and manual verification

## Objective

Implement the currently required live provider adapters behind the existing
`BaseTool` and `ToolFactory` boundary, with one shared asynchronous HTTP layer for
connection pooling, bounded concurrency, retries, redaction, metrics, and raw
response capture.

Real calls must produce the same normalized dictionaries as mock calls. Mock mode
must replay the newest successful recording matching a canonical request fingerprint,
then fall back to the existing curated fixtures. Raw archives remain gitignored, are
retained for 30 days, and are disabled by default in production.

## Goals

- Make real tools usable by setting provider API keys and
  `MOCK_EXTERNAL_APIS=false`, without agent-specific configuration changes.
- Preserve the existing tool contracts consumed by agents.
- Capture every logical tool invocation in a separate JSON file when recording is
  enabled.
- Store recordings in separate per-tool directories with collision-safe filenames.
- Replay exact request matches in mock mode without making network calls.
- Prevent secrets and sensitive headers from entering response recordings.
- Provide bounded retries and truthful partial failures without silently substituting
  mock data in real mode.
- Ground attraction, route, visa, rental, and self-drive results in external sources.

## Non-Goals

- Transactional flight or hotel booking.
- A dedicated weather provider or weather agent. `SafetyAgent` currently obtains
  seasonal risk information through Tavily.
- Treating the raw response archive as a production cache.
- Silently falling back to LLM-generated facts when a critical provider lookup fails.
- Adding provider SDKs when the existing `httpx` dependency can provide a uniform,
  testable REST integration layer.
- Writing or updating unit, integration, contract, smoke, or end-to-end tests in this
  implementation. Automated test coverage is explicitly deferred.

## Provider Matrix

| Capability | Provider | Logical tools |
| --- | --- | --- |
| Airport and city resolution | SerpAPI Google Flights Autocomplete | `search_flights` internal step |
| Flight discovery and pricing snapshots | SerpAPI Google Flights | `search_flights` |
| Hotel discovery and pricing snapshots | SerpAPI Google Hotels | `search_hotels` |
| Web grounding and current-source research | Tavily Search | `tavily_search`, `visa_centre_search`, `rental_search`, `fuel_price` |
| Place search, details, reviews, and offices | Google Places API (New) | `search_places`, `place_details`, `search_taxi_info`, `visa_centre_search`, `embassy_search`, `rental_search` |
| Transit and road routes | Google Routes API v2 | `search_transit`, `search_road_routes` |
| Route distance matrix | Google Routes API v2 | `distance_matrix` |
| Forward geocoding | Google Geocoding API v4 | `geocode` |
| Currency conversion | Open Exchange Rates | `currency_convert` |
| Local deterministic computation | Application code | `cluster_by_proximity`, `enforce_opening_hours`, `validate_day_duration` |

## Core Decisions

- `MOCK_EXTERNAL_APIS` remains the single real/mock mode switch. No mock data is
  silently used in real mode.
- Raw request and response archives are gitignored, capture is independently
  configurable, capture defaults off in production, and retention is 30 days.
- Mock selection uses a canonical request fingerprint and the newest successful exact
  match, then the existing curated fixture fallback.
- Provider errors degrade to typed partial results after bounded retries.
- Existing agent-facing payload keys remain stable. Shared metadata is added under a
  reserved `_meta` key.
- Use the existing `httpx` dependency instead of provider SDKs so pooling, testing,
  redaction, recording, and replay work consistently across providers.
- Google Places and Routes content is subject to caching and attribution restrictions.
  Place IDs are explicitly exempt. The raw archive is a local debugging and fixture
  capture facility, not an approved production cache, and requires terms review before
  live retention or replay.
- SerpAPI results are discovery and pricing snapshots, not booking guarantees.
- If transactional booking becomes a requirement, evaluate GDS or OTA partners such as
  Duffel or Amadeus for flights and contracted hotel inventory providers separately.

## Phase 1: Contracts, Configuration, and Storage

### 1. Stable Tool Results

Define stable tool-result metadata without breaking existing agent payloads. Each tool
retains its current required keys, including `properties`, `best_flights`, `results`,
and `options`, and adds a reserved `_meta` object containing:

- `status`: `success`, `partial`, or `error`
- `provider`
- `fetched_at`
- `request_fingerprint`
- cache and replay status
- retry count and duration
- a sanitized typed error when degraded

Add shared result and error helpers so exhausted calls return the tool-specific empty
shape instead of raising or silently serving mock data.

### 2. Environment Configuration

Extend `Settings` and `.env.example` with explicit response-capture and transport
controls:

```dotenv
# Real/mock tool selection
MOCK_EXTERNAL_APIS=true

# Local response capture and replay
TOOL_RESPONSE_RECORDING_ENABLED=false
TOOL_RESPONSE_DIR=backend/tool_responses
TOOL_RESPONSE_RETENTION_DAYS=30

# Shared HTTP behavior
EXTERNAL_API_CONNECT_TIMEOUT_SECONDS=5
EXTERNAL_API_READ_TIMEOUT_SECONDS=20
EXTERNAL_API_WRITE_TIMEOUT_SECONDS=10
EXTERNAL_API_POOL_TIMEOUT_SECONDS=5
EXTERNAL_API_MAX_RETRIES=3

# Provider credentials
SERPAPI_KEY=
TAVILY_API_KEY=
GOOGLE_MAPS_API_KEY=
GOOGLE_PLACES_API_KEY=
FX_API_KEY=
```

Add configurable per-provider concurrency limits. Real mode requires the credentials
needed by enabled tools, while mock mode starts without external credentials. Recording
is independent of real/mock selection and defaults off in production.

### 3. Archive Location

Add `backend/tool_responses/` to `.gitignore`. Resolve the configured path from the
repository root and reject paths outside the repository unless explicitly allowed.

The required directory structure is:

```text
backend/tool_responses/
├── search_flights/
│   └── search_flights-20260913T142301.123456Z.json
├── search_hotels/
│   └── search_hotels-20260913T142305.654321Z.json
└── tavily_search/
    └── tavily_search-20260913T142310.000001Z.json
```

### 4. Versioned Response Envelope

Implement a versioned response-envelope schema and store. Each logical invocation
writes one file atomically under:

```text
backend/tool_responses/<tool_name>/<tool_name>-<UTC datetime with microseconds>.json
```

Each envelope contains:

```json
{
  "schema_version": 1,
  "tool_name": "search_flights",
  "provider": "serpapi",
  "recorded_at": "2026-09-13T14:23:01.123456Z",
  "request_fingerprint": "sha256:...",
  "arguments": {},
  "exchanges": [
    {
      "request": {},
      "response": {},
      "http_status": 200,
      "duration_ms": 0,
      "attempt": 1
    }
  ],
  "normalized_result": {},
  "status": "success",
  "error": null
}
```

The store must include canonicalized tool arguments, a SHA-256 request fingerprint,
sanitized raw HTTP requests, raw JSON responses, normalized output, timings, retry
count, HTTP statuses, and error details. Non-2xx responses and transport failures are
also recorded.

Before serialization, redact:

- API keys and bearer tokens
- `Authorization`, `Cookie`, and `Set-Cookie` headers
- key-like query parameters
- credentials embedded in URLs
- sensitive identifiers configured by the application

### 5. Atomic Writes and Retention

Run retention cleanup during recorder initialization and writes. Delete recordings
older than 30 days. Use a temporary file followed by an atomic replacement and
collision-safe UTC filenames so concurrent graph branches cannot overwrite or corrupt
recordings.

### 6. Fingerprint Replay

Add a replay store that indexes successful envelopes by
`(tool_name, request_fingerprint)` and chooses the newest match.

In mock mode:

1. Canonicalize arguments and calculate the request fingerprint.
2. Replay `normalized_result` from the newest exact successful match.
3. If no recording matches, use the existing curated fixture implementation.
4. Expose replay-hit or replay-miss information in `_meta`.

Never select an unrelated latest response solely because it belongs to the same tool.

## Phase 2: Shared External API Runtime

### 7. Process-Wide HTTP Client

Implement a process-wide `httpx.AsyncClient` service with:

- explicit connect, read, write, and pool timeouts
- bounded keep-alive and total connection limits
- per-provider semaphores
- optional HTTP/2 where supported
- graceful shutdown from the FastAPI lifespan

Do not construct a new client per request as the current transit, road-route, and taxi
adapters do.

### 8. Provider-Aware Request Execution

Centralize JSON requests through a provider-aware request method. Every provider
exchange made during one logical tool invocation is appended to that invocation's
response envelope.

Retry only:

- transient connection and timeout failures
- HTTP 408
- HTTP 429
- HTTP 5xx

Honor `Retry-After` when present and otherwise use capped exponential backoff with
jitter. Never retry authentication failures, invalid requests, quota-plan exhaustion,
or valid empty results.

### 9. Caching and Request Coalescing

Add canonical cache keys and request coalescing.

- Reuse SerpAPI's exact-query one-hour cache.
- Use Redis for permitted Tavily, SerpAPI, and FX data.
- Do not persistently cache Google Maps content beyond policy exceptions such as Place
  IDs.
- Use bounded in-flight deduplication for identical concurrent Google requests.
- Record logical cache hits in the response envelope even when no provider request is
  made.

### 10. Real-Mode Readiness

Validate credentials when real mode starts. Use separate restricted server-side Google
keys for Routes and Geocoding versus Places where deployment restrictions require it.
Validate SerpAPI, Tavily, and Open Exchange Rates credentials as applicable.

Readiness must fail with actionable missing-key details in real mode while mock mode
continues to start without external credentials.

## Phase 3: Provider Adapters and Normalization

### 11. SerpAPI

Implement the following adapters:

- Resolve free-text origins and destinations through Google Flights Autocomplete before
  Google Flights search. Cache resolved airport or location IDs where permitted.
- Use one-way per-leg flight searches with travel date, traveler count, locale, and
  currency.
- Preserve SerpAPI `best_flights` and `other_flights` shapes expected by
  `TransportSearchAgent`.
- Call Google Hotels with required check-in and check-out dates and adults, plus
  optional price and accommodation-style filters.
- Normalize hotel results to the existing `properties` contract consumed by
  `StaySearchAgent`.
- Keep SerpAPI provider caching enabled.
- Leave `deep_search` disabled by default to control latency and cost.

### 12. Tavily Search

Implement Tavily Search through the shared REST client with:

- concise, focused queries
- `basic` search depth by default
- bounded `max_results`
- `include_usage=true`
- no raw page content unless a tool explicitly requires it
- source, date, country, language, and domain tuning where relevant
- official-source prioritization for visa and safety research

Return Tavily's existing `results` and `answer` contract plus normalized usage and
request metadata.

### 13. Google Places API (New)

Implement Text Search and Place Details using minimal explicit field masks. Never use a
wildcard field mask in production.

Normalize:

- place IDs and resource names
- display names and addresses
- coordinates
- ratings and rating counts
- business status
- regular and current opening hours
- Google Maps and website links
- reviews and review-author attribution
- photos and photo-author attribution
- provider attribution required for frontend display

Reuse common Places request and normalization helpers for taxi, embassy, visa-centre,
and rental discovery rather than duplicating HTTP code.

### 14. Google Routes and Geocoding

Migrate the existing transit and road-route adapters to the shared runtime while
preserving their `options` contracts.

Implement Compute Route Matrix with:

- origin and destination count validation
- a maximum of 625 non-transit elements
- a maximum of 100 transit or traffic-aware-optimal elements
- index-aware parsing because response ordering is not guaranteed
- per-element error handling
- normalized distance and duration matrices

Implement Google Geocoding API v4 as a server-to-server integration with minimal field
masks. Normalize lower-camel-case provider responses to the existing
`{status, lat, lng, ...}` contract.

### 15. Composite Travel Tools

Implement the tools that combine multiple providers:

#### `visa_centre_search`

Use Tavily to identify the corridor-specific official operator or consular process,
then use Places to resolve the nearest relevant office. Prefer official government,
embassy, consulate, and operator sources. Return provenance and verification
timestamps.

#### `embassy_search`

Use Places to locate the destination country's embassy or consulate relative to the
traveler's home city.

#### `rental_search`

Use Places vehicle-rental discovery, supplemented by Tavily for indicative offerings.
Mark results as non-bookable unless the provider supplies live inventory and booking
availability.

#### `fuel_price`

Use Tavily with country, date, currency, and source provenance. Return a typed
unavailable result rather than presenting a hardcoded value as live data.

### 16. Currency Conversion

Implement Open Exchange Rates for `currency_convert`:

- Fetch and cache the latest rates once per base snapshot.
- Derive cross-rates through USD when the account does not permit arbitrary base
  currencies.
- Validate ISO 4217 currency codes.
- Return `amount_converted`, `rate`, provider timestamp, and fetched timestamp.
- Keep same-currency conversion local and exact.

### 17. Local Deterministic Tools

Keep `cluster_by_proximity`, `enforce_opening_hours`, and `validate_day_duration` as
local deterministic tools. Pass them through the logical recorder when capture is
enabled so response capture covers every tool invocation, not only HTTP providers.

## Phase 4: Agent Integration and Behavioral Gaps

### 18. Preserve Dependency Injection

Keep constructor injection and update only tool arguments and result handling at agent
boundaries.

- `TransportSearchAgent` supplies traveler and currency context and accepts normalized
  partial failures per leg.
- `StaySearchAgent` continues deriving single- and multi-stop dates, aligns argument
  names with the real hotel adapter, and validates non-empty ordered dates.
- `FoodDiscoveryAgent`, `ReviewsAgent`, `SafetyAgent`, and `VisaAgent` consume normalized
  metadata, log degraded calls, and retain successful sibling results.

### 19. Ground Local Experiences

Bring `LocalExperiencesAgent` into alignment with the approved architecture:

- Use Google Places search plus Tavily supplementation as factual discovery per stop.
- Map verified candidates to `Experience` models.
- Use geocoding only when retrieved candidates lack coordinates.
- Do not rely on LLM world knowledge to introduce venues absent from retrieved results.
- If an LLM remains for personalization, limit it to ranking, filtering, or summarizing
  retrieved candidates.

### 20. Use Real Route Distance for Self-Drive

Activate `SelfDriveSearchAgent`'s currently unused distance-matrix tool. Build origins
and destinations from selected route stops and compute total route distance when
available.

Remove the unconditional 80 km-per-day estimate except as an explicitly marked
degraded fallback. Rental, fuel, and matrix failures must remain independent so one
failure does not discard successful sibling results.

### 21. Truthful Degradation

Do not replay mock data automatically in real mode. Agents continue with available
sibling results and expose `_meta.status=partial` or `_meta.status=error`.

Visa and safety outputs retain source links and confidence. Critical unknown values
remain unknown rather than being filled from ungrounded LLM memory.

## Phase 5: Documentation and Rollout

### 22. Documentation

Update `plan.md` and developer documentation with:

- the implemented provider matrix
- response-envelope schema
- mock lookup order
- capture and retention policy
- Google attribution and caching warning
- server-side API key restrictions
- local capture and replay workflow
- manual live-provider verification commands

### 23. Deferred Test Work

Do not write or modify automated tests as part of this implementation. Unit,
integration, provider-contract, live-smoke, and end-to-end tests are deferred to a
separate follow-up specification and change set.

## Relevant Files

- `backend/app/config.py`: capture, transport, provider, and validation settings.
- `.env.example`: real/mock and capture switches without secrets.
- `.gitignore`: ignore `backend/tool_responses/`.
- `backend/app/tools/base.py`: shared result metadata and typed tool errors.
- `backend/app/tools/factory.py`: real recording and mock replay wrappers.
- `backend/app/tools/mock/_helpers.py`: curated fixture fallback after replay lookup.
- `backend/app/services/external_api_client.py`: pooled HTTP client, retries, limits,
  coalescing, and raw exchange capture.
- `backend/app/services/tool_response_store.py`: envelope writer, redaction,
  fingerprint index, replay, and retention pruning.
- `backend/app/main.py`: shared HTTP lifecycle and real-mode readiness validation.
- `backend/app/services/cache_service.py`: canonical non-Google cache keys and permitted
  TTL integration.
- `backend/app/tools/real/serpapi_tools.py`: flight autocomplete/search and hotel
  adapter.
- `backend/app/tools/real/tavily_tools.py`: Tavily search adapter.
- `backend/app/tools/real/places_tools.py`: Places adapters and normalization helpers.
- `backend/app/tools/real/transit_tools.py`: shared-runtime Routes transit adapter.
- `backend/app/tools/real/road_route_tools.py`: shared-runtime Routes driving adapter.
- `backend/app/tools/real/taxi_tools.py`: reusable Places taxi discovery.
- `backend/app/tools/real/geo_tools.py`: Route Matrix and Geocoding v4.
- `backend/app/tools/real/visa_tools.py`: Tavily and Places visa tools.
- `backend/app/tools/real/rental_tools.py`: Places and Tavily rental/fuel tools.
- `backend/app/tools/real/fx_tools.py`: Open Exchange Rates conversion.
- `backend/app/agents/local_experiences_agent.py`: tool-grounded venue discovery.
- `backend/app/agents/self_drive_search_agent.py`: route-matrix distance calculation.
- `backend/app/agents/transport_search_agent.py`: live flight context and partial
  handling.
- `backend/app/agents/stay_search_agent.py`: hotel arguments and date validation.
- `backend/app/agents/visa_agent.py`: provenance and degraded-state handling.
- `plan.md`: synchronized system architecture and operational guidance.

## Verification

1. Run static validation only:

   ```bash
   rtk ruff check backend
   rtk mypy backend/app
   ```

2. With `MOCK_EXTERNAL_APIS=false` and capture enabled in a local secret-bearing
  environment, invoke each remote tool once through a manual development command or
  application flow. Inspect one file under every remote tool directory for filename
  correctness, raw exchanges, normalized output, and redaction.

3. Set `MOCK_EXTERNAL_APIS=true` and repeat the same requests without network access.
   Verify exact fingerprint-matched normalized recordings are replayed. Remove a
   matching recording and verify curated fixture fallback plus replay-miss metadata.

4. Start the backend in production configuration with capture unset. Verify no response
   files are written and readiness fails clearly when required real-mode credentials
   are missing.

5. Review the Google Maps billing-account terms before retaining or replaying Google
   content. Verify required Google Maps attribution and review/photo author attribution
   reach the frontend before live release.

## Acceptance Criteria

1. Setting valid provider keys and `MOCK_EXTERNAL_APIS=false` makes all remote logical
   tools callable without modifying agent code.
2. Setting `MOCK_EXTERNAL_APIS=true` makes the graph perform zero external network
   calls.
3. Every real and mock implementation satisfies the same agent-facing output contract.
4. When capture is enabled, each logical tool invocation creates exactly one separate
   JSON envelope under its tool-specific directory.
5. Recorded filenames follow `<tool_name>-<UTC datetime>.json` and cannot collide under
   concurrent execution.
6. Recorded data contains no API keys, authorization headers, cookies, or credential
   query parameters.
7. Recordings older than 30 days are pruned automatically.
8. Mock replay selects only the newest successful exact fingerprint match and otherwise
   falls back to curated fixtures.
9. Real-mode failures never silently return mock data.
10. Retry behavior is bounded, respects `Retry-After`, and excludes permanent failures.
11. Google Places requests use explicit minimal field masks and retain required source
    attribution.
12. `LocalExperiencesAgent` cannot introduce an attraction absent from retrieved
    candidates.
13. `SelfDriveSearchAgent` uses route-matrix distance when available and labels any
    heuristic distance as degraded.
14. Response capture defaults off in production.
15. No automated tests are created or modified as part of this implementation.

## Research Basis

- SerpAPI Google Flights requires airport codes or location KGIDs and provides a
  dedicated Flights Autocomplete endpoint. Its exact-query cache lasts one hour, and
  cached hits are free.
- SerpAPI Google Hotels requires check-in and check-out dates. `StaySearchAgent`
  already derives these values, but the real adapter must consume and validate them.
- Tavily recommends focused queries, bounded asynchronous concurrency, explicit
  timeouts, exponential backoff, deduplication, usage tracking, and `basic` depth as the
  default latency/cost balance.
- Google Places API (New) requires explicit field masks and bills according to requested
  field tiers. Wildcard masks are discouraged in production.
- Google Routes matrix limits are 625 non-transit elements and 100 transit or
  traffic-aware-optimal elements. Responses include per-element errors and indices
  because ordering is not guaranteed.
- Google Maps recommends HTTPS, restricted server-side credentials, exponential
  backoff, avoidance of synchronized request spikes, selective response parsing, and
  compliance with content caching and attribution policies.
- HTTPX supports separate connect, read, write, and pool timeouts plus shared
  connection-pool limits. Reusing one client provides connection pooling that the
  current per-call client construction cannot provide.

## Risks and Follow-Up Work

- Google Maps content retention and replay must be reviewed against the project's
  billing-account agreement before live capture is enabled broadly.
- Raw response files may include traveler queries or addresses even after credential
  redaction. The 30-day retention policy and production-default-off setting are
  mandatory controls, not optional guidance.
- Provider response schemas can evolve. Normalizers must tolerate absent fields and
  isolate provider payloads from stable agent contracts.
- Web-discovered rental and fuel information is indicative, not guaranteed inventory
  or transactional pricing.
- Automated test coverage is deferred. Until a follow-up test specification lands,
  rollout depends on static checks and the manual verification steps in this document.
- External API quota governance and monthly spend controls remain governed by
  `specs/api-cost-governance-and-multi-stop-guardrails-spec.md` and should be implemented
  alongside this specification where the concerns overlap.