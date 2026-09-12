"use client";

import styles from "./empty-state.module.css";

const EXAMPLE_PROMPTS = [
  "3 days in Osaka from Kolkata, love street food",
  "Leh to Nubra to Pangong, 6 days, self-drive",
  "Weekend trip from Mumbai to Pune",
  "10 days in Japan for two, mid-range budget",
];

export function EmptyState({ onExampleClick }: { onExampleClick: (prompt: string) => void }) {
  return (
    <div className={styles.wrapper}>
      <h1 className={styles.heading}>Where are you headed?</h1>
      <p className={styles.subheading}>
        Tell me your trip in a sentence — I&apos;ll plan the route, stays, food, and budget.
      </p>
      <ul className={styles.examples}>
        {EXAMPLE_PROMPTS.map((prompt) => (
          <li key={prompt}>
            <button
              type="button"
              className={styles.exampleButton}
              onClick={() => onExampleClick(prompt)}
            >
              {prompt}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
