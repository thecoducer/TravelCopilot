import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MetricsPanel } from "@/components/planning/metrics-panel";
import type { UsageSummaryEvent } from "@/lib/types";

const usage: UsageSummaryEvent = {
  session_id: "sess-1",
  input_tokens: 1200,
  output_tokens: 340,
  reasoning_tokens: 96,
  cached_tokens: 200,
  total_tokens: 1540,
  cost_usd: 0.0123,
  total_duration_ms: 349570,
  llm_calls: 6,
};

describe("MetricsPanel", () => {
  it("shows a finalizing message while usage is unavailable", () => {
    render(<MetricsPanel usage={null} />);
    expect(screen.getByText("Usage metrics are finalizing.")).toBeInTheDocument();
  });

  it("renders only the subtle total token, cost, and duration summary", () => {
    render(<MetricsPanel usage={usage} />);

    expect(screen.getByText("1,540 tokens used")).toBeInTheDocument();
    expect(screen.getByText("Cost $0.0123")).toBeInTheDocument();
    expect(screen.getByText("Time 5m 50s")).toBeInTheDocument();
    expect(screen.queryByText(/Input|Output|Reasoning|Cached/)).not.toBeInTheDocument();
  });
});
