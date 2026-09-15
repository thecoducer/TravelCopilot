import type { TripDays } from "@/lib/types";

/**
 * Multi-night stays repeat the full StayOptions object on every covered day.
 * Returns the set of day numbers on which the stay should actually be rendered —
 * the first day of each distinct stop (by stop_id, falling back to location).
 */
export function daysToShowStay(tripDays: TripDays[]): Set<number> {
  const seen = new Set<string>();
  const show = new Set<number>();
  for (const day of tripDays) {
    if (!day.stay_options || day.stay_options.options.length === 0) {
      continue;
    }
    const key = day.stop_id ?? day.location;
    if (!seen.has(key)) {
      seen.add(key);
      show.add(day.day_number);
    }
  }
  return show;
}
