import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { personalMode } from "@/lib/personal-mode";
import { setAccount, setHousemateSession } from "@/lib/session";
import { newId } from "@/lib/crypto";
import { sql } from "@/lib/db";
import { workerRequest } from "@/lib/agent-worker";

const preferences = z.object({ city: z.string().trim().min(2).max(120), neighborhood: z.string().trim().max(120),
  beds: z.coerce.number().int().min(0).max(10), budget: z.coerce.number().int().min(300).max(100000) });

export async function POST(request: NextRequest) {
  if (!personalMode(request.headers.get("host"), request.headers.get("origin"))) return new NextResponse("Not found", { status: 404 });
  const form = await request.formData();
  const sub = process.env.PERSONAL_ACCOUNT_ID ?? "local:reed";
  let householdId: string;
  let memberId: string;
  if (form.get("search")) {
    const [member] = await sql<{ id: string; household_id: string }[]>`select id, household_id from housemates
      where household_id = ${String(form.get("search"))} and google_sub = ${sub}`;
    if (!member) return new NextResponse("Search not found", { status: 404 });
    householdId = member.household_id; memberId = member.id;
  } else {
    const result = preferences.safeParse(Object.fromEntries(form));
    if (!result.success) return new NextResponse("Check the city, bedroom count and rent limit.", { status: 400 });
    householdId = newId(); memberId = newId();
    const p = result.data;
    await sql.begin(async (tx) => {
      await tx`insert into households (id, join_code, expected_size, confirmed, search_requested_at)
        values (${householdId}, ${newId(9)}, 1, true, now())`;
      await tx`insert into housemates (id, household_id, name, first_name, google_sub, email, location,
        max_budget_usd, min_bedrooms, neighborhoods, commute_destination, commute_mode, commute_modes,
        max_commute_minutes, interview_done)
        values (${memberId}, ${householdId}, 'Reed', 'Reed', ${sub}, '', ${p.city}, ${p.budget}, ${p.beds},
          ${p.neighborhood ? [p.neighborhood] : []}, '', 'walk', ${[] as string[]}, 0, true)`;
    });
  }
  await setAccount({ sub, email: "", firstName: "Reed", lastName: "" });
  await setHousemateSession(householdId, memberId);
  await workerRequest(`/agent/households/${encodeURIComponent(householdId)}/start`, { method: "POST" }).catch(() => null);
  return NextResponse.redirect(new URL(`/h/${householdId}/search`, process.env.APP_URL!), 303);
}
