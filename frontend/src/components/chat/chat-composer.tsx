"use client";

import { useRef, type KeyboardEvent } from "react";
import { ArrowUp } from "lucide-react";
import { Button } from "@/components/ui/button";

type ChatComposerProps = {
  onSend: (message: string) => void;
  disabled?: boolean;
  placeholder?: string;
};

export function ChatComposer({ onSend, disabled, placeholder }: ChatComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  function submit() {
    const value = textareaRef.current?.value.trim();
    if (!value || disabled) {
      return;
    }
    onSend(value);
    if (textareaRef.current) {
      textareaRef.current.value = "";
      textareaRef.current.style.height = "auto";
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  function autoGrow() {
    const el = textareaRef.current;
    if (!el) {
      return;
    }
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }

  return (
    <div className="flex items-end gap-2 rounded-lg border border-border-strong bg-surface p-2 shadow-sm focus-within:border-accent">
      <textarea
        ref={textareaRef}
        className="max-h-[200px] flex-1 resize-none bg-transparent px-2 py-1.5 text-sm text-fg outline-none placeholder:text-faint disabled:opacity-60"
        rows={1}
        placeholder={placeholder ?? "Where would you like to go?"}
        disabled={disabled}
        onKeyDown={handleKeyDown}
        onInput={autoGrow}
        aria-label="Trip planning message"
      />
      <Button
        type="button"
        size="icon"
        aria-label="Send message"
        disabled={disabled}
        onClick={submit}
      >
        <ArrowUp size={16} aria-hidden="true" />
      </Button>
    </div>
  );
}
