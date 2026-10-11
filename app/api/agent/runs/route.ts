import { NextResponse } from "next/server";
import { isAgent } from "@/lib/agent-auth";
import { getHouseholdState, saveAgentRun } from "@/lib/households";
import { syncCallBookings } from "@/lib/call-bookings";
import { agentRunSchema } from "@/lib/schemas";
import type { AgentRun } from "@/lib/types";

export const maxDuration = 60;

// Post the whole AgentRun each time; the latest post replaces the previous one.
// Post partial runs (finishedAt: null) as calls finish so the dashboard fills in live.
export async function POST(request: Request) {
  if (!isAgent(request)) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const body = await request.json().catch(() => null);
  const parsed = agentRunSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json({ error: "invalid_run", issues: parsed.error.issues.slice(0, 20) }, { status: 400 });
  }
  const result = await saveAgentRun(parsed.data as AgentRun);
  if (result === "not_found") return NextResponse.json({ error: "unknown_household" }, { status: 404 });
  if (result === "not_requested") return NextResponse.json({ error: "search_not_requested" }, { status: 409 });
  const state = parsed.data.bookedTours?.length ? await getHouseholdState(parsed.data.householdId) : null;
  const calendarSync = state ? await syncCallBookings(state.household, parsed.data as AgentRun) : [];
  return NextResponse.json({ ok: true, calendarSync });
}
