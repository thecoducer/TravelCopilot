# Multi-Day Trip Planning Loopholes

This document records design gaps that must be addressed while implementing multi-stop trip planning with `StopsDiscoveryAgent`.

## High Priority

### 1. Day Allocation Is Underspecified

The route plan mentions `stops_by_day`, but does not define arrival dates, departure dates, nights, travel days, or checkout-day behavior.

A route contract should make it possible to answer:

- Where does the traveler sleep each night?
- Which days are travel days?
- When does a stop begin and end?
- Can activities be scheduled before check-in or after checkout?

### 2. Gateway and Itinerary Stops Are Different

A region such as Arunachal Pradesh is not necessarily a transport endpoint. The plan must distinguish:

- User source: Kolkata
- Transport gateway: Guwahati
- First itinerary stop: Bhalukpong

Otherwise `source_to_destination` can incorrectly imply that Kolkata connects directly to Bhalukpong by the searched transport mode.

### 3. Stop Names Are Not Stable Identifiers

A route can visit the same place more than once, for example Dirang on the way to Tawang and again on the return. Dictionaries keyed only by stop name cannot distinguish these occurrences.

Add stable identifiers:

- `stop_id`: `dirang_01`, `dirang_02`
- `leg_id`: `leg_01`, `leg_02`

All stays, experiences, food, reviews, and transport results should use these identifiers.

### 4. Day Visits Need a Parent Stop

A day visit such as Bumla Pass needs explicit ownership:

- `visit_type`: `day_visit`
- `parent_stop_id`: Tawang
- outbound and return leg references
- planned date
- no accommodation unless explicitly configured

A day visit should not accidentally become an itinerary segment or receive a hotel search.

### 5. Transport Dates Are Missing

`RouteLegPlan` needs planned departure and arrival dates, or a `travel_day_index`. Without this, TransportSearchAgent cannot perform date-specific searches or know which accommodation nights are affected.

### 6. Multi-Stop Results Must Be Keyed Per Stop Occurrence

`Experience`, `StayOption`, reviews, and food recommendations currently do not consistently carry a stop identity. An attraction near Dirang could be assigned to Tawang after flattening or global clustering.

Every downstream result should retain its originating `stop_id` and, where useful, `leg_id`.

### 7. Failed Multi-Stop Discovery Must Not Silently Become Single-Destination Planning

Empty route fields can trigger existing fallbacks using the top-level `destination`. This may produce a plausible but incorrect itinerary.

The state must distinguish:

- intentional single-destination planning
- successful multi-stop discovery
- failed or incomplete multi-stop discovery

## Medium Priority

### 8. Transport Policy Override Order Is Undefined

The plan defines `TransportSearchPolicy`, but not precedence between user preference, self-drive intent, route policy, regional defaults, and tool availability.

Recommended precedence:

```text
explicit user preference
> self-drive intent
> route-specific policy
> regional default
```

### 9. Provisional Routes Can Trigger Expensive Searches

External stop validation is deferred, but a provisional route can still trigger hotel, attraction, food, and transport searches.

The initial implementation should label downstream results as best-effort and retain route uncertainty in state and output. It should not imply that the route has been externally verified.

### 10. Food Discovery Is Still Destination-Wide

The current FoodDiscoveryAgent builds every day location from the single top-level destination. It must consume stop-specific day assignments to find food near Bhalukpong, Dirang, Tawang, and other route locations.

Fix: make `FoodDiscoveryAgent` route-aware. For multi-stop plans, it should read `stops_by_day` and scope every search to the active `stop_id` for that day, plus the assigned date, instead of querying only the top-level destination. Example contract:

```python
for each day_index in stops_by_day:
    stop_id = stops_by_day[day_index].stop_id
    stop = stops[stop_id]
    location = stop.name if stop.stop_kind == "overnight" else stop.name
    query = f"best food near {stop.name} on {date}"
    results_by_stop[stop_id][day_date] = food_results
```

This keeps food results keyed by stop occurrence and prevents Dirang/Tawang or Bhalukpong/Tawang recommendations from collapsing into one global destination-wide list.

### 11. Reviews Can Collide by Place Name

`reviews_summary` is keyed by place name. Identically named venues in different stops can overwrite each other.

Use a stable composite key such as:

```text
{stop_id}:{place_id}
```

### 12. Budgeting Assumes One Accommodation

The current budget logic multiplies one selected hotel by all trip days. Multi-stop budgeting must sum accommodation by stop:

```text
sum(price_per_night_for_stop * nights_at_stop)
```

It must also aggregate transport per leg, permits, activities, food, and self-drive costs without double-counting.

### 13. Transport Optimization Is Still Single-Route

TransportOptimizerAgent currently produces one route recommendation. Multi-stop planning needs per-leg recommendations plus a route-wide aggregate while preserving the order supplied by StopsDiscoveryAgent.

The optimizer must not invent new route legs or replace discovered stops with unrelated hubs.

### 14. Compiler Can Still Invent or Reassign the Route

ItineraryCompilerAgent currently receives a global experience list and globally clusters it. With multi-stop planning, its prompt and inputs must state:

- use only provisional stops from StopsDiscoveryAgent
- do not create new segments
- do not move activities between stop boundaries
- do not assign accommodation to day visits

### 15. Existing Models Lack Route Metadata

`TripSegment` currently lacks fields for:

- stable `stop_id`
- arrival and departure metadata
- linked route leg
- check-in and checkout dates
- day-visit parent stop
- travel-day markers

These fields should be added only where required by the final output contract.

### 16. Return Route Anchor Is Ambiguous

For routes ending with a day visit, the return leg should normally begin at the overnight destination, not the day-visit location.

Example:

```text
Tawang -> gateway -> Kolkata
```

not:

```text
Bumla Pass -> Kolkata
```

### 17. Route Changes Need Versioning and Invalidation

If the user changes the trip from five days to eight days, day allocations and downstream results may become stale.

Route plans should have a version or hash. Transport, stay, experience, food, review, and budget results should be invalidated or recomputed when the route plan changes.

## Lower Priority

### 18. Missing Transport Policy Defaults

Each leg should have explicit allowed modes and search scope. Geography alone should not cause exhaustive flight, rail, bus, and road searches.

Examples:

- Arunachal internal transfer: road/private car
- Tawang to Bumla Pass day visit: road
- European country transfer: rail, bus, or flight according to user preference and route policy

### 19. No Route Revision Contract

The system needs a clear response when a user asks to add, remove, reorder, or extend a stop. It should regenerate affected legs and stop-specific results without unnecessarily discarding unrelated results.

### 20. Provisional and Approved Routes Need Different Statuses

The initial phase deliberately defers Tavily, Google Places, geocoding, route-distance, permit, and seasonal validation. The data model should distinguish:

- `provisional`: structured from query and LLM reasoning
- `approved`: externally grounded and feasibility-checked

The initial compiler should not present a provisional route as verified.

## Recommended Contract Additions

The route model should include:

```text
RoutePlan
  status: provisional | approved | needs_clarification
  version: int
  stops: list[TripStop]
  legs: list[RouteLegPlan]
  gateway_options: list[GatewayOption]
  selected_gateway_option_id: str
  day_assignments: list[DayAssignment]
  warnings: list[str]
  confidence: float | None

GatewayOption
  option_id: str
  gateway_name: str
  gateway_stop: TripStop
  entry_legs: list[RouteLegPlan]
  exit_legs: list[RouteLegPlan]
  tradeoffs: GatewayTradeoffs
  is_recommended: bool

GatewayTradeoffs
  transit_duration_hours: float | None
  cost_tier: str | None
  scenic_value: str | None
  acclimatization_notes: str | None

TripStop
  stop_id: str
  name: str
  stop_type: overnight | gateway_transit | day_visit
  parent_stop_id: str | None
  arrival_date: date | None
  departure_date: date | None
  nights: int

RouteLegPlan
  leg_id: str
  origin_stop_id: str | None
  destination_stop_id: str | None
  origin_name: str
  destination_name: str
  leg_type: source_to_gateway | gateway_to_stop | internal_transfer | stop_to_gateway | gateway_to_source | country_transfer
  travel_day: date | None
  allowed_modes: list[str]
```

## Implementation Priority

1. Add stable `stop_id` and `leg_id`.
2. Define exact arrival, departure, nights, and travel-day semantics.
3. Separate gateways from overnight and day-visit stops.
4. Key all downstream results by stop occurrence.
5. Update food, reviews, budgeting, transport optimization, and compilation for per-stop data.
6. Prevent failed multi-stop discovery from silently falling back to a single destination.
7. Add route versioning and invalidation before supporting itinerary revisions.
8. Add external verification and route feasibility validation later as the planned Phase 6.
