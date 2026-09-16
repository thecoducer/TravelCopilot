"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { getProfile, saveProfile } from "@/lib/api";
import type { UserProfileData } from "@/lib/types";
import { useCurrentUser } from "@/hooks/use-current-user";
import { ErrorBanner } from "@/components/ui/error-banner";

const HOTEL_STYLES = ["hostel", "budget", "boutique", "business", "luxury"];
const TRAVEL_STYLES = ["adventure", "cultural", "luxury", "backpacker", "family"];
const FITNESS_LEVELS = ["low", "moderate", "high"];

const inputClass =
  "rounded-md border border-border-strong bg-canvas px-3 py-2 text-sm text-fg outline-none focus:border-accent focus:ring-2 focus:ring-accent/25";

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
    <div className="mx-auto h-dvh w-full max-w-[760px] overflow-y-auto px-5 py-6">
      <header className="mb-6 flex items-start gap-3">
        <button
          className="inline-flex size-10 shrink-0 items-center justify-center rounded-md border border-border bg-surface text-fg hover:bg-canvas"
          onClick={() => router.push("/")}
          aria-label="Back to chats"
        >
          <ArrowLeft size={18} />
        </button>
        <div>
          <h1 className="font-display text-[1.6rem] font-bold tracking-tight text-fg">Your profile</h1>
          <p className="mt-1 text-sm text-muted">
            Preferences here personalize every trip we plan for {username}.
          </p>
        </div>
      </header>

      <Section title="Identity">
        <Field label="Display name">
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
        <Field label="Passport country">
          <input
            className={inputClass}
            value={profile.passport_country ?? ""}
            onChange={(e) => update("passport_country", e.target.value)}
          />
        </Field>
      </Section>

      <Section title="Travel style">
        <Field label="Style">
          <select
            className={inputClass}
            value={profile.travel_style ?? ""}
            onChange={(e) => update("travel_style", e.target.value || null)}
          >
            <option value="">No preference</option>
            {TRAVEL_STYLES.map((style) => (
              <option key={style} value={style}>
                {style}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Fitness level">
          <select
            className={inputClass}
            value={profile.fitness_level ?? ""}
            onChange={(e) => update("fitness_level", e.target.value || null)}
          >
            <option value="">No preference</option>
            {FITNESS_LEVELS.map((level) => (
              <option key={level} value={level}>
                {level}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Interests (comma-separated)">
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

      <Section title="Food">
        <Field label="Dietary restrictions (comma-separated)">
          <input
            className={inputClass}
            value={fromList(profile.dietary_restrictions)}
            onChange={(e) => update("dietary_restrictions", toList(e.target.value))}
            placeholder="vegetarian, no pork"
          />
        </Field>
        <Field label="Preferred cuisines (comma-separated)">
          <input
            className={inputClass}
            value={fromList(profile.preferred_cuisines)}
            onChange={(e) => update("preferred_cuisines", toList(e.target.value))}
            placeholder="italian, japanese"
          />
        </Field>
      </Section>

      <Section title="Stay & transport">
        <Field label="Hotel style">
          <select
            className={inputClass}
            value={profile.hotel_style ?? ""}
            onChange={(e) => update("hotel_style", e.target.value || null)}
          >
            <option value="">No preference</option>
            {HOTEL_STYLES.map((style) => (
              <option key={style} value={style}>
                {style}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Preferred hotel chains (comma-separated)">
          <input
            className={inputClass}
            value={fromList(profile.preferred_hotel_chains)}
            onChange={(e) => update("preferred_hotel_chains", toList(e.target.value))}
          />
        </Field>
        <Field label="Preferred airlines (comma-separated)">
          <input
            className={inputClass}
            value={fromList(profile.preferred_airlines)}
            onChange={(e) => update("preferred_airlines", toList(e.target.value))}
          />
        </Field>
      </Section>

      <Section title="Accessibility">
        <Field label="Accessibility needs (comma-separated)">
          <input
            className={inputClass}
            value={fromList(profile.accessibility_needs)}
            onChange={(e) => update("accessibility_needs", toList(e.target.value))}
            placeholder="step-free access"
          />
        </Field>
      </Section>

      <div className="flex items-center gap-3 pb-6">
        <button
          className="rounded-md bg-accent px-5 py-3 text-[0.95rem] font-semibold text-white hover:bg-accent-hover disabled:opacity-60"
          onClick={handleSave}
          disabled={status === "saving"}
        >
          {status === "saving" ? "Saving…" : "Save profile"}
        </button>
        {status === "saved" ? <span className="text-[0.88rem] font-semibold text-success">Saved ✓</span> : null}
        {status === "error" ? (
          <ErrorBanner message="Could not save. Try again." className="px-3 py-2" />
        ) : null}
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-4 rounded-lg border border-border bg-surface p-5">
      <h2 className="mb-4 text-base font-bold text-fg">{title}</h2>
      <div className="grid grid-cols-2 gap-4 max-[640px]:grid-cols-1">{children}</div>
    </section>
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
