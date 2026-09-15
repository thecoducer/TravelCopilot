"use client";

import { useRef, type KeyboardEvent } from "react";
import { ArrowUp, Square } from "lucide-react";
import { Button } from "@/components/ui/button";

type ChatComposerProps = {
  onSend: (message: string) => void;
  onStop: () => void;
  disabled?: boolean;
  isBusy?: boolean;
  placeholder?: string;
};

export function ChatComposer({ onSend, onStop, disabled, isBusy = false, placeholder }: ChatComposerProps) {
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
    <div className="flex items-end gap-2 rounded-[1.35rem] border border-border-strong/80 bg-surface/80 p-2 shadow-md backdrop-blur-xl transition-[border-color,background-color,box-shadow] duration-200 focus-within:border-chat-blue focus-within:bg-surface/90">
      <textarea
        ref={textareaRef}
        className="max-h-[200px] flex-1 resize-none bg-transparent px-3 py-2 text-[0.94rem] text-fg outline-none placeholder:text-faint disabled:opacity-60"
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
        className="!rounded-full !bg-chat-blue text-white shadow-md hover:!bg-chat-blue-hover dark:!bg-chat-blue dark:text-white dark:hover:!bg-chat-blue-hover"
        aria-label={isBusy ? "Stop planning" : "Send message"}
        disabled={isBusy ? false : disabled}
        onClick={isBusy ? onStop : submit}
      >
        {isBusy ? <Square size={15} fill="currentColor" aria-hidden="true" /> : <ArrowUp size={16} aria-hidden="true" />}
      </Button>
    </div>
  );
}
