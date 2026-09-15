"use client";

import { useEffect, useRef, useState } from "react";
import { groupItineraryDays } from "@/lib/day-grouping";
import type { TripDays } from "@/lib/types";
import { cn } from "@/lib/utils";

type ItineraryDayNavProps = {
  days: TripDays[];
};

function findScrollParent(node: HTMLElement | null): HTMLElement | null {
  let current = node?.parentElement ?? null;
  while (current) {
    const overflowY = window.getComputedStyle(current).overflowY;
    if (overflowY === "auto" || overflowY === "scroll") {
      return current;
    }
    current = current.parentElement;
  }
  return null;
}

export function ItineraryDayNav({ days }: ItineraryDayNavProps) {
  const dayGroups = groupItineraryDays(days);
  const navRef = useRef<HTMLElement>(null);
  const [activeDay, setActiveDay] = useState<number | null>(dayGroups[0]?.dayNumbers[0] ?? null);

  useEffect(() => {
    const root = findScrollParent(navRef.current);
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
        if (visible) {
          const day = Number(visible.target.getAttribute("data-day"));
          if (!Number.isNaN(day)) {
            setActiveDay(day);
          }
        }
      },
      { root, rootMargin: "-15% 0px -75% 0px", threshold: 0 },
    );

    for (const group of dayGroups) {
      const el = document.getElementById(`day-${group.dayNumbers[0]}`);
      if (el) {
        observer.observe(el);
      }
    }
    return () => observer.disconnect();
  }, [dayGroups]);

  if (days.length <= 1) {
    return null;
  }

  function scrollToDay(dayNumber: number) {
    document
      .getElementById(`day-${dayNumber}`)
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return (
    <nav
      ref={navRef}
      className="sticky top-0 max-h-[calc(100dvh-2rem)] self-start overflow-y-auto pr-2 max-[900px]:hidden"
      aria-label="Jump to day"
    >
      <span className="mb-2 block text-[0.7rem] font-bold uppercase tracking-wider text-faint">
        Itinerary
      </span>
      <ol className="flex flex-col gap-0.5 border-l-2 border-border">
        {dayGroups.map(({ day, dayNumbers }, index) => {
          const newStop = day.location !== dayGroups[index - 1]?.day.location;
          const isActive = dayNumbers.includes(activeDay ?? -1);
          return (
            <li key={dayNumbers[0]}>
              {newStop ? (
                <span className="ml-3 mt-3 block text-[0.72rem] font-bold text-muted">
                  {day.location}
                </span>
              ) : null}
              <button
                type="button"
                className={cn(
                  "-ml-0.5 flex w-full flex-col gap-px border-l-2 border-transparent px-3 py-1 text-left hover:border-border-strong",
                  isActive && "border-accent",
                )}
                onClick={() => scrollToDay(day.day_number)}
              >
                <span
                  className={cn(
                    "text-[0.85rem] font-semibold text-muted",
                    isActive && "text-accent-hover",
                  )}
                >
                  {dayNumbers.length > 1
                    ? `Days ${dayNumbers[0]}-${dayNumbers.at(-1)}`
                    : `Day ${day.day_number}`}
                </span>
                <span className="text-[0.72rem] text-faint">{day.date}</span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
