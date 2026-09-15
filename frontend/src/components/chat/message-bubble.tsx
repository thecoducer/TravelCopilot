import type { ReactNode } from "react";

type MessageBubbleProps = {
  role: "user" | "assistant";
  children: ReactNode;
};

export function MessageBubble({ role, children }: MessageBubbleProps) {
  const isUser = role === "user";
  return (
    <div className={`flex w-full ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={
          isUser
            ? "max-w-[min(640px,100%)] rounded-lg bg-accent px-4 py-3 text-white"
            : "w-full max-w-[1120px] text-fg"
        }
      >
        {children}
      </div>
    </div>
  );
}
