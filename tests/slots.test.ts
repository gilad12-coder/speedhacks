import { describe, expect, it } from "vitest";
import { firstFreeSlot, tourDurationMs } from "@/lib/slots";

const at = (hhmm: string) => Date.parse(`2026-11-03T${hhmm}:00-08:00`);
const notBefore = at("00:00");

describe("firstFreeSlot", () => {
  it("returns the first 45-minute slot clear of everyone's busy time", () => {
    const slot = firstFreeSlot({ start: at("10:00"), end: at("12:00") }, [{ start: at("10:00"), end: at("10:20") }], { notBefore });
    expect(slot).toEqual({ start: at("10:30"), end: at("11:15") });
  });

  it("shrinks the tour to fit a short window instead of finding nothing", () => {
    const window = { start: at("11:00"), end: at("11:30") };
    expect(tourDurationMs(window)).toBe(30 * 60_000);
    expect(firstFreeSlot(window, [], { notBefore })).toEqual(window);
  });

  it("returns null when the group is busy for the whole window", () => {
    expect(firstFreeSlot({ start: at("10:00"), end: at("11:00") }, [{ start: at("09:00"), end: at("12:00") }], { notBefore })).toBeNull();
  });
});
