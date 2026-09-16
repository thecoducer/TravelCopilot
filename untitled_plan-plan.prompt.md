## Plan: Anchor Food Searches To Destination

Food recommendations are produced by `FoodDiscoveryAgent`, not `ItineraryCompilerService`. In real mode it queries Google Places Text Search through `search_places` and supplements results with Tavily via `tavily_search`; in mock mode `ToolFactory` replays recorded responses through `ToolResponseStore`.

The likely Leh/West Bengal bug is in the single-stop path: `FoodDiscoveryAgent.__call__` derives `areas` from the first comma-separated token of each `Experience.address`, then `_build_venue_pool` passes that area as the Places `location`. `PlaceSearchTool` appends `in {location}` when the location is absent from the query, allowing an upstream wrong address such as `Kolkata, West Bengal` to steer Google Places away from Leh. The compiler only selects already discovered venues.

**Steps**
1. Add a focused regression test in `backend/tests/unit/test_agents.py` using destination `Leh` and an experience whose address contains `West Bengal`; capture the Places call and assert the provider location remains `Leh` (and the resulting recommendations do not inherit the wrong locality). *First validation target.*
2. Adjust `FoodDiscoveryAgent._build_venue_pool` and its single-stop caller so experience-derived area text remains optional query context, while the provider `location` is always the validated destination for the single-stop route. Preserve the existing multi-stop behavior, where each overnight stop is explicitly searched by stop name.
3. Keep Tavily queries destination-qualified and review `_parse_tavily_venue` address assignment so supplemental venues are labeled with the searched destination/area rather than an untrusted upstream address where appropriate.
4. Run the focused food-agent test file or test class, then the relevant compiler/graph tests if available. Run backend lint/type checks for touched Python files.
5. Inspect recorded mock response fingerprints if the regression test needs mock-mode data; prefer injecting `AsyncMock` tools in the unit test so it verifies query/location construction without requiring network access or changing recordings.

**Relevant files**
- `/Users/mayukh/Documents/TravelCopilot/backend/app/agents/food_discovery_agent.py` — owns food/cafe discovery, area derivation, Google Places and Tavily calls.
- `/Users/mayukh/Documents/TravelCopilot/backend/app/tools/real/places_tools.py` — constructs the Google Places `textQuery` and currently lets `location` override/append to the query.
- `/Users/mayukh/Documents/TravelCopilot/backend/app/tools/factory.py` — selects real tools or recorded-response replay in mock mode.
- `/Users/mayukh/Documents/TravelCopilot/backend/app/services/itinerary_compiler_service.py` — downstream pool consumer only; no sourcing fix belongs here.
- `/Users/mayukh/Documents/TravelCopilot/backend/tests/unit/test_agents.py` — nearest existing `FoodDiscoveryAgent` tests.

**Verification**
1. Regression test proves a Leh single-stop search sends `location="Leh"` even when an experience address says West Bengal.
2. Existing empty-experience and saved-food-preferences tests continue to pass.
3. Multi-stop test coverage, if present, confirms searches remain keyed to each overnight stop.
4. Run `cd backend && uv run pytest tests/unit/test_agents.py -k FoodDiscoveryAgent -v` and `uv run ruff check app/agents/food_discovery_agent.py tests/unit/test_agents.py`.

**Decisions**
- Scope is limited to food-source location integrity; do not change itinerary compilation or unrelated experience geocoding.
- Preserve area/neighborhood text in the query where useful, but make the provider-level location destination-anchored for single-stop trips.
- Do not add real API calls or rewrite recorded tool responses.
