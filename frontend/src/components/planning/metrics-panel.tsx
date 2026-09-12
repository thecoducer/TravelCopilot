import { SectionCard } from "@/components/ui/section-card";
import { formatLatencyMs, formatTokenCount, formatUsd } from "@/lib/format";
import { agentInfo } from "@/lib/agent-catalog";
import type { UsageSummaryEvent } from "@/lib/types";
import styles from "./metrics-panel.module.css";

type MetricsPanelProps = {
  usage: UsageSummaryEvent | null;
};

export function MetricsPanel({ usage }: MetricsPanelProps) {
  if (!usage) {
    return (
      <SectionCard title="Usage metrics" subtitle="Finalizing" defaultOpen={false}>
        <p className={styles.pending}>Token and cost totals are pending…</p>
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
      <div className={styles.totals}>
        <Metric label="Total tokens" value={formatTokenCount(usage.total_tokens)} />
        <Metric label="Total cost" value={formatUsd(usage.total_cost_usd)} />
        <Metric label="Total LLM latency" value={formatLatencyMs(usage.total_latency_ms)} />
      </div>

      {perAgentEntries.length > 0 ? (
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Agent</th>
              <th>Prompt</th>
              <th>Completion</th>
              <th>Total</th>
              <th>Cost</th>
              <th>LLM latency</th>
            </tr>
          </thead>
          <tbody>
            {perAgentEntries.map(([agent, row]) => (
              <tr key={agent}>
                <td>{agentInfo(agent).label}</td>
                <td>{formatTokenCount(row.prompt_tokens)}</td>
                <td>{formatTokenCount(row.completion_tokens)}</td>
                <td>{formatTokenCount(row.total_tokens)}</td>
                <td>{formatUsd(row.cost_usd)}</td>
                <td>{formatLatencyMs(row.latency_ms)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </SectionCard>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className={styles.metric}>
      <span className={styles.metricLabel}>{label}</span>
      <span className={styles.metricValue}>{value}</span>
    </div>
  );
}
