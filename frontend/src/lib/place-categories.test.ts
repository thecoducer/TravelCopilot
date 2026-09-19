import { describe, expect, it } from "vitest";
import { formatPlaceCategory } from "@/lib/place-categories";

describe("formatPlaceCategory", () => {
  it("uses the maintained label for tourist attractions", () => {
    expect(formatPlaceCategory("tourist_attraction")).toBe("Tourist attraction");
  });

  it("formats unknown snake-case categories safely", () => {
    expect(formatPlaceCategory("street_market")).toBe("Street Market");
  });
});