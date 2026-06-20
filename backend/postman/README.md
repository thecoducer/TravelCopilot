# TravelCopilot Postman Collection

## Setup

1. Import `TripPlanner.postman_collection.json` into Postman.
2. Import `local.postman_environment.json` and set it as the active environment.
3. Start the backend: `make dev` (requires Docker).
4. Ensure `MOCK_EXTERNAL_APIS=true` in `.env` — no real API keys needed.

## Run Order

Run requests in this order so that environment variables (`trip_id`) are populated
correctly by earlier requests before later ones use them.

| # | Request | Folder |
|---|---------|--------|
| 1 | Health Check | Ops |
| 2 | Prometheus Metrics | Ops |
| 3 | Upsert Profile | User Profile |
| 4 | Get Profile | User Profile |
| 5 | Plan Trip — SSE (domestic Osaka) | Trip Planning |
| 6 | Plan Trip — Clarification gate | Trip Planning |
| 7 | Get Itinerary by Session | Trip Planning |
| 8 | Update Itinerary (reorder) | Trip Planning |
| 9 | Get Usage | Trip Planning |
| 10 | Generate PDF | Trip Planning |
| 11 | Submit Feedback | Trip Planning |
| 12 | Get Public Itinerary | Trip Planning |

## Expected Outputs

### 5 — Plan Trip (SSE, Osaka)
- Response is `text/event-stream`.
- Multiple `agent_done` events appear in layer order (0 → 5).
- Final `complete` event contains `itinerary_id` — stored automatically in `{{trip_id}}`.
- Final `usage_summary` event shows per-agent token counts.

### 6 — Clarification gate
- Response body includes `needs_clarification` event.
- No `complete` event (graph halted — client must re-POST with clarified query).
- `prompts` array contains at least one entry for `dates` or `travelers`.

### 10 — Generate PDF
- `Content-Type: application/pdf`.
- Response body is a binary PDF — use Postman "Save response to file" to inspect.
- All itinerary sections present: transport, accommodation, day plans, budget, visa.

### 11 — Submit Feedback
- Status 200 with `{"status": "ok"}`.
- If Langfuse is running at `http://localhost:3000`, a score appears on the trace.

## Environment Variables

| Variable | Description | Set by |
|----------|-------------|--------|
| `base_url` | Backend base URL | Manual (default: `http://localhost:8000`) |
| `session_id` | Session identifier | Manual (default: `test-session-postman`) |
| `trip_id` | Trip UUID | Auto-set by request #5 test script |
