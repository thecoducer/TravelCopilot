import type { SafetyReport, TransportSection, VisaReport } from "@/lib/types";

type ItineraryHighlightsProps = {
  transportSection: TransportSection | null;
  visaSection: VisaReport | null;
  safetySection: SafetyReport | null;
  safetyBriefing: string | null;
};

/** Compact strip of transport, budget, safety, and visa highlights. */
export function ItineraryHighlights({
  transportSection,
  visaSection,
  safetySection,
  safetyBriefing,
}: ItineraryHighlightsProps) {
  const cards = [
    transportSection?.recommended?.rationale
      ? { label: "Transport", value: transportSection.recommended.rationale }
      : null,
    visaSection
      ? {
          label: "Visa",
          value: visaSection.visa_required
            ? `Required — ${visaSection.visa_type ?? "check details"}`
            : "Not required",
        }
      : null,
    safetySection
      ? {
          label: "Travel safety",
          value: safetyBriefing ?? `${safetySection.advisory_level} advisory for ${safetySection.destination}`,
          fullWidth: true,
        }
      : null,
  ].filter((card): card is { label: string; value: string; fullWidth?: boolean } => card !== null);

  if (cards.length === 0) {
    return null;
  }

  return (
    <ul className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {cards.map((card) => (
        <li
          key={card.label}
          className={`flex flex-col gap-1 border-l-2 border-accent px-3 py-2 ${
            card.fullWidth ? "col-span-2 sm:col-span-4" : ""
          }`}
        >
          <span className="text-[0.68rem] font-semibold uppercase tracking-[0.12em] text-faint">
            {card.label}
          </span>
          <span className="text-[0.82rem] leading-relaxed text-fg">{card.value}</span>
        </li>
      ))}
    </ul>
  );
}
