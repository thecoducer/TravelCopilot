"use client";

import { useEffect, useRef, useState } from "react";
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
  const navRef = useRef<HTMLElement>(null);
  const [activeDay, setActiveDay] = useState<number | null>(days[0]?.day_number ?? null);

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

    for (const day of days) {
      const el = document.getElementById(`day-${day.day_number}`);
      if (el) {
        observer.observe(el);
      }
    }
    return () => observer.disconnect();
  }, [days]);

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
        {days.map((day, index) => {
          const newStop = day.location !== days[index - 1]?.location;
          const isActive = activeDay === day.day_number;
          return (
            <li key={day.day_number}>
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
                  Day {day.day_number}
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
