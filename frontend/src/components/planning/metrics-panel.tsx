import { formatLatencyMs, formatTokenCount, formatUsd } from "@/lib/format";
import type { UsageSummaryEvent } from "@/lib/types";

type MetricsPanelProps = {
  usage: UsageSummaryEvent | null;
};

export function MetricsPanel({ usage }: MetricsPanelProps) {
  if (!usage) {
    return <p className="text-center text-xs text-faint">Usage metrics are finalizing.</p>;
  }

  return (
    <p className="text-center text-xs tabular-nums text-faint">
      {formatTokenCount(usage.total_tokens)} tokens · {formatUsd(usage.total_cost_usd)} · {formatLatencyMs(usage.total_latency_ms)} latency
    </p>
  );
}
