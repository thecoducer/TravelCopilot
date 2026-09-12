import type { ClarifyRequest, PlanRequest } from "@/lib/types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

async function assertOk(response: Response): Promise<Response> {
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new Error(`Request failed (${response.status}): ${body || response.statusText}`);
  }
  return response;
}

/** Starts a new planning session and returns its SSE response stream. */
export async function planTrip(
  request: PlanRequest,
  signal?: AbortSignal,
): Promise<Response> {
  const response = await fetch(`${API_BASE_URL}/api/trip/plan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
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
