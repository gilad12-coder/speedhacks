import { beforeEach, expect, it, vi } from "vitest";
import { freeCallWindows } from "@/lib/slots";
vi.mock("server-only", () => ({}));
vi.mock("@/lib/agent-auth", () => ({ isAgent: vi.fn(() => true) }));
vi.mock("@/lib/households", () => ({ getHouseholdState: vi.fn() }));
vi.mock("@/lib/google", () => ({ busyIntervals: vi.fn(async () => []) }));
vi.mock("@/lib/db", () => ({ sql: vi.fn(async () => []) }));
import { isAgent } from "@/lib/agent-auth";
import { getHouseholdState } from "@/lib/households";
import { busyIntervals } from "@/lib/google";
import { GET } from "../app/api/agent/availability/[id]/route";
const request = () => new Request("https://app.example/api/agent/availability/home?timezone=America/Los_Angeles");
const context = () => ({ params: Promise.resolve({ id: "home" }) });
beforeEach(() => vi.clearAllMocks());

it("subtracts all busy blocks and limits windows to daytime across a DST change", () => {
  const now = Date.parse("2026-10-31T08:00:00-07:00");
  const busy = [{ start: Date.parse("2026-10-31T10:00:00-07:00"), end: Date.parse("2026-10-31T11:00:00-07:00") }];
  const windows = freeCallWindows(busy, now, "America/Los_Angeles", 2);
  expect(windows[0]).toEqual({ start: Date.parse("2026-10-31T09:00:00-07:00"), end: busy[0].start });
  expect(windows.some((w) => w.start === Date.parse("2026-11-01T09:00:00-08:00"))).toBe(true);
  expect(windows.every((w) => busy.every((b) => w.end <= b.start || w.start >= b.end))).toBe(true);
});

it("rejects unauthenticated availability reads before looking up household calendars", async () => {
  vi.mocked(isAgent).mockReturnValueOnce(false);
  expect((await GET(request(), context())).status).toBe(401);
  expect(getHouseholdState).not.toHaveBeenCalled();
});

it("does not authorize a partially connected household", async () => {
  vi.mocked(getHouseholdState).mockResolvedValueOnce({ searchRequestedAt: new Date(), household: { confirmed: true, expectedSize: 2, housemates: [{ calendarConnected: true }, { calendarConnected: false }] } } as Awaited<ReturnType<typeof getHouseholdState>>);
  expect((await (await GET(request(), context())).json()).enabled).toBe(false);
  expect(busyIntervals).not.toHaveBeenCalled();
});

it("does not authorize on a calendar outage", async () => {
  vi.mocked(getHouseholdState).mockResolvedValueOnce({ searchRequestedAt: new Date(), household: { confirmed: true, expectedSize: 1, housemates: [{ id: "a", calendarConnected: true }] } } as Awaited<ReturnType<typeof getHouseholdState>>);
  vi.mocked(busyIntervals).mockRejectedValueOnce(new Error("outage"));
  expect((await (await GET(request(), context())).json()).enabled).toBe(false);
});
