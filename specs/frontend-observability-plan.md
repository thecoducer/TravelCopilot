# Observable Next.js Frontend Plan

## Goal

Build the complete Travel Copilot frontend in the existing `frontend/` folder using Next.js App Router, TypeScript, and React. The first release is a clean, minimal ChatGPT/Claude-style trip-planning interface with:

- Chat input and send action
- Server-sent planning progress
- Exact currently running agent visibility, including parallel agents
- Safe descriptions of what the planner is doing
- Completion previews and elapsed timings
- Per-agent and total token, cost, LLM-latency, and wall-clock metrics
- Clarification questions and resume support
- Structured itinerary rendering
- Itinerary PDF download
- Local debug inspector for model prompts, tool payloads, and execution traces
- Production-ready Docker image and Compose integration

The frontend is entirely implemented in Next.js. No separate frontend framework, static HTML app, or parallel client application is planned.

## Confirmed Architecture

- Frontend framework: Next.js App Router with TypeScript and React
- Frontend runtime: Node.js 20.9+; use the current stable Next.js release when implementation begins
- Frontend source root: `frontend/`
- Browser API base URL: `NEXT_PUBLIC_API_BASE_URL`
- Local backend URL: `http://localhost:8000`
- Local frontend URL: `http://localhost:3001`
- Langfuse remains on port `3000`
- Frontend production container: multi-stage Node image running `next start`
- Frontend Docker service: expose port `3001` on the host and use container port `3000`
- Existing backend graph routing remains unchanged
- Backend observability changes are allowed where required by the frontend contract
- Debug inspection is opt-in, development-only by default, and disabled in production
- Private chain-of-thought is never exposed; the debug view shows observable execution records instead

## Implementation Steps

### 1. Complete the Next.js application

Replace the package-only frontend stub with a complete Next.js App Router application.

Use:

- Strict TypeScript
- `src/app` routing
- Server-rendered root layout and page shell
- Client Components only for interactive chat, stream state, timers, forms, and browser downloads
- `next/font` for intentional typography
- ESLint and type checking
- `@/*` import aliases
- `lucide-react` for familiar interface icons
- Vitest and Testing Library for focused frontend tests

Add scripts for:

- `dev`: local development on port `3001`
- `build`: production Next.js build
- `start`: production server on port `3000` inside the container
- `lint`
- `typecheck`
- `test`

The UI remains intentionally narrow: one planning conversation, one current itinerary, and one PDF action. History, profiles, authentication, maps, sharing, editing, attachments, feedback, dark mode, and offline persistence remain out of scope.

### 2. Build the minimal chat workspace

Create a responsive full-height workspace with a ChatGPT-like conversation flow:

- Restrained Travel Copilot header
- Centered conversation column
- Empty-state example prompts
- User message bubble
- Assistant planning response
- Sticky bottom composer
- Growing textarea
- Send button with accessible label and loading state
- Enter-to-send and Shift+Enter for a newline
- Visible focus states and keyboard navigation
- Mobile-safe layout with no horizontal overflow
- Reduced-motion support

Use a clean, minimal, modern Notion-inspired visual language:

- Warm off-white canvas
- Soft gray borders and surfaces
- Charcoal text with muted gray secondary text
- One restrained blue accent for primary actions and active states
- Compact, generous whitespace and quiet hierarchy
- Simple rounded controls and subtle shadows only where needed
- No purple gradients, heavy glass effects, decorative blobs, or dense dashboard chrome
- ChatGPT-like message alignment, composer placement, and response rhythm
- Avoid nested decorative cards; use bordered sections only for activity, metrics, and debug inspection

### 3. Extend backend SSE observability

Update `backend/app/routers/trip.py` as needed to expose truthful lifecycle events for both new and resumed graph streams.

Use LangGraph 1.2 unified v2 streaming with:

```python
stream_mode=["tasks", "updates"]
version="v2"
```

Normalize task events into SSE events:

```text
agent_start
agent_done
```

Each normal event should include safe observability data:

- `task_id`
- stable agent/node ID
- user-facing label
- phase/layer
- safe activity description
- session ID
- monotonic start/end timestamps or server timestamps
- wall-clock duration for completed agents
- parallel task context when available
- sanitized completion preview for completed nodes

Track task IDs rather than only agent names so repeated nodes and clarification loops are distinguishable. Maintain multiple active task IDs so parallel agents appear simultaneously in the UI.

Do not send:

- User prompts beyond the original chat message already displayed
- LLM prompts
- Tool arguments or tool responses
- Internal graph state
- Raw model output
- Partial structured JSON
- Chain-of-thought or private reasoning

### 3.1 Local debug inspection mode

Add an explicit development-only debug mode for testing the system under the hood. It must be disabled unless both of these conditions are true:

1. The backend enables a dedicated debug setting, such as `DEBUG_TRACE_ENABLED=true`.
2. The frontend is running in a non-production environment and the user explicitly opens the Debug inspector.

Do not use a query parameter or client-only flag as the sole protection. The backend must decide whether debug records may be emitted.

When enabled, add a collapsible `Debug inspector` panel to each planning run. It may show:

- Agent/node start and finish records
- Execution order and parallel task IDs
- Current phase and status
- Raw LLM request messages/prompts used by the agent
- Raw tool name, arguments, request payload, and result payload
- Model/provider name and request metadata that is safe for local testing
- Structured model response content when it is not private reasoning
- Token usage and timing attached to each call
- Errors, retries, and interruption/resume records

The backend must emit these records as a separate opt-in SSE event family, such as `debug_trace`, rather than mixing them with normal user-facing activity events. Keep the records typed, sequence-numbered, and scoped to the current session/task/call. The frontend should render them as an expandable chronological trace with JSON pretty-printing, copy controls, and clear labels for `prompt`, `tool payload`, `tool result`, `model output`, and `metrics`.

Redaction and safety requirements:

- Never expose private chain-of-thought, hidden reasoning, system secrets, API keys, authorization headers, cookies, database credentials, or provider credentials.
- If a provider returns a reasoning field, omit it rather than displaying it.
- Redact values matching secret-like keys before serialization.
- Cap record size and truncate oversized payloads with an explicit truncation marker.
- Add a clear `Debug mode is for local testing only` indicator.
- Do not persist debug traces to the itinerary, database, PDF, usage summary, or public share responses.
- Add a backend test proving debug events are absent when disabled and redacted when enabled.

This debug inspector is the supported substitute for displaying hidden chain-of-thought. The UI may show what the system received, called, returned, and measured, but never private internal reasoning.

Centralize node metadata in an observability catalog covering every graph node, including:

- `orchestrator`
- `stops_discovery`
- `visa`
- `transport_search`
- `stay_search`
- `local_experiences`
- `transport_optimizer`
- `stay_analyst`
- `self_drive_search`
- `reviews`
- `food_discovery`
- `budget_planner`
- `safety`
- `itinerary_compiler`
- `route_clarification`
- `food_clarification`
- `discovery_failed_end`

Example safe descriptions:

- Understanding your trip request
- Building the route
- Checking visa requirements
- Searching transport options
- Comparing places to stay
- Finding local experiences
- Checking safety and local conditions
- Balancing the budget
- Assembling the itinerary

### 4. Make usage metrics reliable

Update `backend/app/llm.py` with a bounded FIFO usage flush barrier.

The barrier should:

1. Enqueue a marker after graph execution.
2. Wait until all earlier usage writes have completed.
3. Return within a bounded timeout.
4. Log a warning and allow the response to complete if the timeout is reached.

Only publish finalized usage metrics after the barrier and include:

- Prompt tokens
- Completion tokens
- Total tokens
- Estimated USD cost
- LLM latency
- Per-agent breakdown
- Overall totals

Keep full node duration separate from LLM latency. Node duration includes tools, orchestration, and I/O; LLM latency measures only the model call.

When mock providers or model responses do not provide usage data, expose `0` or `unavailable` explicitly rather than inventing estimates.

### 5. Implement typed frontend stream handling

Add frontend-owned TypeScript types for:

- Plan requests
- Clarification requests
- `agent_start`
- `agent_done`
- `needs_clarification`
- `complete`
- `usage_summary`
- `error`
- Rendered itinerary fields

Use `fetch()` with `ReadableStream` for POST SSE requests because the planner endpoint accepts a request body. The parser must support:

- Fragmented frames across chunks
- Multiple events in one chunk
- CRLF and LF delimiters
- Retained trailing buffers
- Malformed event data
- Abort signals
- Stream-level errors

Implement API methods for:

- `POST /api/trip/plan`
- `POST /api/trip/{session_id}/clarify`
- `POST /api/trip/{trip_id}/pdf`

### 6. Implement planner and telemetry state

Use a focused reducer or hook with these states:

- `idle`
- `planning`
- `awaiting_clarification`
- `complete`
- `downloading`
- `error`

Track:

- User prompt
- Session ID
- Itinerary ID
- Current itinerary
- Active tasks by task ID
- Completed task activity in stream order
- Current elapsed time
- Known/completed task counts
- Final usage metrics
- PDF download state
- Error and retry state

Behavior:

- New top-level prompts create a fresh session.
- Clarification resumes the existing session.
- Active agents are added on `agent_start`.
- Only the matching task ID is removed on `agent_done`.
- Parallel agents remain visible together.
- Completion previews remain visible after an agent finishes.
- Stale streams are aborted on retry, replacement prompt, or unmount.
- Token and cost values remain `Pending` until authoritative usage data arrives.

### 7. Display live activity and metrics

Add an expandable `Activity and metrics` panel to the assistant response.

While planning, show:

- `Working now` section
- Current agent/node label
- Safe activity description
- Running elapsed timer
- Phase/layer
- Parallel agents at the same time
- Overall elapsed planning time

After completion, show:

- `Completed` section
- Sanitized completion preview
- Wall-clock duration per node
- Final token total
- Final cost
- Per-agent metric table
- Prompt, completion, and total tokens
- LLM latency
- Full node duration

Label the distinction between model latency and complete agent duration. Use `Pending` or `Unavailable` where exact data is not present.

Use `aria-live` announcements for meaningful status changes without repeatedly announcing every timer tick.

### 8. Render clarification and itinerary output

Render every backend clarification prompt inline and support:

- Text input
- Date input
- Number input
- Select input
- Multiple prompts in one clarification round

Resume the same session with the answers map.

On completion, render a concise itinerary containing:

- Title
- Source and destination route
- Dates and traveler count
- Segment headings
- Day headings
- Top-ranked morning, afternoon, and evening options
- Transport highlights
- Stay highlights
- Budget highlights
- Safety highlights
- Visa highlights when present

Enable the PDF action only after an itinerary ID exists. Download the PDF blob, respect the `Content-Disposition` filename with a safe fallback, revoke the object URL, and show failures inline.

### 9. Add frontend Docker support

Create `frontend/Dockerfile` using a multi-stage build:

1. Dependency stage installs from the lockfile.
2. Build stage runs the Next.js production build.
3. Runtime stage uses a small Node runtime image and runs `next start`.

Prefer Next.js standalone output if it reduces the runtime image and remains compatible with the chosen Next.js version. The image must:

- Run as a non-root user where practical
- Receive `NEXT_PUBLIC_API_BASE_URL` as a build/runtime configuration according to Next.js environment semantics
- Expose container port `3000`
- Provide a predictable production start command
- Avoid including development dependencies in the runtime layer

Add `.dockerignore` for:

- `node_modules`
- `.next`
- Test output
- Local environment files
- Editor metadata
- Logs

Add a frontend service to `docker-compose.yml`:

- Build from `./frontend`
- Map host `3001` to container `3000`
- Depend on the backend service where appropriate
- Pass the backend URL configured for browser access
- Avoid conflicting with Langfuse on host port `3000`

The browser must call the backend through a URL reachable from the browser, not a Docker-internal hostname. Document this distinction for local Compose use.

### 10. Update the Makefile

Keep existing backend targets intact and add frontend-specific targets:

- `frontend-install`
- `frontend-dev`
- `frontend-lint`
- `frontend-typecheck`
- `frontend-test`
- `frontend-build`
- `frontend-docker-build`

Update the existing `build` target to build both backend and frontend artifacts.

Update `verify` so it validates both applications:

1. Backend dependency lock check
2. Frontend dependency/install consistency check
3. Backend formatting
4. Backend lint and mypy
5. Frontend lint
6. Frontend typecheck
7. Backend tests
8. Frontend tests
9. Backend package and Docker build
10. Frontend production build
11. Frontend Docker build

`make verify` must be the final required gate. It must fail on any relevant frontend or backend error and must not silently skip the frontend.

Avoid making `verify` mutate source files where possible. If the existing repository convention retains formatting autofix in `verify`, document that behavior clearly and ensure the final validation reruns after any autofix.

### 11. Add focused tests

Backend tests:

- Task start precedes matching task completion
- Parallel tasks can be active simultaneously
- Repeated node invocations use distinct task IDs
- All catalog nodes have safe metadata
- Normal SSE contains no prompt/state/model debug data when debug mode is disabled
- Opt-in debug SSE contains redacted prompt and tool records only when enabled
- Debug records omit hidden reasoning and secret-like values
- Debug records are size-limited and marked when truncated
- Node duration is captured
- Usage flush succeeds
- Usage flush timeout does not hang the response
- Final per-agent and total metrics are emitted
- Clarification resume preserves lifecycle behavior

Frontend tests:

- SSE frame parsing across chunk boundaries
- Multiple SSE events per chunk
- Simultaneous active agents
- Start/done task reconciliation
- Running timers and completed durations
- Pending-to-final metrics transition
- Metric labels distinguish node duration from LLM latency
- Clarification submission and resume
- Itinerary rendering
- Error and retry behavior
- Cancellation
- PDF blob download and filename handling

## Relevant Files

- `backend/app/routers/trip.py`
- `backend/app/llm.py`
- `backend/app/config.py`
- `backend/app/observability/debug_trace.py`
- `backend/app/graph/graph.py`
- `backend/tests/unit/test_trip_router.py`
- `backend/tests/unit/test_llm.py`
- `frontend/package.json`
- `frontend/package-lock.json`
- `frontend/Dockerfile`
- `frontend/.dockerignore`
- `frontend/next.config.ts`
- `frontend/tsconfig.json`
- `frontend/eslint.config.mjs`
- `frontend/.env.example`
- `frontend/src/app/layout.tsx`
- `frontend/src/app/page.tsx`
- `frontend/src/app/globals.css`
- `frontend/src/components/travel-chat.tsx`
- `frontend/src/components/chat-composer.tsx`
- `frontend/src/components/planning-activity.tsx`
- `frontend/src/components/metrics-panel.tsx`
- `frontend/src/components/debug-inspector.tsx`
- `frontend/src/components/clarification-form.tsx`
- `frontend/src/components/itinerary-response.tsx`
- `frontend/src/hooks/use-trip-planner.ts`
- `frontend/src/lib/api.ts`
- `frontend/src/lib/sse.ts`
- `frontend/src/lib/types.ts`
- `frontend/src/lib/debug-trace.ts`
- `frontend/vitest.config.ts`
- `docker-compose.yml`
- `Makefile`
- `specs/frontend-observability-plan.md`

## Verification and Acceptance

1. Confirm the entire UI is built in Next.js under `frontend/`.
2. Run frontend install, lint, typecheck, tests, and production build.
3. Build the frontend Docker image successfully.
4. Build the backend Docker image successfully.
5. Start the Compose stack and verify the frontend is reachable at `http://localhost:3001`.
6. Verify the frontend can reach the backend at `http://localhost:8000` from the browser.
7. Submit a trip prompt and confirm multiple agent start events appear before completion events.
8. Confirm parallel agents are shown simultaneously.
9. Confirm the UI shows safe activity descriptions and completion previews.
10. Confirm finalized token, cost, LLM-latency, and node-duration metrics match the backend SSE usage summary.
11. Exercise clarification and resume behavior.
12. Download and open the generated itinerary PDF.
13. Run `make verify` from the repository root as the final gate and resolve all relevant errors before considering the work complete.

## Explicit Non-Goals

- No private chain-of-thought or hidden reasoning display
- Raw LLM prompts and tool payloads are available only through the explicitly enabled, local debug inspector
- No debug trace exposure in production or public itinerary responses
- No second narrative LLM call solely for frontend streaming
- No frontend framework other than Next.js
- No separate frontend container runtime outside the Next.js image
- No user accounts or authentication
- No itinerary history or sharing
- No maps or drag-and-drop editing
- No production deployment configuration beyond a runnable Docker image and Compose service
