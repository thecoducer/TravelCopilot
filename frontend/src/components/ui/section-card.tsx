import type { ReactNode } from "react";

type SectionCardProps = {
  title?: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  collapsible?: boolean;
};

const cardClass =
  "rounded-lg border border-border bg-surface shadow-sm transition-[border-color,box-shadow,transform] duration-200 ease-out hover:border-border-strong hover:shadow-md";
const headerClass = "flex items-start justify-between gap-4 p-5";
const titleClass = "font-display text-[0.98rem] font-semibold tracking-tight text-fg";
const subtitleClass = "mt-1 text-[0.82rem] text-muted";

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
    if (!title) {
      return <section className={`${cardClass} p-5`}>{children}</section>;
    }

    return (
      <section className={cardClass}>
        <header className={headerClass}>
          <div>
            <h3 className={titleClass}>{title}</h3>
            {subtitle ? <p className={subtitleClass}>{subtitle}</p> : null}
          </div>
          {actions}
        </header>
        <div className="px-5 pb-5">{children}</div>
      </section>
    );
  }

  return (
    <details className={cardClass} open={defaultOpen}>
      <summary className={`${headerClass} cursor-pointer list-none [&::-webkit-details-marker]:hidden`}>
        <div>
          {title ? <span className={titleClass}>{title}</span> : null}
          {subtitle ? <p className={subtitleClass}>{subtitle}</p> : null}
        </div>
        {actions}
      </summary>
      <div className="px-5 pb-5">{children}</div>
    </details>
  );
}
