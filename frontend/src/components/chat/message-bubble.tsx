import type { ReactNode } from "react";
import styles from "./message-bubble.module.css";

type MessageBubbleProps = {
  role: "user" | "assistant";
  children: ReactNode;
};

export function MessageBubble({ role, children }: MessageBubbleProps) {
  return (
    <div className={[styles.row, styles[role]].join(" ")}>
      <div className={styles.bubble}>{children}</div>
    </div>
  );
}
