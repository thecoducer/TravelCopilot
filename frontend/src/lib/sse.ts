import type { TripStreamEvent } from "@/lib/types";

export type RawSseEvent = {
  event: string;
  data: string;
};

/**
 * Parses a `text/event-stream` body into individual SSE frames.
 *
 * Handles frames split across chunk boundaries, multiple events within one
 * chunk, both CRLF and LF line endings, and retains a trailing partial frame
 * until more data (or stream end) completes it.
 */
export async function* parseSseStream(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<RawSseEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (value) {
        buffer += decoder.decode(value, { stream: true });
      }

      // SSE frames are separated by a blank line (\n\n, \r\n\r\n, or mixed).
      let boundary = findFrameBoundary(buffer);
      while (boundary !== -1) {
        const frame = buffer.slice(0, boundary.frameEnd);
        buffer = buffer.slice(boundary.nextStart);
        const parsed = parseFrame(frame);
        if (parsed) {
          yield parsed;
        }
        boundary = findFrameBoundary(buffer);
      }

      if (done) {
        buffer += decoder.decode();
        const finalParsed = parseFrame(buffer);
        if (finalParsed) {
          yield finalParsed;
        }
        return;
      }
    }
  } finally {
    reader.releaseLock();
  }
}

type FrameBoundary = { frameEnd: number; nextStart: number };

function findFrameBoundary(buffer: string): FrameBoundary | -1 {
  const lfIndex = buffer.indexOf("\n\n");
  const crlfIndex = buffer.indexOf("\r\n\r\n");

  if (crlfIndex !== -1 && (lfIndex === -1 || crlfIndex <= lfIndex)) {
    return { frameEnd: crlfIndex, nextStart: crlfIndex + 4 };
  }
  if (lfIndex !== -1) {
    return { frameEnd: lfIndex, nextStart: lfIndex + 2 };
  }
  return -1;
}

function parseFrame(frame: string): RawSseEvent | null {
  const lines = frame.split(/\r\n|\n/);
  let event = "message";
  const dataLines: string[] = [];

  for (const line of lines) {
    if (line === "" || line.startsWith(":")) {
      continue;
    }
    const separator = line.indexOf(":");
    const field = separator === -1 ? line : line.slice(0, separator);
    const value = separator === -1 ? "" : line.slice(separator + 1).replace(/^ /, "");

    if (field === "event") {
      event = value;
    } else if (field === "data") {
      dataLines.push(value);
    }
  }

  if (dataLines.length === 0) {
    return null;
  }
  return { event, data: dataLines.join("\n") };
}

/** Parses a raw SSE frame's JSON payload into a typed trip stream event. */
export function toTripStreamEvent(raw: RawSseEvent): TripStreamEvent | null {
  let data: unknown;
  try {
    data = JSON.parse(raw.data);
  } catch {
    console.warn("Discarding malformed SSE event data", raw.event);
    return null;
  }

  switch (raw.event) {
    case "agent_start":
    case "agent_done":
    case "needs_clarification":
    case "complete":
    case "usage_summary":
    case "error":
      return { event: raw.event, data } as TripStreamEvent;
    default:
      return null;
  }
}
