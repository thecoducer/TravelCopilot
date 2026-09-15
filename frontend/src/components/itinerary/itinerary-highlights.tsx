import type { BudgetReport, TransportSection, VisaReport } from "@/lib/types";
import { formatUsd } from "@/lib/format";

type ItineraryHighlightsProps = {
  transportSection: TransportSection | null;
  budgetBreakdown: BudgetReport | null;
  safetyBriefing: string | null;
  visaSection: VisaReport | null;
};

/** Compact strip of transport, budget, safety, and visa highlights. */
export function ItineraryHighlights({
  transportSection,
  budgetBreakdown,
  safetyBriefing,
  visaSection,
}: ItineraryHighlightsProps) {
  const cards = [
    transportSection?.recommended?.rationale
      ? { label: "Transport", value: transportSection.recommended.rationale }
      : null,
    budgetBreakdown
      ? {
          label: "Budget",
          value: `${formatUsd(budgetBreakdown.total_estimated_cost)} · ${budgetBreakdown.vs_budget_verdict}`,
        }
      : null,
    safetyBriefing ? { label: "Safety", value: safetyBriefing } : null,
    visaSection
      ? {
          label: "Visa",
          value: visaSection.visa_required
            ? `Required — ${visaSection.visa_type ?? "check details"}`
            : "Not required",
        }
      : null,
  ].filter((card): card is { label: string; value: string } => card !== null);

  if (cards.length === 0) {
    return null;
  }

  return (
    <ul className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {cards.map((card) => (
        <li
          key={card.label}
          className="flex flex-col gap-1 rounded-md border border-border bg-surface p-3"
        >
          <span className="text-[0.7rem] font-semibold uppercase tracking-wide text-faint">
            {card.label}
          </span>
          <span className="line-clamp-3 text-[0.82rem] text-fg">{card.value}</span>
        </li>
      ))}
    </ul>
  );
}
