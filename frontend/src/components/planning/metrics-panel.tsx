import { formatDurationMs, formatTokenCount, formatUsd } from "@/lib/format";
import type { UsageSummaryEvent } from "@/lib/types";

type MetricsPanelProps = {
  usage: UsageSummaryEvent | null;
};

export function MetricsPanel({ usage }: MetricsPanelProps) {
  if (!usage) {
    return <p className="text-center text-xs text-faint">Usage metrics are finalizing.</p>;
  }

  const stats: { label: string; value: string }[] = [
    { label: "", value: `${formatTokenCount(usage.total_tokens)} tokens used` },
    { label: "Cost", value: formatUsd(usage.cost_usd) },
    { label: "Time", value: formatDurationMs(usage.total_duration_ms ?? 0) },
  ];

  return (
    <div className="flex flex-wrap items-center justify-center gap-x-2 gap-y-1 font-mono text-[0.7rem] tabular-nums text-faint">
      {stats.map((stat, index) => (
        <span key={stat.label} className="inline-flex items-center gap-2">
          {index > 0 ? <span aria-hidden="true" className="text-[0.55rem] text-faint/70">·</span> : null}
          <span>{stat.label} {stat.value}</span>
        </span>
      ))}
    </div>
  );
}
