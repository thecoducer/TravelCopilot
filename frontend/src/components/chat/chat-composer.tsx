"use client";

import { useRef, type KeyboardEvent } from "react";
import { ArrowUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import styles from "./chat-composer.module.css";

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
    <div className={styles.composer}>
      <textarea
        ref={textareaRef}
        className={styles.textarea}
        rows={1}
        placeholder={placeholder ?? "Where would you like to go?"}
        disabled={disabled}
        onKeyDown={handleKeyDown}
        onInput={autoGrow}
        aria-label="Trip planning message"
      />
      <Button
        type="button"
        aria-label="Send message"
        disabled={disabled}
        onClick={submit}
        className={styles.sendButton}
      >
        <ArrowUp size={16} aria-hidden="true" />
      </Button>
    </div>
  );
}
