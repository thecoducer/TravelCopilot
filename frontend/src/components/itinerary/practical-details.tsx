"use client";

import { useState } from "react";
import { MoreExpander } from "@/components/ui/more-expander";
import type { Itinerary } from "@/lib/types";

const miniHeading = "mb-2 text-[0.8rem] font-bold uppercase tracking-wide text-faint";

type PracticalItem = {
  title: string;
  value?: string;
  checklist?: string[];
};

function Checklist({ items }: { items: string[] }) {
  return (
    <ul className="flex list-disc flex-col gap-1 pl-4 text-[0.88rem] text-fg">
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

function buildPracticalItems(itinerary: Itinerary): PracticalItem[] {
  const items: Array<PracticalItem | null> = [
    itinerary.connectivity_summary
      ? { title: "Connectivity", value: itinerary.connectivity_summary }
      : null,
    itinerary.language_tips ? { title: "Language tips", value: itinerary.language_tips } : null,
    itinerary.currency_tips ? { title: "Money tips", value: itinerary.currency_tips } : null,
    itinerary.safety_briefing ? { title: "Safety briefing", value: itinerary.safety_briefing } : null,
    itinerary.safety_section?.women_safety_notes
      ? { title: "Women's safety notes", value: itinerary.safety_section.women_safety_notes }
      : null,
    itinerary.safety_section?.medical_facilities
      ? { title: "Medical facilities", value: itinerary.safety_section.medical_facilities }
      : null,
    itinerary.packing_tips.length > 0
      ? { title: "Packing list", checklist: itinerary.packing_tips }
      : null,
  ];
  return items.filter((item): item is PracticalItem => item !== null);
}

export function PracticalDetails({ itinerary }: { itinerary: Itinerary }) {
  const [expanded, setExpanded] = useState(false);
  const practicalItems = buildPracticalItems(itinerary);

  if (practicalItems.length === 0) return null;

  const visibleItems = expanded ? practicalItems : practicalItems.slice(0, 2);

  return (
    <section className="flex flex-col gap-6 pb-8 pt-4">
      <header>
        <span className="text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-faint">
          Before you go
        </span>
        <h3 className="mt-1 font-display text-[1.7rem] font-semibold tracking-tight text-fg sm:text-[1.9rem]">
          Practical details
        </h3>
      </header>
      <div className="flex flex-col gap-4">
        {visibleItems.map((item) => (
          <div key={item.title}>
            <h5 className={miniHeading}>{item.title}</h5>
            {item.checklist ? (
              <Checklist items={item.checklist} />
            ) : (
              <p className="text-[0.88rem] leading-relaxed text-fg">{item.value}</p>
            )}
          </div>
        ))}
        {practicalItems.length > 2 ? (
          <div className="flex justify-center pt-1">
            <MoreExpander
              expanded={expanded}
              onClick={() => setExpanded((current) => !current)}
              collapsedLabel="Read more"
            />
          </div>
        ) : null}
      </div>
    </section>
  );
}