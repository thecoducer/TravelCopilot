## Plan: Add Multi-Stop Place Planning

Introduce `StopsDiscoveryAgent` as a Layer 1 route-intelligence agent. It will discover and structure an ordered multi-stop route, allocate trip days and overnight locations, and produce a **provisional** route contract consumed by Layer 2. The multi-day trip planner is **universally applicable to any country, city, region, or place globally**. Users can provide ambiguous, high-level queries with just a source and a destination (e.g. *"Plan a trip to Japan from NYC"* or *"10 days in Amalfi Coast from London"*); it is the agent's explicit job to understand the regional geography, discover intermediate stops and transport gateways, evaluate candidate options, and structure the complete route. External grounding and route feasibility validation are explicitly deferred to Phase 6. Layer 2 searches transport, stays, and experiences per route leg/stop; Layer 3 and Layer 4 aggregate and reason over those keyed results; Layer 5 compiles the existing `TripSegment` output without independently inventing stops. Every stop and leg is a stable, uniquely identified **occurrence** (`stop_id` / `leg_id`) — never keyed by display name — so repeated places (e.g. Dirang visited outbound and again on return) and ambiguous transport gateways (e.g. Arunachal Pradesh is a region, not a transport endpoint) are modeled unambiguously. See **Core concepts** below before the phase steps; it defines terms (`stop_id`/`leg_id`, gateway, day allocation, transport policy precedence, provisional-vs-verified, route revision) that every phase step depends on.

The initial route contract uses six explicit `leg_type` values:
- `source_to_gateway`: travel from the user's source to the trip's **access gateway** (see Core concepts) — e.g. long-distance flight/train/bus from origin to gateway (`Kolkata -> Guwahati` or `Kolkata -> Leh IXL Airport`).
- `gateway_to_stop`: transfer from the access gateway to the first itinerary stop — e.g. regional road/transit connection (`Guwahati -> Bhalukpong` or `Leh Airport -> Leh hotel`).
- `internal_transfer`: movement between itinerary places within the same country/region, including intercity transfers (`Bhalukpong -> Dirang -> Tawang`).
- `stop_to_gateway`: return transfer from the last overnight itinerary stop back to the exit gateway (`Tawang -> Guwahati` or `Leh hotel -> Leh Airport`).
- `gateway_to_source`: return travel from the exit gateway back to the user's source (`Guwahati -> Kolkata` or `Leh IXL Airport -> Kolkata`).
- `country_transfer`: movement between destinations in different countries during a multi-country trip (e.g. `Paris -> Amsterdam`).

`source_to_gateway` and `gateway_to_source` are reserved for long-distance transit between origin and gateway. `gateway_to_stop` and `stop_to_gateway` connect the gateway to the actual itinerary stops. `country_transfer` is used for cross-border legs such as Paris -> Amsterdam, Amsterdam -> Venice, or Venice -> Rome.

## Non-negotiable acceptance gates

These are hard requirements and must be treated as release-blocking if not implemented:

1. Every downstream result that is associated with a stop or leg must retain its originating `stop_id` and, when useful, `leg_id`.
   - This includes `Experience`, `StayOption`, `reviews_summary`, `food_recommendations`, safety/budget aggregates, and any per-stop transport results.
   - Name-based keys are not allowed for multi-stop data because repeated occurrences (for example, Dirang outbound vs Dirang return) would silently overwrite each other.

2. A route must explicitly declare one of three states:
   - `single_destination` for a genuine one-place trip
   - `multi_stop_provisional` for a valid provisional multi-stop structure
   - `discovery_failed` for an incomplete or unusable route
   - Only `single_destination` may use the legacy single-destination fallback fields.

3. `discovery_failed` must never silently degrade into a single-destination itinerary. It must trigger clarification / resume or fail hard before any downstream supply search runs.

4. `route_verification_status` remains `"provisional"` until Phase 6 external verification is implemented; the product must never present a provisional route as authoritative.

## Development execution protocol

This document is the implementation backlog and release contract for the multi-stop rollout. The numbered phase steps below are authoritative; do not implement a later phase until the current phase exit gate passes.

### TODO workflow

At the start of each phase, create a TODO list containing one item for every numbered deliverable in that phase. Each TODO must name its owning file/module, acceptance test, and verification command. Work one phase at a time:

1. Read the applicable official documentation before using or changing a framework/library API. At minimum, use the official documentation for LangGraph (`StateGraph`, reducers, `interrupt()`/resume, checkpointing), Pydantic v2 (models, validation, serialization), FastAPI/OpenAPI, `structlog`, pytest/pytest-asyncio, Ruff, mypy, and uv as each phase touches them. Reuse the repository's existing wrappers and patterns; do not invent replacement abstractions when an official or local solution exists.
2. Mark exactly one TODO `in_progress`. Write or update the focused test that expresses the acceptance condition before implementing the behavior when practical.
3. Implement the smallest modular change that satisfies the TODO. Keep mock and real tools behind `ToolFactory`; mock-first tests must make zero network calls. Add structured logs for route creation/failure, route version changes, per-stop/per-leg search, invalidation, and compiler rejection paths using the repository logger.
4. Run the focused test for the changed slice, then complete the remaining TODOs in the current phase. Do not hide failures with broad fallbacks, test-only production branches, or weakened assertions.
5. Before closing the phase, run `make verify` from the repository root. This runs `check-deps`, formatting, Ruff, mypy, the full backend test suite, package build, and Docker build. Treat any failure as a blocker for phase completion; fix it in the current phase and rerun the focused test plus `make verify`.
6. Mark TODOs `completed` only after the focused test and `make verify` pass. Record changed files, tests, verification output, deferred items, and any compatibility decision in the phase handoff. A phase may end only with no unresolved TODOs except explicitly documented Phase 6 deferrals.

### Quality and compatibility rules

- Keep agents small and single-purpose: route discovery owns route structure; search agents call tools; analyst agents reason over typed results; the compiler assembles output without inventing route structure.
- Validate state at every boundary with typed Pydantic models. Preserve single-destination JSON and behavior until the multi-stop contract is selected explicitly.
- Use structured logging only through the existing logging module. Include `session_id`, `route_version`, `stop_id`/`leg_id` where applicable, and counts/status fields; never log secrets or full user prompts unnecessarily.
- Add tests for success, empty results, tool failures, repeated stop occurrences, gateway pass-throughs, `discovery_failed`, route revision, and legacy single-destination compatibility. Prefer real behavior and injected mock tools over assertions about internal calls.
- Keep comments short and limited to behavior that is not clear from the code. Update OpenAPI, persistence, frontend, PDF, and SSE contracts in the phase where the backend field becomes public.
- Do not promote provisional route output to `verified`, `authoritative`, or `canonical` before Phase 6 validation is implemented.

### Phase exit gates

| Phase | Completion gate |
| --- | --- |
| Phase 1: contract and graph design | Typed route models, state fields, discovery status, versioning, and graph gate exist; route-structure tests pass; `make verify` passes. |
| Phase 2: route-aware supply search | Transport, stays, and experiences are keyed by `leg_id`/`stop_id`; gateway pass-through and repeated-stop tests pass; `make verify` passes. |
| Phase 3: analysis and enrichment | Reviews, food, safety, budgeting, self-drive, and transport optimization consume current-version keyed results; focused downstream tests pass; `make verify` passes. |
| Phase 4: synthesis and output models | Compiler preserves route boundaries and return anchor; output metadata serializes; single-destination regression tests pass; `make verify` passes. |
| Phase 5: migration and integration | API, persistence, SSE, frontend, PDF, cache keys, integration tests, and documentation expose the contract; full regression suite and `make verify` pass. |
| Phase 6: external verification | Grounding, geocoding, feasibility, deterministic validation, confidence, and promotion to `verified` are implemented with mocked tests; `make verify` and applicable evals pass. |

If a phase cannot pass its gate, stop implementation at that phase, record the blocker, and do not claim the rollout is complete. `make verify` is the required repository-level proof; focused tests are additional evidence, not a replacement.

## Core concepts

### Universal Global Scope & Ambiguous Query Resolution
The multi-day trip planning architecture is designed for **universal global applicability across any country, city, region, or place** (e.g., Japan, Amalfi Coast, Patagonia, Rajasthan, Scottish Highlands, Ladakh, or Arunachal Pradesh). Specific regional examples in this spec are strictly illustrative test scenarios, not domain limitations.

Users frequently submit ambiguous, high-level, or minimal queries containing only an origin and a broad destination (e.g., *"Plan a 10-day trip to Japan from New York"*, *"7 days in Amalfi Coast from London"*, *"Trip to Ladakh from Kolkata"*). It is the explicit job of `StopsDiscoveryAgent` (and Layer 1 route intelligence) to:
1. **Disambiguate the region and identify access gateways**: Discover regional entry/exit transport hubs (airports, train stations, road hubs) connecting the user's origin to the destination region.
2. **Discover overnight itinerary stops & circuits**: Propose a logical, geographically ordered multi-stop circuit of overnight stops based on standard travel patterns, regional connectivity, and trip duration.
3. **Structure candidate gateway options**: Evaluate trade-offs (flight vs. overland, travel duration, acclimatization, scenic value, cost tier) and generate up to `MAX_GATEWAY_OPTIONS` structured options for downstream search and user selection.

### Stop and leg occurrence identity
Every stop in a route is an **occurrence**, not just a place name. A route that revisits a place (e.g. Kolkata -> Bhalukpong -> Dirang -> Tawang -> Dirang -> Kolkata) has two distinct Dirang occurrences and must assign two distinct `stop_id`s (e.g. `dirang_01`, `dirang_02`) — a dict keyed by place name cannot represent this and would silently merge or overwrite one occurrence's data with the other's. `RouteLegPlan` similarly carries a stable `leg_id` (e.g. `leg_03`), independent of its origin/destination names. **Every keyed per-stop or per-leg field introduced anywhere in this spec (`stays_raw_by_stop`, `experiences_raw_by_stop`, `stays_shortlist_by_stop`, `reviews_summary`, per-stop food/safety/budget data, transport-leg results) is keyed by `stop_id`/`leg_id`, never by place name alone.**

### Gateway vs. source vs. first stop
The user's `source` is not necessarily connected by scheduled transport to the trip's first itinerary stop. For `5 days Arunachal from Kolkata`: `source` is Kolkata, the **access gateway** is Guwahati (nearest city with flight/train/bus connectivity to Kolkata), and the **first itinerary stop** is Bhalukpong. `StopsDiscoveryAgent` must resolve the access gateway as its own stop occurrence with `stop_kind: "gateway_transit"`, distinct from both `source` and the first itinerary stop. This decomposes the journey into distinct leg types:
- `source_to_gateway`: `Kolkata -> Guwahati` (flight/train/bus).
- `gateway_to_stop`: `Guwahati -> Bhalukpong` (road).
- `internal_transfer`: `Bhalukpong -> Dirang -> Tawang` (road).
- `stop_to_gateway`: `Tawang -> Guwahati` (road), anchored at the last overnight stop back to the gateway.
- `gateway_to_source`: `Guwahati -> Kolkata` (flight/train/bus).
A `gateway_transit` stop is a pass-through: it receives a transport search only, never an accommodation/experience/food search, unless the traveler actually overnights there — in which case it is reclassified `overnight` for that portion of the trip. When the first stop itself has practical direct transport from the source, the gateway and first stop coincide and no separate `gateway_transit` occurrence is created.

### Multi-Gateway Discovery & Candidate Options
Regions such as Ladakh, Arunachal Pradesh, Kashmir, or Rajasthan often have multiple potential access gateways. For example, a trip query like "Plan a trip to Ladakh from Kolkata" can enter via several distinct gateway corridors:

1. **Fly-In Gateway (Leh Airport - IXL)**:
   - Journey decomposition: `Kolkata -> Leh IXL Airport` (`source_to_gateway`, flight) -> `Leh Airport -> Leh City hotel` (`gateway_to_stop`, taxi/shuttle).
   - Trade-offs: Direct and fastest (2-3 hrs flight), but high-altitude arrival (11,500 ft) strictly requires 24–36 hrs mandatory rest and acclimatization in Leh City before high-pass travel (Pangong Tso / Khardung La).
2. **Overland Gateway via Srinagar / Kashmir (NH-1)**:
   - Journey decomposition: `Kolkata -> Srinagar` (`source_to_gateway`, flight/train) -> `Srinagar -> Kargil / Drass Valley -> Leh City` (`gateway_to_stop` & `internal_transfer`, scenic road drive).
   - Trade-offs: Gradual altitude gain through Drass Valley (smoother acclimatization), historic Zoji La pass route, but adds +2 days travel duration.
3. **Overland Gateway via Manali / Himachal (NH-3)**:
   - Journey decomposition: `Kolkata -> Manali` (or via Bhuntar/Chandigarh) (`source_to_gateway`, flight/train + road) -> `Manali -> Jispa / Sarchu -> Leh City` (`gateway_to_stop` & `internal_transfer`, high-altitude highway drive).
   - Trade-offs: Iconic high-mountain pass highway (Baralacha La, Lachung La, Tanglang La), gradual road ascent, but rugged road conditions and adds +2 days travel duration.
4. **Highway Hub Gateway (Delhi or Chandigarh)**:
   - Journey decomposition: `Kolkata -> Delhi / Chandigarh` (`source_to_gateway`, flight/train) -> `Delhi/Chandigarh -> Manali/Srinagar -> Leh City` (`gateway_to_stop` & `internal_transfer`, overland road trip/rental).
   - Trade-offs: Flexible starting hub for road trip / self-drive enthusiasts driving all the way into Ladakh.

`StopsDiscoveryAgent` discovers candidate transport gateways and formats up to `MAX_GATEWAY_OPTIONS` options (a configurable setting in `config.py`, defaulting to `2`):
- `option_id`: Unique identifier (e.g. `gw_opt_leh_flyin`, `gw_opt_srinagar_overland`, `gw_opt_manali_overland`).
- `gateway_name`: Human-readable option title (e.g. "Fly Direct to Leh Airport (IXL)", "Overland via Srinagar & Drass Valley", "Overland via Manali").
- `gateway_stop`: `TripStop` representing the gateway transit point (`stop_kind: "gateway_transit"`).
- `entry_legs`: List of entry `RouteLegPlan`s (`source_to_gateway`, `gateway_to_stop`).
- `exit_legs`: List of exit `RouteLegPlan`s (`stop_to_gateway`, `gateway_to_source`).
- `tradeoffs`: `GatewayTradeoffs` detailing `transit_duration_hours`, `cost_tier`, `scenic_value`, and `acclimatization_notes`.
- `is_recommended`: Boolean indicating the primary recommended route.

The recommended gateway option is automatically set as the active `route_plan` and `route_legs` for Layer 2 supply execution, while all discovered candidate options are preserved in `TripState.gateway_options` and `selected_gateway_option_id` for user evaluation or interactive UI switching.

### Day allocation semantics
Every overnight `TripStop` carries `nights` (an explicit count), `arrival_date`, and `departure_date`. `stops_by_day` resolves, for every day index in the trip, the day's `stop_id`, `is_travel_day` (true when a transfer leg occupies part or all of that day), `is_checkin_day`/`is_checkout_day`, and that day's concrete date. Nights across all overnight stops plus travel days must sum to the trip length — a 4-night stop must never receive 5 days of scheduled activities, and a checkout day's activity scheduling is capped to the pre-departure window rather than treated as a full free day. This allocation is computed once by `StopsDiscoveryAgent` and is the single source of truth every downstream agent reads from; no agent independently re-derives day counts from `nights` alone. `RouteLegPlan.planned_departure_date`/`planned_arrival_date` must agree with the date resolved from `RouteLegPlan.travel_day_index` via `stops_by_day` — `TransportSearchAgent` is the consumer that requires a concrete calendar date (not just an index) to perform date-specific searches, while which stop's night(s) a travel day displaces stays implicit via `stops_by_day[day].is_travel_day`/`is_checkin_day`/`is_checkout_day`, not a separate field on the leg.

### Stop-scoped food discovery
`FoodDiscoveryAgent` must consume `stops_by_day` rather than derive every day's location from the top-level `destination`. For each allocated day, it resolves `day.stop_id` in `stops`, uses that occurrence's name and coordinates as the food-search location, and includes the allocated calendar date in date-sensitive queries. A multi-stop route therefore searches near the active overnight stop, such as Bhalukpong, Dirang, or Tawang, instead of issuing one destination-wide search for Arunachal Pradesh. Pure `gateway_transit` occurrences are excluded from food searches unless the route explicitly reclassifies them as `overnight`.

For `route_discovery_status == "multi_stop_provisional"`, food output is keyed by stop occurrence and then day, for example `food_recommendations_by_stop[stop_id][day_date]`. Each returned recommendation carries its `stop_id` and `route_version`; repeated occurrences such as `dirang_01` and `dirang_02` must never share a result bucket merely because their display name is the same. The legacy day-keyed `food_recommendations` field is retained only for `single_destination` compatibility and must not be populated as a silent fallback for a multi-stop route.

### Transport search policy precedence
When more than one signal applies to a leg, `TransportSearchPolicy` resolves in this order (highest precedence first):
1. Explicit user preference stated in the query or profile (e.g. "I want to fly to X").
2. `self_drive_intent` — forces road/rental modes for internal legs when set.
3. `leg_type` default:
   - `source_to_gateway` & `gateway_to_source`: defaults to long-distance scheduled transport (`flight`, `train`, `intercity_bus`).
   - `gateway_to_stop` & `stop_to_gateway`: defaults to local/regional transit connection (`road`, `taxi`, `rental`, `local_transit`).
   - `internal_transfer`: defaults to inter-stop transfer (`road`, `private_car`, `local_transit`).
   - `country_transfer`: defaults to cross-border transit (`flight`, `train`, `intercity_bus`).
4. Regional heuristic default (e.g. remote Northeast India hill corridors are road-only regardless of `leg_type`).
5. Tool/data availability fallback — if the preferred mode returns no results, fall back to the next mode allowed by the policy and record `mode_downgraded: true` on that leg's result rather than failing silently.

### Provisional vs. verified terminology
Until Phase 6 external verification lands, all route/stop/segment output is **provisional** — this spec deliberately avoids "canonical" or "authoritative" for anything not yet externally verified. Layer 2–5 agents operate in explicit **best-effort-on-provisional-stops** mode: they trust the route contract's structure (order, stop identity, day allocation) enough to search and compile against it, but every output surface (state, API response, SSE progress event, itinerary) carries a `route_verification_status` of `"provisional"` so the product never silently presents an unverified route as final. "Authoritative"/"canonical" apply only once Phase 6 promotes a route to `"verified"`.

### Failed discovery vs. intentional single destination
`StopsDiscoveryAgent` always writes a `route_discovery_status`: `"single_destination"` (the query genuinely names one place; no multi-stop structure is needed), `"multi_stop_provisional"` (a route was successfully structured), or `"discovery_failed"` (parsing/LLM output could not produce a usable route). Only `"single_destination"` may use the legacy single-`destination` fallback fields. `"discovery_failed"` must never silently degrade into a single-destination itinerary — it routes to the existing clarification `interrupt()`/resume path (or a hard error) instead of producing a plausible-looking but wrong itinerary.

### Return route semantics
The return journey is always anchored from the **last overnight stop's** exit gateway back to `source` — e.g. `Tawang -> Guwahati -> Kolkata` (via `stop_to_gateway: Tawang -> Guwahati` and `gateway_to_source: Guwahati -> Kolkata`). Deterministic validation (Phase 6, item 25) rejects any route whose return leg originates at any stop other than the last overnight stop in sequence.

### Route revision
If the user changes trip parameters after a route already exists (e.g. "5 days" -> "8 days", or a different destination), the route plan increments a monotonic `route_version`. Every per-stop/per-leg keyed result (`stays_raw_by_stop`, `experiences_raw_by_stop`, transport/leg results, `reviews_summary`, budget line items) is tagged with the `route_version` it was computed against. A version bump invalidates results tagged with a stale version and re-triggers day (re)allocation plus the affected downstream searches; the compiler and any cache lookups must never mix results from two different route versions.

### Downstream contracts for loopholes 11–17
`StopsDiscoveryAgent` owns route structure; downstream agents enrich that structure without changing stop order, stop identity, day allocation, or return anchoring. Every multi-stop result envelope carries `route_version` plus its owning `stop_id`, `leg_id`, or both. A display name is descriptive data only and is never a result-map key.

- **Reviews:** review targets carry `stop_id`, `place_id` when available, and a stable `review_key` such as `{route_version}:{stop_id}:{place_id}`. If a provider has no `place_id`, use a deterministic fallback built from the stop occurrence, normalized venue name, and coordinates. `reviews_summary` is keyed by `review_key`, so identical venue names at different stops cannot overwrite one another.
- **Budget:** budget aggregation consumes `stays_pick_by_stop`, `route_legs`/per-leg transport recommendations, `food_recommendations_by_stop`, activities, permits, and route-wide self-drive costs. Accommodation is `price_per_night × stop.nights × travelers`; it is never one stay multiplied by total trip days. Per-stop and per-leg line items retain their source IDs, currency, and `route_version` before FX normalization, and the report exposes enough breakdown data to audit the total without double-counting.
- **Transport optimization:** the optimizer returns one recommendation record for every discovered `leg_id`, including an explicit no-result or policy-downgraded result when supply is unavailable, plus a separate route-wide aggregate and alternatives. It may rank options for a leg but cannot invent, remove, reorder, or replace route legs or stops.
- **Compiler:** compilation groups experiences, food, stays, reviews, and safety context by `stop_id` and allocated day before clustering. It creates exactly one segment per overnight stop occurrence, keeps day visits under their `parent_stop_id`, and uses only route stops and legs emitted by `StopsDiscoveryAgent`. LLM output is validated against these deterministic boundaries before it is returned.
- **Output metadata:** `TripSegment` and `Day` expose the route metadata needed by the final output (`stop_id`, linked `leg_id` where applicable, arrival/departure, check-in/check-out, and travel-day state). New fields are optional only for legacy `single_destination` responses; multi-stop responses must populate them.
- **Return and revision safety:** the active route's return leg originates at the last overnight `stop_id`, even when the final activity is a day visit. On route revision, stale versioned maps are cleared or filtered before any downstream node runs; the compiler rejects mixed-version inputs, and caches include `route_version` plus stop/leg identity in their keys.

**Steps**

### Phase 1: Contract and graph design
1. Define typed route models in `backend/app/models/stops.py` rather than using raw tuples/dicts:
   - `LegType` enum: `source_to_gateway`, `gateway_to_stop`, `internal_transfer`, `stop_to_gateway`, `gateway_to_source`, `country_transfer`.
   - `TripStop`: stable `stop_id` (unique per occurrence, e.g. `dirang_01`), `name`, optional coordinates, `stop_kind` (`"overnight"` | `"gateway_transit"`), `nights` (`0` for non-overnighted gateways), `arrival_date`, `departure_date`, `sequence`, and optional permit/altitude notes. `StopsDiscoveryAgent`'s scope is restricted to overnight itinerary stops and gateway transit points only — nearby excursions/attractions (e.g. Bumla Pass from Tawang) are not modeled as stops; they are discovered and scheduled later by `LocalExperiencesAgent` as experiences within the overnight stop's allocated days.
   - `GatewayTradeoffs`: `transit_duration_hours`, `cost_tier`, `scenic_value`, `acclimatization_notes`.
   - `GatewayOption`: `option_id`, `gateway_name`, `gateway_stop` (`TripStop`), `entry_legs` (`list[RouteLegPlan]`), `exit_legs` (`list[RouteLegPlan]`), `tradeoffs` (`GatewayTradeoffs`), `is_recommended` (`bool`).
   - `RouteLegPlan`: stable `leg_id`, origin `stop_id`, destination `stop_id`, `sequence`, `leg_type` (`LegType`), mandatory `travel_day_index` **and** mandatory `planned_departure_date`/`planned_arrival_date` (all three required — `travel_day_index` must resolve via `stops_by_day` to the same calendar date as the explicit fields, so `TransportSearchAgent` always has a concrete date to search against), and a `TransportSearchPolicy` (`allowed_modes`, `search_scope`, `requires_public_transport`, `mode_downgraded`) resolved per the precedence order in Core concepts.
   - Keep `source` and top-level `destination` for backward compatibility with `"single_destination"` trips. The route plan is the **provisional** multi-stop input for downstream agents — not "canonical" (see Provisional vs. verified terminology).
2. Extend `TripState`/`TripStateModel` in `backend/app/graph/state.py` with `route_plan`, `route_legs` (keyed by `leg_id`), `stops` (keyed by `stop_id`), `stops_by_day` (day-index -> allocation record per Day allocation semantics), `gateway_options` (`list[GatewayOption]`), `selected_gateway_option_id` (`str`), `route_discovery_status`, `route_version`, `route_verification_status`, and keyed per-stop/per-leg result fields (all keyed by `stop_id`/`leg_id`, never by name). Preserve the existing single-destination fields as compatibility fallbacks used only when `route_discovery_status == "single_destination"`.
3. Add `StopsDiscoveryAgent` in `backend/app/agents/stops_discovery_agent.py`. It belongs to Layer 1 and uses the parsed query, source, destination, dates, travel intent, and mock/real tool abstractions to produce a provisional ordered route plan:
   - Evaluates connectivity to the destination region and discovers up to `MAX_GATEWAY_OPTIONS` (from `config.py`) gateway routes (e.g. Leh IXL fly-in vs overland via Manali/Srinagar for Ladakh; Guwahati vs Dibrugarh for Arunachal).
   - Formulates gateway options with trade-offs (travel duration, cost, scenery, acclimatization).
   - Assigns explicit `leg_type`s to all route legs (`source_to_gateway`, `gateway_to_stop`, `internal_transfer`, `stop_to_gateway`, `gateway_to_source`).
   - Assigns a distinct `stop_id`/`leg_id` to every occurrence, computes day/night/arrival/departure per Day allocation semantics, and sets `route_discovery_status` (`"single_destination"` / `"multi_stop_provisional"` / `"discovery_failed"`). Output `route_verification_status` is always `"provisional"`.
4. Update `backend/app/graph/graph.py` so `stops_discovery` directly fans out to `transport_search`, `stay_search`, and `local_experiences` (plus `visa` as appropriate) only after a usable route is shaped. If `route_discovery_status == "discovery_failed"`, route to the existing clarification `interrupt()` path instead of continuing to Layer 2 — a failed discovery must never reach supply search with a fabricated fallback. `StopsDiscoveryAgent` is a Layer 1 prerequisite for supply search; unrelated Layer 1 agents may remain parallel where they do not consume the route plan. Ensure every downstream predecessor/barrier still fires exactly once.

### Phase 2: Route-aware Layer 2 supply search
5. Update `TransportSearchAgent` to consume `route_legs` keyed by `leg_id` and resolve each leg's `TransportSearchPolicy` per the precedence order in Core concepts (user preference > self-drive intent > `leg_type` default > regional heuristic > availability fallback), recording `mode_downgraded` when the preferred mode returns no results. Uses `leg_type` defaults to scope searches (`source_to_gateway`/`gateway_to_source` -> scheduled flights/trains; `gateway_to_stop`/`stop_to_gateway`/`internal_transfer` -> local road/transit). Search every required leg in parallel. Store results keyed by `leg_id`, never a display string. Retain the current source/destination fallback for `"single_destination"` trips.
6. Update `StaySearchAgent` to search accommodations only for stops with `stop_kind == "overnight"`, using each stop's `arrival_date`/`departure_date`/`nights`. Never search accommodation for `gateway_transit` stops unless reclassified `overnight`. Return `stays_raw_by_stop` keyed by `stop_id`, while retaining `stays_raw` fallback behavior for `"single_destination"` trips.
7. Update `LocalExperiencesAgent` to search each `overnight` stop independently in parallel (skip pure `gateway_transit` pass-throughs unless they are overnighted), keyed by `stop_id` — not stop name — so Dirang's two occurrences never collide. Every `Experience` produced also carries the producing `stop_id` (see Phase 4 model changes) so later clustering cannot misplace it into another stop's segment. Queries must include the stop name so Dirang waterfalls and Tawang attractions (including nearby excursions such as Bumla Pass) are found in their own local context rather than from one broad Arunachal search.
8. Extend Layer 2 tests with a deterministic Arunachal fixture/scenario proving: all route stops produce transport, stay, and experience searches; `gateway_transit` stops are excluded from stay search unless overnighted; repeated stops get distinct `stop_id`-keyed results; and a return leg anchored at the last overnight stop is present.

### Phase 3: Segment-aware analysis and enrichment
9. Update `TransportOptimizerAgent` to consume `route_legs` and raw results keyed by `leg_id`, returning a recommendation record for every discovered leg plus a route-wide aggregate recommendation and alternatives. Each per-leg record preserves origin/destination `stop_id`s, `leg_type`, planned dates, policy, and `route_version`; unavailable supply is represented explicitly rather than dropping the leg. Preserve route order and travel dates, and validate the LLM output against the discovered route so it cannot replace a stop with an unrelated hub or invent a new leg.
10. Update `StayAnalystAgent` to rank options independently for every `stop_id` with `stop_kind == "overnight"` and return `stays_shortlist_by_stop`, `stays_pick_by_stop`, and rationales keyed by `stop_id`, with each result tagged by `route_version` and the stop's arrival/departure dates. The single-stop output remains supported for `"single_destination"` trips.
11. Update `SelfDriveSearchAgent` to calculate route-wide distance, fuel, rental, toll, and permit implications from the ordered provisional route. Key route-leg distance/permit outputs by `leg_id` and tag them with `route_version`; keep whole-trip rental assumptions separate from per-leg transport recommendations so the same cost is not counted twice. Day-visit legs remain children of their `parent_stop_id` and cannot become return-route origins.
12. Update `ReviewsAgent` to carry `stop_id`, provider `place_id` when available, and `route_version` through target discovery and synthesis. Key `reviews_summary` by a stable `review_key` such as `{route_version}:{stop_id}:{place_id}`; when no provider ID exists, use a deterministic name-plus-coordinate fallback scoped to the stop occurrence. Never key by place name alone, and preserve the owning stop on both stay and experience review targets.
13. Update `FoodDiscoveryAgent` and `SafetyAgent` to operate per `stop_id`/day allocation instead of the single top-level `destination` string (this fixes the current `food_discovery_agent.py` behavior of building every day's search location from one destination). For every day in `stops_by_day`, resolve the active `stop_id`, skip non-overnight gateway pass-throughs, and query Places/Tavily using that stop's name or coordinates plus the allocated date. Return `food_recommendations_by_stop[stop_id][day_date]`, retain `stop_id` and `route_version` on each recommendation, and allow the legacy `food_recommendations` field only for `single_destination` trips. Safety includes stop-specific altitude, permit, road, weather, and venue context.
14. Update `BudgetPlannerAgent` to aggregate accommodation cost per `stop_id` — nights × that stop's chosen stay price — rather than one hotel price multiplied by total trip days (this fixes the current `budget_planner_agent.py` single-accommodation assumption). Aggregate transport recommendations per `leg_id`, per-stop activities/food/permits, and route-wide self-drive costs into auditable versioned line items before FX conversion; distinguish gateway transit from overnight accommodation and do not count whole-trip rental costs again as transport. Preserve currency, traveler count, and per-day accounting from `stops_by_day`.

### Phase 4: Multi-segment synthesis
15. Update `ItineraryCompilerAgent` to treat the route contract as the **provisional** structural source of truth (not "authoritative" pre-Phase-6 — see Provisional vs. verified terminology). Before the LLM call, partition experiences, food, stays, reviews, and safety context by `stop_id` and `stops_by_day`; then geo-cluster experiences only within each stop's allocated days. The compiler prompt must explicitly instruct the LLM to use only route stops produced by `StopsDiscoveryAgent`, never create new segments, never move activities across stop boundaries, and never turn a day visit into accommodation or a route leg. Build one `TripSegment` per **overnight stop occurrence** (two Dirang occurrences become two segments, never merged), attach that stop's stay shortlist and food, and run deterministic post-validation for stop IDs, day ownership, route version, and return-leg anchoring.
16. Extend the itinerary/transport models: `TripSegment`/`Day` (currently in `itinerary.py`, which has only a location and days, no stop identity) gain `stop_id`, `leg_id` (linked route leg where applicable), `arrival_date`/`departure_date`, `check_in`/`check_out`, and `is_travel_day`; `Experience`, `StayOption`, food outputs, review summaries, and transport recommendations gain the owning `stop_id`/`leg_id` and `route_version` where applicable. Keep existing `TripSegment`, `Day`, `StayOptions`, and `TransportRecommendation` JSON compatibility for `"single_destination"` trips, where these new fields are unset/null; multi-stop output must not omit them.
17. Update `_build_context`, compiler fallback/stub behavior, and transport injection for provisional multi-segment routes. Context must serialize the ordered route, `stops_by_day`, per-stop food/stays/experiences, per-leg transport, and `route_verification_status`; fallback stubs must be built from the route contract rather than the top-level destination. When `route_version` changes, invalidate stale per-stop/per-leg results and caches before downstream execution, then compile using only current-version data. Reject mixed-version inputs, preserve the last-overnight return anchor, and keep existing activity scheduling gates unchanged for now; route-stop verification and route feasibility validation remain deferred to Phase 6.

### Phase 5: Initial tests, documentation, and migration
18. Add unit tests for `StopsDiscoveryAgent`:
    - Gateway option discovery: test Ladakh query generates candidate gateway options (e.g. IXL fly-in vs overland) up to `MAX_GATEWAY_OPTIONS`, with trade-offs populated and primary option recommended.
    - Gateway resolution: test Kolkata -> Guwahati -> Bhalukpong with exact leg-type tagging (`source_to_gateway: Kolkata -> Guwahati`, `gateway_to_stop: Guwahati -> Bhalukpong`).
      - Distinct `stop_id`s for repeated stops (e.g. `dirang_01`, `dirang_02`).
      - Day/night/arrival/departure allocation correctness (nights + travel days sum to trip length, no overcounted activity days on a checkout day), including that every `RouteLegPlan.planned_departure_date`/`planned_arrival_date` agrees with the date resolved from its `travel_day_index` via `stops_by_day`.
      - Stop-scoped food discovery: a five-day Arunachal route queries food for the allocated Bhalukpong, Dirang, and Tawang days; both Dirang occurrences retain distinct `stop_id`-keyed result buckets; gateway-only occurrences are skipped; and no multi-stop food query falls back to the top-level destination.
      - Leg-type assignment including gateway legs (`source_to_gateway`, `gateway_to_stop`, `internal_transfer`, `stop_to_gateway`, `gateway_to_source`, `country_transfer`).
    - `route_discovery_status` coverage for all three states (`single_destination`, `multi_stop_provisional`, `discovery_failed`) with `discovery_failed` asserted to trigger clarification rather than a silent single-destination fallback, and domestic single-destination fallback. These tests cover route structuring only; they must not require Tavily, Google Places, geocoding, or route-distance validation.
19. Add focused downstream unit tests: same-named venues at different stops produce distinct review keys; a two-stop budget uses each stop's nights and does not multiply one stay across the whole trip; transport optimization returns one result per `leg_id` plus a route-wide aggregate; compiler input/output preserves stop boundaries and rejects invented or cross-stop activities; and segment/day models round-trip the new route metadata while legacy single-destination JSON remains compatible.
20. Update graph integration tests to assert ordering (`stops_discovery` before Layer 2), route-state contents keyed by `stop_id`/`leg_id`, `gateway_options` in state, per-stop results, stop-scoped food recommendations for each allocated overnight stop, final segments for a five-day Arunachal scenario (including two distinct Dirang segments), and a route-revision test ("5 days" -> "8 days") asserting stale `route_version`-tagged per-stop/per-leg results, including food, reviews, and budget inputs, are invalidated and recomputed rather than mixed with new ones. Assert the return leg starts at the last overnight stop even when the final activity is a Bumla Pass day visit. Keep existing Osaka/Leh/single-destination tests green.
21. Update `plan.md`, roadmap/docs, SSE agent progress labels, API/OpenAPI schemas, frontend types, map/route rendering, PDF template, and persistence serialization to expose `stop_id`/`leg_id`-keyed provisional stops/segments, gateway options, selected gateway option, route verification/discovery status, route version, review keys, per-stop budget breakdowns, and per-leg transport recommendations. Add cache-key scope for stop/leg-specific searches keyed by `route_version` plus `stop_id`/`leg_id`, not display name.
22. Run focused route-structure, downstream contract, and existing regression tests. Defer external stop verification, route feasibility tests, full route-quality evaluation, and validation-specific manual inspection to Phase 6.

### Phase 6: Deferred stop verification and route validation
23. Add Tavily grounding to `StopsDiscoveryAgent` to find supporting travel circuits, agency itineraries, and route evidence. Treat Tavily as route-relevance evidence, not as definitive geographic truth.
24. Add Google Places/geocoding verification to confirm each proposed stop exists, resolve canonical names and coordinates, and identify the country. Do not use Google Places alone to decide whether a stop belongs in the route.
25. Add a route/distance service or tool to estimate travel time between consecutive stops and validate whether the allocated days are realistic. Add permit, seasonal, and road-restriction sources where required.
26. Add deterministic validation for: duplicate `stop_id`s, invalid leg types, country mismatches, missing or misanchored return legs (a `stop_to_gateway` or return leg must never originate anywhere other than the last overnight stop), inconsistent day/night allocation (nights + travel days not summing to trip length), and route duration overflow.
27. Add validation-specific tests with mocked Tavily, Google Places, geocoding, and route-distance tools. Add low-confidence and infeasible-route behavior, including user clarification/resume before expensive downstream searches.
28. Update route models with verification metadata such as `verification_status` (promoting `route_verification_status` from `"provisional"` to `"verified"`), `sources`, `last_verified_at`, `confidence`, and route warnings. Only promote a provisional route to a verified one after this phase is implemented — "authoritative"/"canonical" language may only be used for `"verified"` routes.


**Relevant files**
- `/Users/mayukh/Documents/repos/TravelCopilot/backend/app/graph/graph.py` — insert `stops_discovery` node and gate Layer 2 without duplicating downstream executions.
- `/Users/mayukh/Documents/repos/TravelCopilot/backend/app/graph/state.py` — add route and keyed per-stop/per-leg state contracts plus compatibility defaults.
- `/Users/mayukh/Documents/repos/TravelCopilot/backend/app/models/stops.py` — new typed route/stop/day-allocation models.
- `/Users/mayukh/Documents/repos/TravelCopilot/backend/app/models/itinerary.py` — preserve and extend `TripSegment`/`Day` only for route metadata needed by the final output.
- `/Users/mayukh/Documents/repos/TravelCopilot/backend/app/models/transport.py` — add leg/route association only if the new route contract cannot be represented without ambiguous fields.
- `/Users/mayukh/Documents/repos/TravelCopilot/backend/app/agents/stops_discovery_agent.py` — new Layer 1 route and overnight-place discovery owner.
- `/Users/mayukh/Documents/repos/TravelCopilot/backend/app/agents/transport_search_agent.py` — per-route-leg transport supply search.
- `/Users/mayukh/Documents/repos/TravelCopilot/backend/app/agents/stay_search_agent.py` — per-overnight-stop accommodation search.
- `/Users/mayukh/Documents/repos/TravelCopilot/backend/app/agents/local_experiences_agent.py` — per-stop attraction/activity search and grounding.
- `/Users/mayukh/Documents/repos/TravelCopilot/backend/app/agents/transport_optimizer_agent.py`, `/Users/mayukh/Documents/repos/TravelCopilot/backend/app/agents/stay_analyst_agent.py`, `/Users/mayukh/Documents/repos/TravelCopilot/backend/app/agents/self_drive_search_agent.py` — route-aware analysis contracts.
- `/Users/mayukh/Documents/repos/TravelCopilot/backend/app/agents/reviews_agent.py`, `/Users/mayukh/Documents/repos/TravelCopilot/backend/app/agents/food_discovery_agent.py`, `/Users/mayukh/Documents/repos/TravelCopilot/backend/app/agents/safety_agent.py`, `/Users/mayukh/Documents/repos/TravelCopilot/backend/app/agents/budget_planner_agent.py` — per-stop enrichment and aggregation.
- `/Users/mayukh/Documents/repos/TravelCopilot/backend/app/agents/itinerary_compiler_agent.py` — provisional route-to-segments compilation and per-stop clustering.
- `/Users/mayukh/Documents/repos/TravelCopilot/backend/tests/unit/`, `/Users/mayukh/Documents/repos/TravelCopilot/backend/tests/integration/` — route, agent, graph, and regression tests.
- `/Users/mayukh/Documents/repos/TravelCopilot/plan.md`, `/Users/mayukh/Documents/repos/TravelCopilot/dev-roadmap.md` — architecture and delivery documentation.
- `/Users/mayukh/Documents/repos/TravelCopilot/backend/openapi.json`, frontend route/types/components, and PDF template — downstream serialized/output contract updates.

**Initial verification**
1. Unit-test `StopsDiscoveryAgent` with `5 days Arunachal Pradesh from Kolkata` and `7 days Ladakh from Kolkata`:
   - Assert resolved `gateway_transit` stops (e.g. Guwahati for Arunachal; Leh Airport, Srinagar/Drass, Manali, or Delhi/Chandigarh for Ladakh) are distinct from `source` and the first itinerary stop (e.g. Leh City or Bhalukpong).
   - Assert candidate gateway options are generated up to `MAX_GATEWAY_OPTIONS` with populated trade-offs (acclimatization notes, scenic value, transit duration, cost tier).
   - Verify specific Ladakh gateway decompositions:
     - Fly-In option: `source_to_gateway: Kolkata -> Leh IXL Airport`, `gateway_to_stop: Leh Airport -> Leh City hotel`.
     - Srinagar Overland option: `source_to_gateway: Kolkata -> Srinagar`, `gateway_to_stop: Srinagar -> Kargil/Drass -> Leh City`.
     - Manali Overland option: `source_to_gateway: Kolkata -> Manali`, `gateway_to_stop: Manali -> Sarchu/Jispa -> Leh City`.
     - Highway Hub option: `source_to_gateway: Kolkata -> Delhi/Chandigarh`, `gateway_to_stop: Delhi/Chandigarh -> Manali/Srinagar -> Leh City`.
   - Assert provisional ordered stops each have a unique `stop_id`, overnight allocation (nights/arrival/departure) sums correctly to trip duration, route legs/leg types use the 6 explicit leg types (`source_to_gateway`, `gateway_to_stop`, `internal_transfer`, `stop_to_gateway`, `gateway_to_source`), return legs are anchored at the last overnight stop's exit gateway, and `route_discovery_status == "multi_stop_provisional"`.
2. Unit-test Layer 2 with injected mock tools; assert parallel per-`stop_id`/per-`leg_id` calls and keyed outputs for Bhalukpong, Tawang, and both Dirang occurrences (distinct `stop_id`s).
3. Run the graph integration test; assert `stops_discovery` completes before Layer 2, a `discovery_failed` status routes to clarification instead of Layer 2, and the final itinerary contains ordered `TripSegment`s (one per overnight stop occurrence) with separate stays and local attractions.
4. Run existing regression tests for single-destination, international visa, self-drive, budget, and transport flows; run lint/type checks and full backend tests.
5. Do not assert external stop validity, route realism, permit correctness, or source grounding in this phase — all output remains `route_verification_status == "provisional"`.

**Deferred verification**
1. Assert Tavily route evidence, Google Places/geocoding confirmation, route-distance feasibility, deterministic route invariants (including duplicate `stop_id` and misanchored-return-leg checks), confidence, and source metadata; assert promotion from `route_verification_status: "provisional"` to `"verified"`.
2. Assert the compiler never places a Dirang attraction in Tawang's segment, and never invents places outside verified experience results.
3. Test low-confidence and infeasible routes pause for clarification before expensive Layer 2 searches.

**Decisions**
- `StopsDiscoveryAgent` belongs in Layer 1 because it produces destination/route intelligence needed by all supply agents; it is not a replacement for `TransportSearchAgent` or the compiler.
- Layer 2 must wait for `StopsDiscoveryAgent`; unrelated Layer 1 intelligence may remain parallel.
- Ordered typed route data is preferred over `list[tuple[str, str]]` and unstructured dicts; every stop/leg carries a stable `stop_id`/`leg_id` so repeated places and gateway transfers can never collide under one dict key.
- `leg_type` is updated to six explicit values (`source_to_gateway`, `gateway_to_stop`, `internal_transfer`, `stop_to_gateway`, `gateway_to_source`, `country_transfer`) to unambiguously distinguish long-distance transit to/from gateways from local transfers to itinerary stops.
- Multi-gateway discovery generates up to `MAX_GATEWAY_OPTIONS` candidate gateways (configurable via `config.py`, default `2`) with trade-offs (duration, cost, scenery, acclimatization) attached to `TripState.gateway_options`.
- The stop plan is the **provisional** structural source for overnight locations and day allocation (not "authoritative" until Phase 6 verification promotes it); the compiler may schedule activities within those boundaries but must not invent the corridor or move activities across stop boundaries.
- Transport search is policy-driven per leg, resolved by the precedence order in Core concepts (user preference > self-drive intent > leg_type default > regional heuristic > availability fallback). It searches only modes permitted by the route plan; geography alone must not trigger exhaustive flight/train/bus combinations.
- The access gateway is modeled as its own `gateway_transit` stop occurrence, separate from `source` and the first itinerary stop, so `source_to_gateway` never has to mean "source directly to an unreachable regional destination."
- `StopsDiscoveryAgent`'s scope is restricted to overnight itinerary stops and gateway transit points only; nearby excursions/attractions (e.g. Bumla Pass from Tawang) are not stops — they are discovered later by `LocalExperiencesAgent` as experiences scheduled within Tawang's allocated days, and never receive their own accommodation search, transport leg, or segment.
- A `route_discovery_status` of `discovery_failed` must never silently fall back to a single-destination itinerary; only a genuine `single_destination` query may use the legacy fallback fields.
- Existing single-destination behavior remains supported during migration.
- Initial scope includes backend route contracts, graph wiring, route-structure tests, docs, API serialization, frontend types/rendering, and PDF output because the provisional route state must survive end to end. It excludes external stop verification, route feasibility validation, booking execution, and live permit guarantees until Phase 6.

**Decisions**
- Universal global scope: The agent architecture works for any country, city, region, or place globally. When given an ambiguous query with an origin and destination, `StopsDiscoveryAgent` autonomously discovers the access gateways, intermediate stops, and candidate gateway options.
- Default five-day Arunachal policy: use a conservative agency-style circuit, e.g. Kolkata -> Guwahati (gateway) -> Bhalukpong -> Dirang -> Tawang -> Dirang -> Guwahati -> Kolkata; Bumla Pass is discovered by `LocalExperiencesAgent` as an excursion attraction under Tawang, not as a separate route stop; feasibility checks are deferred to Phase 6.
- Initial discovery method: structured LLM route proposal plus provisional deterministic shaping only (stop/leg identity assignment, day allocation, gateway resolution); Tavily, Google Places/geocoding, route-distance checks, and full deterministic validation are deferred to Phase 6.
- Low-confidence or infeasible route: pause for route confirmation before expensive Layer 2 searches, using the existing LangGraph interrupt/resume mechanism.
- Route revision (e.g. trip length changed mid-conversation) increments `route_version` and invalidates stale per-stop/per-leg results rather than mixing route structures — see Route revision in Core concepts.
