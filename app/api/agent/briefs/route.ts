import { NextResponse } from "next/server";
import { isAgent } from "@/lib/agent-auth";
import { buildSearchBrief } from "@/lib/brief";
import { getHouseholdState, pendingHouseholdIds } from "@/lib/households";

export const dynamic = "force-dynamic";

// Searches the agent still owes: requested, and no finished run yet.
export async function GET(request: Request) {
  if (!isAgent(request)) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const briefs = [];
  for (const id of await pendingHouseholdIds()) {
    const state = await getHouseholdState(id);
    if (state) briefs.push(buildSearchBrief(id, state.household.housemates));
  }
  return NextResponse.json({ briefs });
}
