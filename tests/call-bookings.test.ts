import { beforeEach, expect, it, vi } from "vitest";
import type { AgentRun, Household } from "@/lib/types";

vi.mock("server-only", () => ({}));
const db = vi.hoisted(() => {
  type Stored = { start_at: Date; end_at: Date; calendar_event_ids: Record<string, string>; status: string };
  const state = { stored: null as Stored | null };
  const tx = Object.assign(async (parts: TemplateStringsArray, ...values: unknown[]) => {
    const query = parts.join("?");
    if (query.includes("select start_at")) return state.stored ? [state.stored] : [];
    if (query.includes("insert into tours")) state.stored = {
      start_at: values[2] as Date, end_at: values[3] as Date, status: values[4] as string,
      calendar_event_ids: values[5] as Record<string, string>,
    };
    return [];
  }, { json: (value: unknown) => value });
  return { state, sql: { begin: async (fn: (t: typeof tx) => Promise<unknown>) => fn(tx) } };
});
vi.mock("@/lib/db", () => ({ sql: db.sql }));
vi.mock("@/lib/google", () => ({ createConfirmedEvent: vi.fn() }));
import { createConfirmedEvent } from "@/lib/google";
import { syncCallBookings } from "@/lib/call-bookings";

const household = { id: "home", housemates: [{ id: "a", calendarConnected: true }, { id: "b", calendarConnected: true }] } as Household;
const run = { listings: [], bookedTours: [{ listingId: "rental", callId: "call", start: "2026-10-15T18:00:00-07:00", end: "2026-10-15T18:30:00-07:00", meetingAddress: "123 Main St", contactEvidence: { quote: "Booked." } }] } as unknown as AgentRun;

beforeEach(() => { db.state.stored = null; vi.resetAllMocks(); });

it("persists partial calendar success, then retries only the missing housemate", async () => {
  vi.mocked(createConfirmedEvent).mockResolvedValueOnce("event-a").mockRejectedValueOnce(new Error("network"));
  expect((await syncCallBookings(household, run))[0].status).toBe("pending");
  expect(db.state.stored?.calendar_event_ids).toEqual({ a: "event-a" });
  vi.mocked(createConfirmedEvent).mockResolvedValueOnce("event-b");
  expect((await syncCallBookings(household, run))[0].status).toBe("synced");
  expect((await syncCallBookings(household, run))[0].status).toBe("synced");
  expect(createConfirmedEvent).toHaveBeenCalledTimes(3);
  const calls = vi.mocked(createConfirmedEvent).mock.calls;
  expect(calls[1][1]).toBe(calls[2][1]); // stable ID for a timeout retry
  expect(calls[0][1]).toMatch(/^[a-f0-9]{64}$/);
});

it("does not overwrite an existing different appointment", async () => {
  db.state.stored = { start_at: new Date("2026-10-16T18:00:00-07:00"), end_at: new Date("2026-10-16T18:30:00-07:00"), calendar_event_ids: {}, status: "accepted" };
  expect((await syncCallBookings(household, run))[0].error).toContain("different viewing");
  expect(createConfirmedEvent).not.toHaveBeenCalled();
});

it("leaves an offer alone", async () => {
  expect(await syncCallBookings(household, { ...run, bookedTours: [] })).toEqual([]);
  expect(createConfirmedEvent).not.toHaveBeenCalled();
});
