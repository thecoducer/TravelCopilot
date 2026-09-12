import { describe, expect, it } from "vitest";
import { parseSseStream, toTripStreamEvent } from "@/lib/sse";

function streamFromChunks(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  let index = 0;
  return new ReadableStream({
    pull(controller) {
      if (index < chunks.length) {
        controller.enqueue(encoder.encode(chunks[index]));
        index += 1;
      } else {
        controller.close();
      }
    },
  });
}

async function collect(stream: ReadableStream<Uint8Array>) {
  const events = [];
  for await (const event of parseSseStream(stream)) {
    events.push(event);
  }
  return events;
}

describe("parseSseStream", () => {
  it("parses a single complete frame", async () => {
    const stream = streamFromChunks([
      'event: agent_done\ndata: {"agent":"orchestrator"}\n\n',
    ]);
    const events = await collect(stream);
    expect(events).toEqual([
      { event: "agent_done", data: '{"agent":"orchestrator"}' },
    ]);
  });

  it("reassembles a frame split across multiple chunks", async () => {
    const stream = streamFromChunks([
      "event: agent_",
      'done\ndata: {"agent":"stay_search"}',
      "\n\n",
    ]);
    const events = await collect(stream);
    expect(events).toEqual([
      { event: "agent_done", data: '{"agent":"stay_search"}' },
    ]);
  });

  it("parses multiple events delivered in a single chunk", async () => {
    const stream = streamFromChunks([
      'event: agent_done\ndata: {"agent":"a"}\n\n' +
        'event: agent_done\ndata: {"agent":"b"}\n\n',
    ]);
    const events = await collect(stream);
    expect(events).toHaveLength(2);
    expect(events[0]?.data).toContain('"a"');
    expect(events[1]?.data).toContain('"b"');
  });

  it("supports CRLF line endings", async () => {
    const stream = streamFromChunks([
      'event: complete\r\ndata: {"itinerary_id":"1"}\r\n\r\n',
    ]);
    const events = await collect(stream);
    expect(events).toEqual([
      { event: "complete", data: '{"itinerary_id":"1"}' },
    ]);
  });

  it("parses a trailing frame with no closing blank line", async () => {
    const stream = streamFromChunks(['event: error\ndata: {"message":"boom"}']);
    const events = await collect(stream);
    expect(events).toEqual([{ event: "error", data: '{"message":"boom"}' }]);
  });

  it("ignores comment lines", async () => {
    const stream = streamFromChunks([
      ': keep-alive\nevent: agent_done\ndata: {"agent":"a"}\n\n',
    ]);
    const events = await collect(stream);
    expect(events).toHaveLength(1);
  });
});

describe("toTripStreamEvent", () => {
  it("returns a typed event for known event names", () => {
    const result = toTripStreamEvent({
      event: "agent_done",
      data: '{"agent":"orchestrator","layer":0,"session_id":"s1","preview":"Done"}',
    });
    expect(result?.event).toBe("agent_done");
  });

  it("returns null for malformed JSON instead of throwing", () => {
    const result = toTripStreamEvent({ event: "agent_done", data: "{not json" });
    expect(result).toBeNull();
  });

  it("returns null for unknown event names", () => {
    const result = toTripStreamEvent({ event: "ping", data: "{}" });
    expect(result).toBeNull();
  });
});
