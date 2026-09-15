import { describe, expect, it } from "vitest";
import { groupItineraryDays } from "@/lib/day-grouping";
import type { TripDays } from "@/lib/types";

function day(dayNumber: number, location: string, summary = "Same plan"): TripDays {
  return {
    day_number: dayNumber,
    date: `2026-01-${String(dayNumber).padStart(2, "0")}`,
    location,
    summary,
    morning: { slot: "morning", options: [], notes: null },
    afternoon: { slot: "afternoon", options: [], notes: null },
    evening: { slot: "evening", options: [], notes: null },
    food_options: [],
    stay_options: null,
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
    stop_id: "stop-1",
    is_travel_day: false,
  };
}

describe("groupItineraryDays", () => {
  it("merges consecutive days with the same location and details", () => {
    const groups = groupItineraryDays([day(4, "Osaka"), day(5, "Osaka")]);

    expect(groups).toHaveLength(1);
    expect(groups[0]?.dayNumbers).toEqual([4, 5]);
  });

  it("keeps days separate when any itinerary detail differs", () => {
    const groups = groupItineraryDays([day(4, "Osaka"), day(5, "Osaka", "Different plan")]);

    expect(groups).toHaveLength(2);
  });

  it("does not merge non-consecutive days", () => {
    const groups = groupItineraryDays([day(4, "Osaka"), day(6, "Osaka")]);

    expect(groups).toHaveLength(2);
  });
});