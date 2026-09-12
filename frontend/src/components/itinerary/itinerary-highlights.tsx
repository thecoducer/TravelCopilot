import type { BudgetReport, TransportSection, VisaReport } from "@/lib/types";
import { formatUsd } from "@/lib/format";
import styles from "./itinerary-highlights.module.css";

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
    <ul className={styles.list}>
      {cards.map((card) => (
        <li key={card.label} className={styles.item}>
          <span className={styles.label}>{card.label}</span>
          <span className={styles.value}>{card.value}</span>
        </li>
      ))}
    </ul>
  );
}
