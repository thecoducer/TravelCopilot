"use client";

import { useState, type FormEvent } from "react";
import { ChevronDown } from "lucide-react";
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
    const visibleFields = new Set(prompts.map((prompt) => prompt.field));
    onSubmit(
      Object.fromEntries(
        Object.entries(values).filter(([field]) => visibleFields.has(field)),
      ),
    );
  }

  function skip(field: string) {
    setValue(field, "__skip__");
  }

  function setValue(field: string, value: string) {
    setValues((prev) => ({ ...prev, [field]: value }));
  }

  return (
    <SectionCard collapsible={false}>
      <form className="flex flex-col gap-4" onSubmit={handleSubmit}>
        {prompts.map((prompt) => (
          <label key={prompt.field} className="flex flex-col gap-1">
            <span className="text-sm font-semibold text-fg">{prompt.question}</span>
            <ClarificationInput
              prompt={prompt}
              value={values[prompt.field] ?? ""}
              onChange={(value) => setValue(prompt.field, value)}
            />
            {prompt.optional ? (
              <button
                type="button"
                className="self-start text-xs font-semibold text-muted underline-offset-2 hover:text-fg hover:underline"
                onClick={() => skip(prompt.field)}
              >
                {prompt.skip_label ?? "Skip"}
              </button>
            ) : null}
          </label>
        ))}
        <Button
          type="submit"
          variant="secondary"
          disabled={disabled}
          className="relative z-10 self-start rounded-full px-4 py-2 text-sm"
        >
          Continue
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
    required: !prompt.optional,
  };

  switch (prompt.input_type) {
    case "date":
      return <Input type="date" {...commonProps} />;
    case "number":
      return <Input type="number" {...commonProps} />;
    case "select":
      return (
        <span className="relative mt-1 block">
          <select
            {...commonProps}
            className="w-full appearance-none rounded-md border border-border-strong bg-canvas px-3 py-2 pr-10 text-sm text-fg outline-none focus:border-accent"
          >
            <option value="" disabled>
              Select an option
            </option>
            {prompt.options.map((option) => (
              <option key={option} value={option}>
                {formatOption(option)}
              </option>
            ))}
          </select>
          <ChevronDown
            size={16}
            aria-hidden="true"
            className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-muted"
          />
        </span>
      );
    default:
      return <Input type="text" {...commonProps} />;
  }
}

function formatOption(option: string): string {
  if (option.toLowerCase() === "mid") return "Mid / Standard";
  return option.charAt(0).toUpperCase() + option.slice(1);
}
