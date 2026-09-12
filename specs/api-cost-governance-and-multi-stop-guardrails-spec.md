# Plan: Close multi-stop planning loopholes + API-credit governance layer

## Context / constraints
- SerpAPI: 250 searches/month (very tight — flights+hotels).
- Tavily: 1000 queries/month.
- Google Places/Maps: pay-as-you-go, $1000 initial credit.
- Real tool implementations (`backend/app/tools/real/*`) are currently all `NotImplementedError` stubs (Phase 5 not started).
- `CacheService` (`backend/app/services/cache_service.py`) exists with TTL constants + key builders but is ONLY used for LLM usage bookkeeping (`llm.py`, `routers/trip.py`) — zero tool calls (flights/hotels/places/tavily/rentals) are cached anywhere today.
- `max_llm_spend_usd_per_trip` in `config.py` is defined but never read/enforced anywhere in the codebase (confirmed via grep — zero other references).
- No `backend/evals/` directory exists yet despite being called out as "from day one" in dev-roadmap.
- Current graph (`backend/app/graph/graph.py`, `state.py`) is single-destination only: `TransportSearchAgent`, `StaySearchAgent`, `LocalExperiencesAgent` all key off one `state["destination"]` string. The open `specs/stops-discovery-agent-spec.md` plan is the path to multi-stop, but its Phase 6 (Tavily/Places/route-distance verification, deterministic route validation) is explicitly deferred — meaning Phases 1–5 would ship route + itinerary generation that can hallucinate unreachable/non-existent stops, skip permit checks (e.g., Arunachal ILP, Bumla Pass closures), and never surface "unverified" status to the user.

## Loopholes found (by category)

### A. Multi-stop / multi-day correctness
1. No multi-stop support today at all — single `destination` string throughout state and Layer 2/3/4 agents.
2. Stops-discovery spec defers ALL external validation (Tavily grounding, Places/geocoding existence check, route-distance feasibility, permit/seasonal checks) to Phase 6, but ships itinerary compilation in Phase 4 — risk of confidently presenting fabricated/infeasible routes as final output with no "provisional" flag surfaced to the user/UI.
3. No day-budget/pacing validation: nothing checks that sum of inter-stop travel days/hours fits inside the total trip length, or flags back-to-back long-travel-day fatigue.
4. No cap on number of stops/legs — a request like "15-day, 10-city Europe trip" fans out Layer 2/3/4 per stop with no ceiling, multiplying API+LLM cost combinatorially.
5. No dedup when the same stop appears twice in a circular/there-and-back route (e.g., Dirang outbound + return) — spec's "duplicate handling" covers stop identity but not re-searching stays/experiences for the same place twice.
6. No incremental re-plan path — editing one day/stop after compilation appears to require rerunning the whole graph (full re-spend of API/LLM budget) rather than patching just the affected stop's subgraph.
7. Mock fixtures only cover a handful of named destinations (Osaka, Lisbon, Leh) — no documented graceful-degradation path for arbitrary/tail destinations once real APIs are live.

### B. Orchestration / spend control
8. After `max_clarification_rounds` is exhausted, best-effort defaults are applied and the graph proceeds — but there's no check that critical fields (e.g., destination) are non-empty/sane before firing Layer 2, risking API calls with garbage input.
9. `max_llm_spend_usd_per_trip` is unenforced dead config — no circuit breaker stops a runaway trip from blowing past its LLM budget.
10. No equivalent per-trip/per-session cap or circuit breaker for external API spend (SerpAPI/Tavily/Places call counts or estimated $ cost).

### C. Caching & API credit control (core ask)
11. **Biggest gap**: `CacheService` + TTLs (flights 4h, hotels 2h, transit 6h, places 48h, tavily 24h, fx 12h, rentals 12h) are fully defined but never wired into `ToolFactory`-produced real tools or agents — every call will hit paid APIs fresh even for identical repeated queries.
12. No request coalescing / single-flight lock — concurrent identical requests (two users, or retries) will double-spend quota.
13. No negative-result caching for empty/failed lookups (protects against retry storms on typo'd or unsupported destinations).
14. No cache-key canonicalization — free-text place names ("Osaka" vs "Osaka, Japan") would fragment the cache and multiply calls; gets worse once stops-discovery introduces many arbitrary stop names.
15. No shared "resolved place registry" in `TripState` — destination/stop names get re-resolved (geocode, hub-ID, place search) independently by multiple agents (transport hub-ID, stops discovery, local experiences, reviews) instead of once.
16. No rate limiting / backoff / circuit breaker around outbound SerpAPI/Tavily/Places calls — no protection against 429s or quota cliff, especially dangerous given SerpAPI's 250/month ceiling.
17. No API-call usage metering — `UsageLogger` (`llm.py`) tracks LLM token cost only; there's no equivalent counter for SerpAPI/Tavily/Places calls per session/trip/month, so nothing catches a runaway pattern before the monthly quota silently runs out.
18. Likely duplicate Places Details calls across agents (`LocalExperiencesAgent.search_places` vs `ReviewsAgent`'s place lookups) — `place_id`s resolved once are not reused.
19. No `backend/evals/` cost-regression suite — nothing catches an agent change that adds an extra tool call per run before it hits production and burns quota.

## Steps

### Phase 1: Tool-call caching + quota governance (foundational, unblocks everything else)
1. Add a `CachedTool` wrapper in `backend/app/tools/factory.py` — `ToolFactory.get()` wraps every **real** tool instance (mock tools stay uncached, they're free) with a decorator that: builds a canonical cache key via existing `CacheService.*_key()` builders, checks `cache_service.get()` first, calls the underlying tool only on a miss, then `cache_service.set()` with the tool-appropriate TTL constant already defined in `cache_service.py`. Cache hits/misses logged via `structlog` for observability.
2. Add a Redis-based single-flight lock (short-TTL `SET NX`) inside the same wrapper so concurrent identical cache-key requests await one in-flight upstream call instead of firing N.
3. Add negative-result caching: cache empty/error results with a short TTL (e.g. 10 min) to stop retry storms on failing queries.
4. Add a `QuotaGovernor` service (new `backend/app/services/quota_service.py`) — Redis counters keyed by provider+month (`quota:serpapi:2026-09`, `quota:tavily:2026-09`), incremented on every real (non-cached) call. Configurable hard ceilings in `config.py` (`serpapi_monthly_quota=250`, `tavily_monthly_quota=1000`) with a soft-warn threshold (e.g. 80%) that logs/alerts, and a hard-stop that forces fallback (cached-stale-if-available → secondary source → mock/LLM-estimate with a `low_confidence`/`estimated` flag) once exceeded.
5. Enforce `max_llm_spend_usd_per_trip`: extend the existing `_write_usage`/`UsageLogger` accumulation in `llm.py` to check the running per-session total against `settings.max_llm_spend_usd_per_trip` before each `get_llm()` call site (or via a lightweight pre-call guard in `orchestrator.py`/agent `base.py`), short-circuiting to a cheaper/no-op path when exceeded.
6. Extend `UsageLogger`'s pattern to tool calls: record per-session, per-provider call counts/estimated cost in Redis (reuse `usage_key`-style keys), surfaced through the existing `/trip/{session_id}` usage read path in `routers/trip.py`.

### Phase 2: Canonical place registry (dedupes Places/Tavily/geocode calls across agents)
7. Add a `resolved_places: dict[str, ResolvedPlace]` field to `TripState` (`backend/app/graph/state.py`) — keyed by canonical place key (lowercased, geocoded place_id once available). `ResolvedPlace` holds `place_id`, `lat`/`lng`, `canonical_name`, `country`.
8. First agent to resolve a place name (stops discovery, or `TransportSearchAgent`'s hub-ID step for single-destination trips) writes into `resolved_places`; `LocalExperiencesAgent`, `ReviewsAgent`, `StaySearchAgent`, `FoodDiscoveryAgent`, `SafetyAgent` read from it before calling Places/Tavily again, only falling back to a fresh resolve on a miss.
9. `ReviewsAgent` reuses `place_id`s already produced by `LocalExperiencesAgent`/`StaySearchAgent` instead of re-searching Places for the same entities (avoids duplicate, pricier Place Details calls).

### Phase 3: Multi-stop guardrails (extends `specs/stops-discovery-agent-spec.md`, *depends on Phase 1 for cost safety*)
10. Add a hard `max_stops`/`max_legs` config cap in `StopsDiscoveryAgent`; routes exceeding it trigger the existing clarification `interrupt()` (ask the user to narrow scope) *before* any Layer 2 fan-out fires — protects the 250/month SerpAPI ceiling from combinatorial multi-city fan-out.
11. Add deterministic dedup in the route contract: if the same canonical stop (via the Phase 2 registry) appears in more than one leg (there-and-back, hub revisit), only issue one stay/experience search for it and reuse the result across both legs' output keys.
12. Add a `verification_status` field (`provisional` / `verified`) to the route contract and thread it through to `Itinerary`/`TripSegment` output and SSE progress events *starting in Phase 1 of the spec*, rather than silently shipping unverified routes until Phase 6 lands — surfaces the accuracy caveat to the chat UI immediately.
13. Add a deterministic day-budget check before compiling: sum allocated travel days/hours across `route_legs` vs. total trip length; if it overflows, pause for clarification or shrink scope rather than silently compiling an infeasible itinerary.

### Phase 4: Incremental re-plan / chat-edit path (*depends on Phases 1–3*)
14. Add a narrow "patch" entrypoint (new function alongside `run_graph` in `graph.py`) that accepts a target stop/day/leg id and re-invokes only the affected Layer 2/3/4 subset (e.g. `stay_search` + `stay_analyst` for one stop), reusing all cached/resolved data from the prior full run via the Phase 1 cache + Phase 2 registry — required so routine chat edits ("swap this hotel", "add a day in Dirang") don't re-burn the full trip's API/LLM budget.

### Phase 5: Regression protection
15. Add `backend/evals/` (referenced but never created) with a cost-regression evaluator: run fixture trips in mock mode, assert per-agent tool-call counts stay within a checked-in baseline (`baselines.json`) so a future change that silently adds an extra SerpAPI/Tavily call per run is caught in CI, not in production quota burn.
16. Add unit tests for the `CachedTool` wrapper (cache hit/miss/negative-cache/single-flight), `QuotaGovernor` (soft-warn, hard-stop, fallback path), and the place registry dedup behavior.

## Relevant files
- `backend/app/tools/factory.py` — add `CachedTool` wrapper around real tools in `ToolFactory.get()`.
- `backend/app/services/cache_service.py` — reuse existing TTL constants/key builders; add negative-cache TTL constant.
- `backend/app/services/quota_service.py` — new: monthly quota counters + soft/hard thresholds.
- `backend/app/config.py` — add `serpapi_monthly_quota`, `tavily_monthly_quota`, soft-warn ratio; wire up enforcement for existing unused `max_llm_spend_usd_per_trip`.
- `backend/app/llm.py` — extend `_write_usage`/`UsageLogger` pattern for tool-call metering and per-trip LLM spend guard.
- `backend/app/graph/state.py` — add `resolved_places`, route `verification_status`.
- `backend/app/agents/local_experiences_agent.py`, `reviews_agent.py`, `stay_search_agent.py`, `food_discovery_agent.py`, `safety_agent.py`, `transport_search_agent.py` — read/write the shared place registry instead of independently resolving names.
- `backend/app/agents/stops_discovery_agent.py` (per open spec) — add `max_stops`/`max_legs` cap, dedup, `verification_status`, day-budget check.
- `backend/app/graph/graph.py` — add patch/partial re-run entrypoint.
- `backend/evals/` — new: cost-regression baseline + evaluator.
- `backend/tests/unit/` — new tests for caching, quota, dedup.

## Verification
1. Unit test `CachedTool`: identical calls within TTL hit cache once; concurrent identical calls single-flight to one upstream call; negative cache short-circuits repeated failing queries.
2. Unit test `QuotaGovernor`: soft-warn logs at 80%, hard-stop forces fallback path at 100%, monthly key rollover resets counters.
3. Integration test: multi-stop fixture (reuse Arunachal scenario from the spec) asserts total SerpAPI/Tavily/Places call count stays within an expected bound and duplicate stops aren't re-searched.
4. Run `backend/evals/run_evals.py --mode mock` (once created) against `baselines.json` to catch call-count regressions.
5. Manual: confirm `/trip/{session_id}` usage endpoint surfaces both LLM spend and external API call counts.

## Decisions
- Cache/quota/dedup layer is foundational and should land before or alongside the stops-discovery-agent-spec implementation, not after — otherwise multi-stop fan-out ships directly into the tight SerpAPI/Tavily ceilings with zero protection.
- Mock tools remain uncached (no cost, fixtures are static); only real tool instances get wrapped.
- Prefer surfacing `verification_status: provisional` immediately (Phase 3 here / Phase 1 of the spec) over waiting for full Phase 6 external verification, so the product never silently presents unverified routes as final.
- Quota hard-stop fallback order: stale cache (even if past TTL) → cheaper/alternate source (e.g. Tavily instead of SerpAPI) → LLM-estimated data clearly flagged as an estimate — never a silent hard failure.

## Further considerations
1. Whether to store the monthly quota counters in Postgres instead of Redis for durability across Redis restarts — recommend Redis with a daily snapshot to Postgres if quota accuracy across restarts matters.
2. Whether patch/incremental re-plan (Phase 4) should be scoped now or deferred — it's high-value for a "chat app" but is the largest single piece of new graph-execution logic; could be split into its own follow-up plan.
