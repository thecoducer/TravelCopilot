import type { ReactNode } from "react";
import styles from "./section-card.module.css";

type SectionCardProps = {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  collapsible?: boolean;
};

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
      <section className={styles.card}>
        <header className={styles.header}>
          <div>
            <h3 className={styles.title}>{title}</h3>
            {subtitle ? <p className={styles.subtitle}>{subtitle}</p> : null}
          </div>
          {actions}
        </header>
        <div className={styles.body}>{children}</div>
      </section>
    );
  }

  return (
    <details className={styles.card} open={defaultOpen}>
      <summary className={styles.summary}>
        <div>
          <span className={styles.title}>{title}</span>
          {subtitle ? <p className={styles.subtitle}>{subtitle}</p> : null}
        </div>
        {actions}
      </summary>
      <div className={styles.body}>{children}</div>
    </details>
  );
}
