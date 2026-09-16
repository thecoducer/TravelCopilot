import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useElapsedTimer } from "@/hooks/use-elapsed-timer";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useElapsedTimer", () => {
  it("returns baseMs immediately when not running", () => {
    const { result } = renderHook(() => useElapsedTimer(1500, null));
    expect(result.current).toBe(1500);
  });

  it("ticks upward from baseMs while running", () => {
    const startedAt = Date.now();
    const { result } = renderHook(() => useElapsedTimer(0, startedAt));

    act(() => {
      vi.advanceTimersByTime(1000);
    });

    expect(result.current).toBeGreaterThanOrEqual(1000);
  });

  it("freezes at the accumulated value once runningSince becomes null (paused)", () => {
    const startedAt = Date.now();
    const { result, rerender } = renderHook(
      ({ baseMs, runningSince }: { baseMs: number; runningSince: number | null }) =>
        useElapsedTimer(baseMs, runningSince),
      { initialProps: { baseMs: 0, runningSince: startedAt as number | null } },
    );

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    const frozenAt = result.current;

    rerender({ baseMs: frozenAt, runningSince: null });
    act(() => {
      vi.advanceTimersByTime(5000);
    });

    expect(result.current).toBe(frozenAt);
  });

  it("resumes from the accumulated base without jumping the paused duration", () => {
    const { result, rerender } = renderHook(
      ({ baseMs, runningSince }: { baseMs: number; runningSince: number | null }) =>
        useElapsedTimer(baseMs, runningSince),
      { initialProps: { baseMs: 2000, runningSince: null as number | null } },
    );
    expect(result.current).toBe(2000);

    const resumedAt = Date.now();
    rerender({ baseMs: 2000, runningSince: resumedAt });
    act(() => {
      vi.advanceTimersByTime(500);
    });

    expect(result.current).toBeGreaterThanOrEqual(2500);
    expect(result.current).toBeLessThan(2600);
  });
});
