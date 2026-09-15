import type { ReactNode } from "react";

type MessageBubbleProps = {
  role: "user" | "assistant";
  children: ReactNode;
};

export function MessageBubble({ role, children }: MessageBubbleProps) {
  const isUser = role === "user";
  return (
    <div className={`flex w-full ${isUser ? "justify-end" : "justify-center"}`}>
      <div
        className={
          isUser
            ? "max-w-[min(680px,100%)] rounded-[1.5rem] bg-chat-blue px-5 py-3.5 text-[0.94rem] text-white shadow-sm"
            : "w-full max-w-[980px] text-fg"
        }
      >
        {children}
      </div>
    </div>
  );
}
