"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Accessibility,
  ArrowLeft,
  Check,
  ChevronDown,
  CircleUserRound,
  Compass,
  ForkKnife,
  Hotel,
  Save,
} from "lucide-react";
import { getProfile, saveProfile } from "@/lib/api";
import type { UserProfileData } from "@/lib/types";
import { useCurrentUser } from "@/hooks/use-current-user";
import { ErrorBanner } from "@/components/ui/error-banner";

const HOTEL_STYLES = ["hostel", "budget", "boutique", "business", "luxury"];
const TRAVEL_STYLES = ["adventure", "cultural", "luxury", "backpacker", "family"];
const FITNESS_LEVELS = ["low", "moderate", "high"];

const inputClass =
  "min-h-11 rounded-md border border-border-strong bg-canvas px-3 text-sm text-fg outline-none transition-[border-color,box-shadow] placeholder:text-faint focus:border-accent focus:ring-2 focus:ring-accent/25";

function toList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function fromList(value: string[] | undefined): string {
  return (value ?? []).join(", ");
}

export function ProfileForm() {
  const router = useRouter();
  const { username } = useCurrentUser();
  const [profile, setProfile] = useState<UserProfileData | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "saving" | "saved" | "error">(
    "loading",
  );

  useEffect(() => {
    if (!username) return;
    void (async () => {
      try {
        const existing = await getProfile(username);
        setProfile(existing ?? { user_id: username, username });
      } catch {
        setProfile({ user_id: username, username });
      } finally {
        setStatus("ready");
      }
    })();
  }, [username]);

  function update<K extends keyof UserProfileData>(key: K, value: UserProfileData[K]) {
    setProfile((current) => (current ? { ...current, [key]: value } : current));
    setStatus("ready");
  }

  async function handleSave() {
    if (!profile || !username) return;
    setStatus("saving");
    const payload: UserProfileData = {
      ...profile,
      user_id: username,
      username,
      food_preferences_configured:
        (profile.dietary_restrictions?.length ?? 0) > 0 ||
        (profile.preferred_cuisines?.length ?? 0) > 0,
    };
    try {
      await saveProfile(username, payload);
      setStatus("saved");
    } catch {
      setStatus("error");
    }
  }

  if (status === "loading" || !profile) {
    return <div className="flex h-dvh items-center justify-center text-muted">Loading profile…</div>;
  }

  return (
    <div className="h-dvh overflow-y-auto">
      <div className="mx-auto w-full max-w-[920px] px-5 pb-12 pt-16 sm:px-8 sm:pt-8">
      <header className="mb-10 grid grid-cols-[2.5rem_minmax(0,1fr)] items-start gap-x-4">
        <button
          className="inline-flex size-10 items-center justify-center rounded-md border border-border bg-surface text-fg transition-colors hover:border-border-strong hover:bg-canvas"
          onClick={() => router.push("/")}
          aria-label="Back to chats"
        >
          <ArrowLeft size={18} />
        </button>
        <div className="min-w-0 pt-0.5">
          <p className="mb-2 font-mono text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-summary-heading">
            Settings
          </p>
          <h1 className="font-display text-[clamp(1.65rem,4vw,2.2rem)] font-bold leading-tight tracking-tight text-fg">
            Personalize your trips
          </h1>
          <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-muted">
            Manage the preferences Travel Copilot uses to shape your recommendations, from places to stay to the food you seek out.
          </p>
        </div>
      </header>

      <div className="flex flex-col gap-4">
      <Section icon={<CircleUserRound size={17} />} title="Personal details">
        <Field label="Name">
          <input
            className={inputClass}
            value={profile.display_name ?? ""}
            onChange={(e) => update("display_name", e.target.value)}
          />
        </Field>
        <Field label="Nationality">
          <input
            className={inputClass}
            value={profile.nationality ?? ""}
            onChange={(e) => update("nationality", e.target.value)}
          />
        </Field>
      </Section>

      <Section icon={<Compass size={17} />} title="Travel preferences" subtitle="Set the pace, interests, and activity level you want reflected in your plans.">
        <Field label="Travel style">
          <SelectField
            value={profile.travel_style ?? ""}
            onChange={(e) => update("travel_style", e.target.value || null)}
            options={TRAVEL_STYLES}
          />
        </Field>
        <Field label="Fitness level">
          <SelectField
            value={profile.fitness_level ?? ""}
            onChange={(e) => update("fitness_level", e.target.value || null)}
            options={FITNESS_LEVELS}
          />
        </Field>
        <Field label="Interests">
          <input
            className={inputClass}
            value={fromList(profile.interests)}
            onChange={(e) => update("interests", toList(e.target.value))}
            placeholder="hiking, museums, street food"
          />
        </Field>
        <Field label="Altitude experience">
          <label className="flex items-center gap-2 text-[0.88rem] text-fg">
            <input
              type="checkbox"
              checked={Boolean(profile.altitude_experience)}
              onChange={(e) => update("altitude_experience", e.target.checked)}
            />
            Comfortable travelling above 3,000 m
          </label>
        </Field>
      </Section>

      <Section icon={<ForkKnife size={17} />} title="Food and dining" subtitle="Tell us what to avoid and what you enjoy so recommendations feel more considered.">
        <Field label="Dietary needs">
          <input
            className={inputClass}
            value={fromList(profile.dietary_restrictions)}
            onChange={(e) => update("dietary_restrictions", toList(e.target.value))}
            placeholder="vegetarian, no pork"
          />
        </Field>
        <Field label="Cuisines you enjoy">
          <input
            className={inputClass}
            value={fromList(profile.preferred_cuisines)}
            onChange={(e) => update("preferred_cuisines", toList(e.target.value))}
            placeholder="italian, japanese"
          />
        </Field>
      </Section>

      <Section icon={<Hotel size={17} />} title="Stays and transport" subtitle="Choose the accommodation and carrier preferences we should use by default.">
        <Field label="Accommodation style">
          <SelectField
            value={profile.hotel_style ?? ""}
            onChange={(e) => update("hotel_style", e.target.value || null)}
            options={HOTEL_STYLES}
          />
        </Field>
        <Field label="Hotel chains you like">
          <input
            className={inputClass}
            value={fromList(profile.preferred_hotel_chains)}
            onChange={(e) => update("preferred_hotel_chains", toList(e.target.value))}
          />
        </Field>
        <Field label="Airlines you prefer">
          <input
            className={inputClass}
            value={fromList(profile.preferred_airlines)}
            onChange={(e) => update("preferred_airlines", toList(e.target.value))}
          />
        </Field>
      </Section>

      <Section icon={<Accessibility size={17} />} title="Accessibility" subtitle="Add anything we should account for when planning movement, activities, and stays.">
        <Field label="Access needs">
          <input
            className={inputClass}
            value={fromList(profile.accessibility_needs)}
            onChange={(e) => update("accessibility_needs", toList(e.target.value))}
            placeholder="step-free access"
          />
        </Field>
      </Section>

      </div>

      <div className="mt-6 flex items-center justify-between gap-4 pt-3 max-[520px]:items-start max-[520px]:flex-col">
        <button
          className="inline-flex min-h-11 items-center gap-2 rounded-md bg-accent px-5 text-[0.88rem] font-semibold text-white transition-colors hover:bg-accent-hover disabled:cursor-wait disabled:opacity-60"
          onClick={handleSave}
          disabled={status === "saving"}
        >
          <Save size={16} />
          {status === "saving" ? "Saving settings…" : "Save settings"}
        </button>
        {status === "saved" ? (
          <span className="inline-flex items-center gap-1.5 font-mono text-[0.72rem] font-semibold uppercase tracking-[0.1em] text-success">
            <Check size={14} strokeWidth={2.5} /> Settings saved
          </span>
        ) : null}
        {status === "error" ? (
          <ErrorBanner message="Could not save. Try again." className="px-3 py-2" />
        ) : null}
      </div>
    </div>
    </div>
  );
}

function Section({ icon, title, subtitle, children }: { icon: React.ReactNode; title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <section className="py-6">
      <header className="mb-5 flex items-start gap-3">
        <span className="mt-0.5 inline-flex size-8 shrink-0 items-center justify-center rounded-md bg-accent-soft text-accent-hover">{icon}</span>
        <div>
          <h2 className="font-display text-[1rem] font-semibold tracking-tight text-fg">{title}</h2>
          {subtitle ? <p className="mt-1 text-[0.8rem] leading-relaxed text-muted">{subtitle}</p> : null}
        </div>
      </header>
      <div className="grid grid-cols-2 gap-x-4 gap-y-5 max-[640px]:grid-cols-1">{children}</div>
    </section>
  );
}

function SelectField({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: React.ChangeEventHandler<HTMLSelectElement>;
  options: string[];
}) {
  return (
    <span className="relative block">
      <select className={`${inputClass} w-full appearance-none pr-10 capitalize`} value={value} onChange={onChange}>
        <option value="">No preference</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
      <ChevronDown className="pointer-events-none absolute right-3 top-1/2 size-4 -translate-y-1/2 text-muted" aria-hidden="true" />
    </span>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-2">
      <span className="text-[0.78rem] font-semibold text-muted">{label}</span>
      {children}
    </label>
  );
}
