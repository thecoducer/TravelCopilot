import { SectionCard } from "@/components/ui/section-card";
import { formatLatencyMs, formatTokenCount, formatUsd } from "@/lib/format";
import { agentInfo } from "@/lib/agent-catalog";
import type { UsageSummaryEvent } from "@/lib/types";

type MetricsPanelProps = {
  usage: UsageSummaryEvent | null;
};

export function MetricsPanel({ usage }: MetricsPanelProps) {
  if (!usage) {
    return (
      <SectionCard title="Usage metrics" subtitle="Finalizing" defaultOpen={false}>
        <p className="text-sm text-muted">Token and cost totals are pending…</p>
      </SectionCard>
    );
  }

  const perAgentEntries = Object.entries(usage.per_agent);

  return (
    <SectionCard
      title="Usage metrics"
      subtitle={`${formatTokenCount(usage.total_tokens)} tokens · ${formatUsd(usage.total_cost_usd)}`}
      defaultOpen={false}
    >
      <div className="mb-4 flex flex-wrap gap-6">
        <Metric label="Total tokens" value={formatTokenCount(usage.total_tokens)} />
        <Metric label="Total cost" value={formatUsd(usage.total_cost_usd)} />
        <Metric label="Total LLM latency" value={formatLatencyMs(usage.total_latency_ms)} />
      </div>

      {perAgentEntries.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-faint">
                <th className="py-1 pr-3 font-semibold">Agent</th>
                <th className="py-1 pr-3 font-semibold">Prompt</th>
                <th className="py-1 pr-3 font-semibold">Completion</th>
                <th className="py-1 pr-3 font-semibold">Total</th>
                <th className="py-1 pr-3 font-semibold">Cost</th>
                <th className="py-1 font-semibold">LLM latency</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {perAgentEntries.map(([agent, row]) => (
                <tr key={agent} className="border-t border-border">
                  <td className="py-1 pr-3">{agentInfo(agent).label}</td>
                  <td className="py-1 pr-3">{formatTokenCount(row.prompt_tokens)}</td>
                  <td className="py-1 pr-3">{formatTokenCount(row.completion_tokens)}</td>
                  <td className="py-1 pr-3">{formatTokenCount(row.total_tokens)}</td>
                  <td className="py-1 pr-3">{formatUsd(row.cost_usd)}</td>
                  <td className="py-1">{formatLatencyMs(row.latency_ms)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </SectionCard>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs uppercase tracking-wide text-faint">{label}</span>
      <span className="text-[0.95rem] font-semibold tabular-nums text-fg">{value}</span>
    </div>
  );
}
