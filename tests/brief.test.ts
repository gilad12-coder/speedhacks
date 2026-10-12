import { describe, expect, it } from "vitest";
import { buildSearchBrief, detectConflicts } from "@/lib/brief";
import type { Housemate } from "@/lib/types";

const mate = (over: Partial<Housemate>): Housemate => ({
  id: over.name ?? "x",
  name: "x",
  location: "Berlin",
  maxBudgetUsd: 2000,
  commute: { destination: "Mountain View Caltrain", mode: "caltrain", modes: ["caltrain"], maxMinutes: 45 },
  mustHaves: [],
  wishes: [],
  dealBreakers: [],
  niceToHaves: [],
  moveInFrom: "2026-11-01",
  moveInTo: "2026-12-01",
  incomeBandUsd: { min: 75000, max: 150000 },
  calendarConnected: false,
  intakeComplete: true,
  ...over,
});

describe("brief", () => {
  it("keeps an explicit solo bedroom preference and leaves unspecified dates and commute flexible", () => {
    const brief = buildSearchBrief("personal", [mate({name:"Reed", minBedrooms:2, neighborhoods:["Civic Center"],
      moveInFrom:"", moveInTo:"", commute:{destination:"", mode:"walk", modes:[], maxMinutes:0}})]);
    expect(brief.occupants).toBe(1); expect(brief.minBedrooms).toBe(2);
    expect(brief.neighborhoods).toEqual(["Civic Center"]);
    expect(brief.moveInFrom).toBe(""); expect(brief.moveInTo).toBe(""); expect(brief.commute.destination).toBe("");
  });
  const group = [
    mate({ name: "Gilad", mustHaves: ["Pets allowed", "In-unit laundry"] }),
    mate({ name: "Lucy", maxBudgetUsd: 1800, dealBreakers: ["Pets allowed"], commute: { destination: "mountain view  caltrain", mode: "bus", modes: ["bus", "bike"], maxMinutes: 50 } }),
    mate({ name: "Dana", commute: { destination: "SoMa", mode: "metro", modes: ["metro"], maxMinutes: 30 } }),
  ];

  it("flags a need-vs-rule-out clash and leaves it out of the search", () => {
    const conflicts = detectConflicts(group);
    expect(conflicts.find((c) => c.field === "mustHaves")?.description).toContain("Pets allowed");
    const brief = buildSearchBrief("h1", group, 4);
    expect(brief.mustHaves).toEqual(["In-unit laundry"]);
    expect(brief.dealBreakers).toEqual([]);
  });

  it("sums budgets, uses household size and the most common commute", () => {
    const brief = buildSearchBrief("h1", group, 4);
    expect(brief.maxTotalRentUsd).toBe(5800);
    expect(brief.occupants).toBe(4);
    expect(brief.commute.destination).toBe("Mountain View Caltrain");
    expect(brief.commute.maxMinutes).toBe(45);
    expect(brief.commute.modes).toEqual(["caltrain", "bus", "bike"]);
  });

  it("passes interview wishes on, named only when there's a group", () => {
    const wishes = [mate({ name: "A", wishes: ["A quiet street"] }), mate({ name: "B", wishes: ["Lots of light"] })];
    expect(buildSearchBrief("h1", wishes).wishes).toEqual(["A: A quiet street", "B: Lots of light"]);
    expect(buildSearchBrief("h1", wishes.slice(0, 1)).wishes).toEqual(["A quiet street"]);
  });

  it("searches where most of the group wants to live and flags the rest", () => {
    const spread = [mate({ name: "A" }), mate({ name: "B", location: " berlin " }), mate({ name: "C", location: "Lisbon" })];
    expect(buildSearchBrief("h1", spread).location).toBe("Berlin");
    expect(detectConflicts(spread).find((c) => c.field === "location")?.suggestion).toContain("Berlin");
    expect(detectConflicts(group).some((c) => c.field === "location")).toBe(false);
  });
});
