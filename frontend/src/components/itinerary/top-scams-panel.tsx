"use client";

import { useState } from "react";
import { MoreExpander } from "@/components/ui/more-expander";
import type { ScamEntry } from "@/lib/types";

type TopScamsPanelProps = {
  scams: ScamEntry[];
};

export function TopScamsPanel({ scams }: TopScamsPanelProps) {
  const [expanded, setExpanded] = useState(false);

  if (scams.length === 0) return null;
  const visibleScams = expanded ? scams : scams.slice(0, 2);

  return (
    <section className="flex flex-col gap-6 pb-8 pt-4">
      <header>
        <span className="text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-faint">
          Stay alert
        </span>
        <h3 className="mt-1 font-display text-[1.7rem] font-semibold tracking-tight text-fg sm:text-[1.9rem]">
          Top scams to avoid
        </h3>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted">
          Keep these common scams in mind while you travel, and pause before paying or sharing personal information.
        </p>
      </header>

      <div className="grid gap-4 sm:grid-cols-2">
        {visibleScams.map((scam, index) => (
          <article key={scam.name} className="border border-border border-l-4 border-l-danger bg-surface px-5 py-4 shadow-sm">
            <div className="flex items-start gap-3">
              <span className="inline-flex size-6 shrink-0 items-center justify-center rounded-full bg-danger-soft font-mono text-xs font-semibold text-danger">
                {index + 1}
              </span>
              <h4 className="pt-0.5 font-semibold text-fg">{scam.name}</h4>
            </div>
            <p className="mt-2 text-sm leading-relaxed text-muted">{scam.description}</p>
            <div className="mt-4 border-t border-border pt-3">
              <h5 className="text-[0.68rem] font-bold uppercase tracking-wide text-danger">How to avoid it</h5>
              <p className="mt-1 text-sm leading-relaxed text-fg">{scam.how_to_avoid}</p>
            </div>
          </article>
        ))}
      </div>
      {scams.length > 2 ? (
        <div className="relative -mt-8 flex justify-center pt-8">
          <MoreExpander expanded={expanded} onClick={() => setExpanded((current) => !current)} />
        </div>
      ) : null}
    </section>
  );
}
