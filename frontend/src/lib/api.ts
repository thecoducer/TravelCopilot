import type {
  ChatTurn,
  ClarifyRequest,
  Itinerary,
  PlanRequest,
  SessionSummary,
  UserProfileData,
} from "@/lib/types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

async function assertOk(response: Response): Promise<Response> {
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new Error(`Request failed (${response.status}): ${body || response.statusText}`);
  }
  return response;
}

const jsonHeaders = { "Content-Type": "application/json" } as const;

/** Starts a new planning session and returns its SSE response stream. */
export async function planTrip(
  request: PlanRequest,
  signal?: AbortSignal,
): Promise<Response> {
  const headers: Record<string, string> = { ...jsonHeaders };
  if (request.username) {
    headers["X-Username"] = request.username;
  }
  const response = await fetch(`${API_BASE_URL}/api/trip/plan`, {
    method: "POST",
    headers,
    body: JSON.stringify(request),
    signal,
  });
  return assertOk(response);
}

/** Resumes a paused planning session with clarification answers. */
export async function clarifyTrip(
  sessionId: string,
  request: ClarifyRequest,
  signal?: AbortSignal,
): Promise<Response> {
  const response = await fetch(`${API_BASE_URL}/api/trip/${sessionId}/clarify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
    signal,
  });
  return assertOk(response);
}

export type PdfDownload = {
  blob: Blob;
  filename: string;
};

const FALLBACK_PDF_FILENAME = "itinerary.pdf";

/** Downloads the itinerary PDF, honoring the server's suggested filename. */
export async function downloadItineraryPdf(tripId: string): Promise<PdfDownload> {
  const response = await fetch(`${API_BASE_URL}/api/trip/${tripId}/pdf`, {
    method: "POST",
  });
  await assertOk(response);
  const blob = await response.blob();
  const filename = extractFilename(response.headers.get("Content-Disposition"));
  return { blob, filename };
}

function extractFilename(contentDisposition: string | null): string {
  if (!contentDisposition) {
    return FALLBACK_PDF_FILENAME;
  }
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(contentDisposition);
  return match?.[1] ? decodeURIComponent(match[1]) : FALLBACK_PDF_FILENAME;
}

// ── User identity, profile, and sessions ─────────────────────────────────────

/** Registers a username (or returns the existing one). No authentication. */
export async function registerUser(username: string): Promise<string> {
  const response = await fetch(`${API_BASE_URL}/api/user`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ username }),
  });
  await assertOk(response);
  const data = (await response.json()) as { username: string };
  return data.username;
}

/** Lists a user's chat sessions for the sidebar, newest first. */
export async function listSessions(username: string): Promise<SessionSummary[]> {
  const response = await fetch(`${API_BASE_URL}/api/user/${encodeURIComponent(username)}/sessions`);
  await assertOk(response);
  const data = (await response.json()) as { sessions: SessionSummary[] };
  return data.sessions;
}

export async function renameSession(
  username: string,
  sessionId: string,
  title: string,
): Promise<void> {
  const response = await fetch(
    `${API_BASE_URL}/api/user/${encodeURIComponent(username)}/sessions/${sessionId}`,
    { method: "PATCH", headers: jsonHeaders, body: JSON.stringify({ title }) },
  );
  await assertOk(response);
}

export async function deleteSession(username: string, sessionId: string): Promise<void> {
  const response = await fetch(
    `${API_BASE_URL}/api/user/${encodeURIComponent(username)}/sessions/${sessionId}`,
    { method: "DELETE" },
  );
  await assertOk(response);
}

export async function getProfile(username: string): Promise<UserProfileData | null> {
  const response = await fetch(`${API_BASE_URL}/api/user/${encodeURIComponent(username)}/profile`);
  await assertOk(response);
  const data = (await response.json()) as { profile: UserProfileData | null };
  return data.profile;
}

export async function saveProfile(
  username: string,
  profile: UserProfileData,
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/user/${encodeURIComponent(username)}/profile`, {
    method: "PUT",
    headers: jsonHeaders,
    body: JSON.stringify(profile),
  });
  await assertOk(response);
}

/** Loads a previously-saved itinerary for a session. */
export async function getSessionItinerary(sessionId: string): Promise<Itinerary | null> {
  const response = await fetch(`${API_BASE_URL}/api/trip/${sessionId}`);
  if (response.status === 404) {
    return null;
  }
  await assertOk(response);
  const data = (await response.json()) as { itinerary: Itinerary | null };
  return data.itinerary;
}

/** Loads the chat-turn history for a session. */
export async function getSessionTurns(sessionId: string): Promise<ChatTurn[]> {
  const response = await fetch(`${API_BASE_URL}/api/trip/${sessionId}/turns`);
  await assertOk(response);
  const data = (await response.json()) as { turns: ChatTurn[] };
  return data.turns;
}
