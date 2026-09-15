"use client";

import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SectionCard } from "@/components/ui/section-card";
import type { ClarificationPrompt } from "@/lib/types";

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
      <form className="flex flex-col gap-4" onSubmit={handleSubmit}>
        {prompts.map((prompt) => (
          <label key={prompt.field} className="flex flex-col gap-1">
            <span className="text-sm font-semibold text-fg">{prompt.question}</span>
            <span className="text-xs text-muted">{prompt.reason}</span>
            <ClarificationInput
              prompt={prompt}
              value={values[prompt.field] ?? ""}
              onChange={(value) => setValue(prompt.field, value)}
            />
          </label>
        ))}
        <Button type="submit" disabled={disabled} className="self-start">
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
    className: "mt-1",
    value,
    onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
      onChange(event.target.value),
    required: true,
  };

  switch (prompt.input_type) {
    case "date":
      return <Input type="date" {...commonProps} />;
    case "number":
      return <Input type="number" {...commonProps} />;
    case "select":
      return (
        <select
          {...commonProps}
          className="mt-1 w-full rounded-md border border-border-strong bg-canvas px-3 py-2 text-sm text-fg outline-none focus:border-accent"
        >
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
      return <Input type="text" {...commonProps} />;
  }
}
