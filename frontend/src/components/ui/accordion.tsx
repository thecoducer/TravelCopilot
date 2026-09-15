import type { ReactNode } from "react";

type AccordionProps = {
  title: string;
  eyebrow?: string;
  meta?: string;
  defaultOpen?: boolean;
  children: ReactNode;
};

/** A single collapsible panel built on native <details> for zero-JS disclosure. */
export function Accordion({ title, eyebrow, meta, defaultOpen = false, children }: AccordionProps) {
  return (
    <details className="group overflow-hidden rounded-lg border border-border bg-surface" open={defaultOpen}>
      <summary className="flex cursor-pointer list-none select-none items-center gap-3 p-4 [&::-webkit-details-marker]:hidden">
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          {eyebrow ? (
            <span className="text-[0.68rem] font-semibold uppercase tracking-wider text-faint">
              {eyebrow}
            </span>
          ) : null}
          <span className="font-display text-[1.05rem] font-semibold tracking-tight text-fg">
            {title}
          </span>
        </div>
        {meta ? <span className="whitespace-nowrap text-sm text-muted">{meta}</span> : null}
        <span className="text-lg leading-none text-faint transition-transform group-open:rotate-180" aria-hidden>
          ⌄
        </span>
      </summary>
      <div className="border-t border-border px-4 pb-4 pt-4">{children}</div>
    </details>
  );
}
