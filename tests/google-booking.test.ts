import { beforeEach, afterEach, expect, it, vi } from "vitest";
vi.mock("server-only", () => ({}));
vi.mock("@/lib/crypto", () => ({ decrypt: (s: string) => s, encrypt: (s: string) => s }));
vi.mock("@/lib/env", () => ({ env: {} }));
vi.mock("@/lib/db", () => ({ sql: vi.fn(async () => [{ refresh: "test-refresh", access: "test-access", expires: new Date(Date.now() + 60_000) }]) }));
import { busyIntervals, createConfirmedEvent } from "@/lib/google";
const fetchMock = vi.fn<typeof fetch>();
const event = { summary: "Tour", location: "123 Main St", description: "Confirmed on call", start: new Date("2026-10-15T18:00:00-07:00"), end: new Date("2026-10-15T18:45:00-07:00") };
const saved = { id: "stable", start: { dateTime: event.start.toISOString() }, end: { dateTime: event.end.toISOString() } };
beforeEach(() => { fetchMock.mockReset(); vi.stubGlobal("fetch", fetchMock); });
afterEach(() => vi.unstubAllGlobals());

it("treats calendar-level errors as unknown instead of free", async () => {
  fetchMock.mockResolvedValue(Response.json({ calendars: { primary: { errors: [{ reason: "notFound" }] } } }));
  await expect(busyIntervals("a", { start: +event.start, end: +event.end })).rejects.toThrow("unknown");
});

it("finds an event written before a lost response without another insert or freebusy conflict", async () => {
  fetchMock.mockResolvedValue(Response.json(saved));
  expect(await createConfirmedEvent("a", "stable", event)).toBe("stable");
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(fetchMock.mock.calls[0][1]?.method).toBe("GET");
});

it("keeps the exact duration and recovers a duplicate-ID response", async () => {
  fetchMock.mockResolvedValueOnce(new Response(null, { status: 404 }))
    .mockResolvedValueOnce(Response.json({ calendars: { primary: { busy: [] } } }))
    .mockResolvedValueOnce(new Response(null, { status: 409 }))
    .mockResolvedValueOnce(Response.json(saved));
  expect(await createConfirmedEvent("a", "stable", event)).toBe("stable");
  const body = JSON.parse(String(fetchMock.mock.calls[2][1]?.body));
  expect(body.id).toBe("stable");
  expect(body.end.dateTime).toBe(event.end.toISOString());
});

it("preserves a contact booking for review when the calendar changed", async () => {
  fetchMock.mockResolvedValueOnce(new Response(null, { status: 404 }))
    .mockResolvedValueOnce(Response.json({ calendars: { primary: { busy: [{ start: event.start.toISOString(), end: event.end.toISOString() }] } } }));
  await expect(createConfirmedEvent("a", "stable", event)).rejects.toThrow("changed since the call");
  expect(fetchMock).toHaveBeenCalledTimes(2);
});
