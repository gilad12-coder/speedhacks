import { NextResponse } from "next/server";
import { isAgent } from "@/lib/agent-auth";
import { getHouseholdState } from "@/lib/households";
import { busyIntervals } from "@/lib/google";
import { freeCallWindows } from "@/lib/slots";
import { sql } from "@/lib/db";

export const maxDuration = 30;

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  if (!isAgent(request)) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const { id } = await params;
  const state = await getHouseholdState(id);
  if (!state) return NextResponse.json({ error: "unknown_household" }, { status: 404 });
  const now = Date.now();
  const disabled = (reason: string) => NextResponse.json({ enabled: false, windows: [], checked_at: new Date(now).toISOString(), reason });
  const members = state.household.housemates;
  if (!state.searchRequestedAt || !state.household.confirmed || members.length !== state.household.expectedSize
      || members.some((h) => !h.calendarConnected)) return disabled("Every housemate must confirm the search and connect a calendar before booking on a call");
  const timeZone = new URL(request.url).searchParams.get("timezone") || "America/Los_Angeles";
  try {
    const range = { start: now, end: now + 7 * 86_400_000 };
    const busy = (await Promise.all(members.map((h) => busyIntervals(h.id, range)))).flat();
    // Include bookings whose Google sync is still pending.
    const tours = await sql<{ start_at: Date; end_at: Date }[]>`select start_at, end_at from tours where household_id=${id} and end_at > ${new Date(now)}`;
    busy.push(...tours.map((t) => ({ start: t.start_at.getTime(), end: t.end_at.getTime() })));
    const windows = freeCallWindows(busy, now, timeZone).map((w) => ({ start: new Date(w.start).toISOString(), end: new Date(w.end).toISOString() }));
    return NextResponse.json({ enabled: windows.length > 0, windows, checked_at: new Date(now).toISOString(), source: "household_calendars", reason: "All housemates' calendars checked" });
  } catch {
    return disabled("Calendar availability could not be verified; collect offers only");
  }
}
