import { describe, expect, it } from "vitest";
import { agentRunSchema } from "@/lib/schemas";

describe("research worker contract", () => {
  const run = { householdId: "test", startedAt: "2026-10-11T12:00:00-07:00", finishedAt: null,
    listings: [{ id: "other:1", source: "live_search", sourceUrl: "https://example.com/rental", address: "Rental address pending",
      neighborhood: "", rentUsd: null, bedrooms: null, bathrooms: null, photoUrls: [],
      contact: { name: "", role: "property_manager", phone: "" }, commuteMinutes: null, status: "found",
      research: { status: "unconfirmed", checkedAt: null, findings: [], facts: [],
        limitations: "Not enough evidence", medianComparableRent: null, comparableCount: 0 } }],
    calls: [], checks: [], offeredWindows: [], progress: ["Searching"], warnings: ["Commute unconfirmed"] };
  it("preserves unknowns, research evidence and worker progress", () => {
    const parsed = agentRunSchema.parse(run);
    expect(parsed.listings[0].rentUsd).toBeNull();
    expect(parsed.listings[0].research?.status).toBe("unconfirmed");
    expect(parsed.progress).toEqual(["Searching"]);
  });
  it("rejects positive checks without call evidence", () => {
    expect(agentRunSchema.safeParse({ ...run, checks: [{ listingId: "other:1", kind: "real", passed: true, summary: "Real", evidence: null }] }).success).toBe(false);
  });
  const agent = { callId: "1", t: 10, quote: "Please book that tour for Reed." };
  const contact = { callId: "1", t: 20, quote: "Confirmed, you are booked." };
  const bookedRun = { ...run,
    calls: [{ id: "1", listingId: "other:1", dialCallId: "provider", startedAt: run.startedAt,
      durationSec: 25, outcome: "answered", audioUrl: null, listingVerified: true,
      transcript: [{ t: 10, speaker: "agent", text: agent.quote }, { t: 20, speaker: "contact", text: contact.quote }] }],
    bookedTours: [{ listingId: "other:1", callId: "1", start: "2026-10-15T18:00:00-07:00", end: "2026-10-15T18:30:00-07:00",
      meetingAddress: "123 Main St", agentEvidence: agent, contactEvidence: contact }] };
  it("accepts separate call-confirmed appointments without converting offers", () => {
    const parsed = agentRunSchema.parse(bookedRun);
    expect(parsed.bookedTours).toHaveLength(1);
    expect(parsed.offeredWindows).toEqual([]);
  });
  it("rejects unknown verification, forged quotes, wrong speakers and duplicate bookings", () => {
    expect(agentRunSchema.safeParse({ ...bookedRun, calls: [{ ...bookedRun.calls[0], listingVerified: null }] }).success).toBe(false);
    expect(agentRunSchema.safeParse({ ...bookedRun, bookedTours: [{ ...bookedRun.bookedTours[0], contactEvidence: agent }] }).success).toBe(false);
    expect(agentRunSchema.safeParse({ ...bookedRun, bookedTours: [{ ...bookedRun.bookedTours[0], contactEvidence: { ...contact, quote: "Invented" } }] }).success).toBe(false);
    expect(agentRunSchema.safeParse({ ...bookedRun, bookedTours: [...bookedRun.bookedTours, ...bookedRun.bookedTours] }).success).toBe(false);
  });
});
