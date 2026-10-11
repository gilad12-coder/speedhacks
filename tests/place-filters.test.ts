import { describe, expect, it } from "vitest";
import { EMPTY_FILTERS, searchPlaces, type Query } from "@/lib/place-filters";
import type { AgentRun, Listing } from "@/lib/types";

const place = (id: string, over: Partial<Listing>): Listing => ({
  id,
  source: "live_search",
  sourceUrl: `https://example.com/${id}`,
  address: `${id} Main St`,
  neighborhood: "Mission",
  rentUsd: 3000,
  bedrooms: 2,
  bathrooms: 1,
  photoUrls: [],
  contact: { name: "", role: "landlord", phone: "" },
  commuteMinutes: null,
  status: "found",
  ...over,
});

const run: AgentRun = {
  householdId: "h",
  startedAt: "2026-10-01T00:00:00Z",
  finishedAt: null,
  listings: [
    place("a", { status: "verified", rentUsd: 3500 }),
    place("b", { status: "ruled_out", ruledOutReason: "scam", ruledOutNote: "Asked for a wire transfer", neighborhood: "Sunset" }),
    place("c", { status: "found", rentUsd: 4500 }),
  ],
  calls: [],
  checks: [],
  offeredWindows: [],
};

const query = (over: Partial<Query> = {}): Query => ({ text: "", stage: "all", filters: EMPTY_FILTERS, sort: "best", ...over });

describe("searchPlaces", () => {
  it("lists ruled-out places alongside the rest, furthest along first", () => {
    expect(searchPlaces(run, 4000, query()).results.map((l) => l.id)).toEqual(["a", "c", "b"]);
  });

  it("filters by stage and counts every stage against the other filters", () => {
    const out = searchPlaces(run, 4000, query({ stage: "ruled_out" }));
    expect(out.results.map((l) => l.id)).toEqual(["b"]);
    expect(out.stageCounts).toEqual({ all: 3, checking: 1, verified: 1, ruled_out: 1 });
  });

  it("counts each facet value against the other filters, not its own", () => {
    const out = searchPlaces(run, 4000, query({ filters: { ...EMPTY_FILTERS, neighborhoods: ["Mission"] } }));
    expect(out.results.map((l) => l.id)).toEqual(["a", "c"]);
    expect(out.facets.neighborhoods).toEqual([
      { value: "Mission", count: 2 },
      { value: "Sunset", count: 1 },
    ]);
    expect(out.facets.rent).toEqual([
      { value: "within", count: 1 },
      { value: "over", count: 1 },
    ]);
  });

  it("searches the ruled-out note as well as the address", () => {
    expect(searchPlaces(run, 4000, query({ text: "wire" })).results.map((l) => l.id)).toEqual(["b"]);
  });
});
