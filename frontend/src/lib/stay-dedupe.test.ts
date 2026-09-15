import { describe, expect, it } from "vitest";
import { daysToShowStay } from "@/lib/stay-dedupe";
import type { StayOptions, TripDays } from "@/lib/types";

function stayOptions(location: string): StayOptions {
  return {
    location,
    options: [{ name: `Hotel ${location}` }],
    recommended: null,
    notes: null,
  };
}

function day(dayNumber: number, location: string, stopId: string | null, withStay: boolean): TripDays {
  return {
    day_number: dayNumber,
    date: `2026-01-0${dayNumber}`,
    location,
    summary: null,
    morning: { slot: "morning", options: [], notes: null },
    afternoon: { slot: "afternoon", options: [], notes: null },
    evening: { slot: "evening", options: [], notes: null },
    food_options: [],
    stay_options: withStay ? stayOptions(location) : null,
    transport_options: [],
    safety_briefing: null,
    review_highlights: [],
    permits_required: [],
    altitude_meters: null,
    altitude_warning: null,
    connectivity: null,
    drive_notes: null,
    estimated_cost: null,
    currency_code: null,
    stop_id: stopId,
    is_travel_day: false,
  };
}

describe("daysToShowStay", () => {
  it("shows a multi-night stay only on the first day of the stop", () => {
    const days = [
      day(1, "Kyoto", "s1", true),
      day(2, "Kyoto", "s1", true),
      day(3, "Kyoto", "s1", true),
    ];
    expect([...daysToShowStay(days)]).toEqual([1]);
  });

  it("shows a new stay when the stop changes", () => {
    const days = [
      day(1, "Kyoto", "s1", true),
      day(2, "Kyoto", "s1", true),
      day(3, "Osaka", "s2", true),
    ];
    expect([...daysToShowStay(days)]).toEqual([1, 3]);
  });

  it("falls back to location when stop_id is absent", () => {
    const days = [day(1, "Goa", null, true), day(2, "Goa", null, true)];
    expect([...daysToShowStay(days)]).toEqual([1]);
  });

  it("skips days without a stay", () => {
    const days = [day(1, "Delhi", "s1", false), day(2, "Delhi", "s1", true)];
    expect([...daysToShowStay(days)]).toEqual([2]);
  });
});
