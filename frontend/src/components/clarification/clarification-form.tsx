"use client";

import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { SectionCard } from "@/components/ui/section-card";
import type { ClarificationPrompt } from "@/lib/types";
import styles from "./clarification-form.module.css";

type ClarificationFormProps = {
  prompts: ClarificationPrompt[];
  onSubmit: (answers: Record<string, string>) => void;
  disabled?: boolean;
};

export function ClarificationForm({ prompts, onSubmit, disabled }: ClarificationFormProps) {
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(prompts.map((prompt) => [prompt.field, prompt.extracted_value ?? ""])),
  );

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit(values);
  }

  function setValue(field: string, value: string) {
    setValues((prev) => ({ ...prev, [field]: value }));
  }

  return (
    <SectionCard title="A couple of quick questions" collapsible={false}>
      <form className={styles.form} onSubmit={handleSubmit}>
        {prompts.map((prompt) => (
          <label key={prompt.field} className={styles.field}>
            <span className={styles.question}>{prompt.question}</span>
            <span className={styles.reason}>{prompt.reason}</span>
            <ClarificationInput
              prompt={prompt}
              value={values[prompt.field] ?? ""}
              onChange={(value) => setValue(prompt.field, value)}
            />
          </label>
        ))}
        <Button type="submit" disabled={disabled}>
          Continue planning
        </Button>
      </form>
    </SectionCard>
  );
}

function ClarificationInput({
  prompt,
  value,
  onChange,
}: {
  prompt: ClarificationPrompt;
  value: string;
  onChange: (value: string) => void;
}) {
  const commonProps = {
    className: styles.input,
    value,
    onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
      onChange(event.target.value),
    required: true,
  };

  switch (prompt.input_type) {
    case "date":
      return <input type="date" {...commonProps} />;
    case "number":
      return <input type="number" {...commonProps} />;
    case "select":
      return (
        <select {...commonProps}>
          <option value="" disabled>
            Select an option
          </option>
          {prompt.options.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      );
    default:
      return <input type="text" {...commonProps} />;
  }
}
