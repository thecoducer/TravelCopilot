import type { TripDays } from "@/lib/types";

export type ItineraryDayGroup = {
  day: TripDays;
  dayNumbers: number[];
};

function comparableDay(day: TripDays) {
  const { day_number: _dayNumber, date: _date, ...details } = day;
  return details;
}

function hasSameDetails(first: TripDays, second: TripDays) {
  return JSON.stringify(comparableDay(first)) === JSON.stringify(comparableDay(second));
}

/** Groups consecutive calendar days when every rendered detail is identical. */
export function groupItineraryDays(days: TripDays[]): ItineraryDayGroup[] {
  const groups: ItineraryDayGroup[] = [];

  for (const day of days) {
    const previousGroup = groups[groups.length - 1];
    const previousDay = previousGroup?.day;
    const previousDayNumber = previousGroup?.dayNumbers.at(-1);

    if (
      previousGroup &&
      previousDay &&
      previousDayNumber !== undefined &&
      day.day_number === previousDayNumber + 1 &&
      hasSameDetails(previousDay, day)
    ) {
      previousGroup.dayNumbers.push(day.day_number);
    } else {
      groups.push({ day, dayNumbers: [day.day_number] });
    }
  }

  return groups;
}