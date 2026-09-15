import type { ReactNode } from "react";

type SectionCardProps = {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  collapsible?: boolean;
};

const cardClass = "rounded-lg border border-border bg-surface shadow-sm";
const headerClass = "flex items-start justify-between gap-3 p-4";
const titleClass = "text-[0.95rem] font-semibold text-fg";
const subtitleClass = "mt-1 text-sm text-muted";

/** Bordered, optionally-collapsible section used for activity, metrics, and debug panels. */
export function SectionCard({
  title,
  subtitle,
  actions,
  children,
  defaultOpen = true,
  collapsible = true,
}: SectionCardProps) {
  if (!collapsible) {
    return (
      <section className={cardClass}>
        <header className={headerClass}>
          <div>
            <h3 className={titleClass}>{title}</h3>
            {subtitle ? <p className={subtitleClass}>{subtitle}</p> : null}
          </div>
          {actions}
        </header>
        <div className="px-4 pb-4">{children}</div>
      </section>
    );
  }

  return (
    <details className={cardClass} open={defaultOpen}>
      <summary className={`${headerClass} cursor-pointer list-none [&::-webkit-details-marker]:hidden`}>
        <div>
          <span className={titleClass}>{title}</span>
          {subtitle ? <p className={subtitleClass}>{subtitle}</p> : null}
        </div>
        {actions}
      </summary>
      <div className="px-4 pb-4">{children}</div>
    </details>
  );
}
