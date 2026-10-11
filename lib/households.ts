import "server-only";
import { createHash } from "node:crypto";
import { detectConflicts } from "./brief";
import { newId } from "./crypto";
import { sql } from "./db";
import { INCOME_BANDS } from "./features";
import type { InterviewMessage, InterviewResult } from "./interview";
import type { Intake } from "./schemas";
import type { Account } from "./session";
import type { AgentRun, CommuteMode, Household, Housemate, TourSlot } from "./types";

interface HouseholdRow {
  id: string;
  join_code: string;
  expected_size: number;
  confirmed: boolean;
  search_requested_at: Date | null;
}

interface HousemateRow {
  id: string;
  name: string;
  location: string | null;
  max_budget_usd: number;
  commute_destination: string;
  commute_mode: CommuteMode;
  commute_modes: CommuteMode[] | null;
  max_commute_minutes: number;
  must_haves: string[];
  deal_breakers: string[];
  nice_to_haves: string[];
  wishes: string[];
  move_in_from: string;
  move_in_to: string;
  income_min: number;
  income_max: number;
  calendar_connected: boolean;
}

function toHousemate(r: HousemateRow): Housemate {
  return {
    id: r.id,
    name: r.name,
    location: r.location ?? "",
    maxBudgetUsd: r.max_budget_usd,
    commute: {
      destination: r.commute_destination,
      mode: r.commute_mode,
      modes: r.commute_modes ?? [r.commute_mode],
      maxMinutes: r.max_commute_minutes,
    },
    mustHaves: r.must_haves,
    dealBreakers: r.deal_breakers,
    niceToHaves: r.nice_to_haves,
    wishes: r.wishes,
    moveInFrom: r.move_in_from,
    moveInTo: r.move_in_to,
    incomeBandUsd: { min: r.income_min, max: r.income_max },
    calendarConnected: r.calendar_connected,
    intakeComplete: true,
  };
}

export interface HouseholdState {
  household: Household;
  joinCode: string;
  searchRequestedAt: Date | null;
}

export async function createHousehold(expectedSize: number): Promise<{ id: string; joinCode: string }> {
  const id = newId();
  const joinCode = newId(9);
  await sql`insert into households (id, join_code, expected_size) values (${id}, ${joinCode}, ${expectedSize})`;
  return { id, joinCode };
}

export async function findHouseholdByCode(joinCode: string) {
  const [row] = await sql<HouseholdRow[]>`select * from households where join_code = ${joinCode}`;
  if (!row) return null;
  const [{ count }] = await sql<{ count: number }[]>`
    select count(*)::int as count from housemates where household_id = ${row.id}`;
  return { id: row.id, expectedSize: row.expected_size, joined: count, searchStarted: row.search_requested_at !== null };
}

async function housemateRows(householdId: string) {
  return sql<HousemateRow[]>`
    select id, name, location, max_budget_usd, commute_destination, commute_mode, commute_modes, max_commute_minutes,
      must_haves, deal_breakers, nice_to_haves, wishes,
      to_char(move_in_from, 'YYYY-MM-DD') as move_in_from, to_char(move_in_to, 'YYYY-MM-DD') as move_in_to,
      income_min, income_max, google_refresh_token is not null as calendar_connected
    from housemates where household_id = ${householdId} order by created_at`;
}

export async function getHouseholdState(householdId: string): Promise<HouseholdState | null> {
  const [row] = await sql<HouseholdRow[]>`select * from households where id = ${householdId}`;
  if (!row) return null;
  const housemates = (await housemateRows(householdId)).map(toHousemate);
  return {
    household: {
      id: row.id,
      shareUrl: `/join/${row.join_code}`,
      housemates,
      expectedSize: row.expected_size,
      conflicts: detectConflicts(housemates),
      confirmed: row.confirmed,
    },
    joinCode: row.join_code,
    searchRequestedAt: row.search_requested_at,
  };
}

export async function isMember(householdId: string, housemateId: string | null): Promise<boolean> {
  if (!housemateId) return false;
  const [row] = await sql`select 1 from housemates where id = ${housemateId} and household_id = ${householdId}`;
  return Boolean(row);
}

export async function findHousemateByAccount(householdId: string, sub: string): Promise<string | null> {
  const [row] = await sql<{ id: string }[]>`
    select id from housemates where household_id = ${householdId} and google_sub = ${sub}`;
  return row?.id ?? null;
}

export async function getHousemateFullName(housemateId: string) {
  const [row] = await sql<{ first_name: string | null; last_name: string | null; name: string }[]>`
    select first_name, last_name, name from housemates where id = ${housemateId}`;
  return row ? { firstName: row.first_name ?? row.name, lastName: row.last_name ?? "" } : null;
}

export async function upsertHousemate(
  householdId: string,
  housemateId: string | null,
  intake: Intake,
  account: Account | null,
): Promise<string> {
  const band = INCOME_BANDS[intake.incomeBand];
  const values = {
    // Conflicts and the dashboard address housemates by first name.
    name: intake.firstName,
    first_name: intake.firstName,
    last_name: intake.lastName,
    ...(account && { google_sub: account.sub, email: account.email }),
    location: intake.location,
    max_budget_usd: intake.maxBudgetUsd,
    commute_destination: intake.commuteDestination,
    commute_mode: intake.commuteModes[0],
    commute_modes: intake.commuteModes,
    max_commute_minutes: intake.maxCommuteMinutes,
    move_in_from: intake.moveInFrom,
    move_in_to: intake.moveInTo,
    income_min: band.min,
    income_max: band.max,
  };

  return sql.begin(async (tx) => {
    // Lock the household row so two people joining at once can't exceed its size.
    const [household] = await tx<HouseholdRow[]>`select * from households where id = ${householdId} for update`;
    if (!household) throw new Error("Household not found");
    if (household.search_requested_at) throw new HouseholdError("The search has already started, so preferences are locked.");

    let id = housemateId;
    if (id) {
      const updated = await tx`update housemates set ${tx(values)} where id = ${id} and household_id = ${householdId}`;
      if (updated.count === 0) id = null;
    }
    if (!id) {
      const [{ count }] = await tx<{ count: number }[]>`
        select count(*)::int as count from housemates where household_id = ${householdId}`;
      if (count >= household.expected_size) throw new HouseholdError("This household is already full.");
      id = newId();
      await tx`insert into housemates ${tx({ id, household_id: householdId, ...values })}`;
    }
    // Any change to someone's preferences means the group has to look at the brief again.
    await tx`update households set confirmed = false where id = ${householdId}`;
    return id;
  });
}

export class HouseholdError extends Error {}

export async function confirmBrief(householdId: string, seenFingerprint: string) {
  // Someone may have edited their answers after this person loaded the page; only confirm what they actually saw.
  const state = await getHouseholdState(householdId);
  if (!state || briefFingerprint(state.household) !== seenFingerprint) return false;
  await sql`update households set confirmed = true where id = ${householdId}`;
  return true;
}

export function briefFingerprint(household: Household): string {
  const answers = household.housemates.map((h) => [
    h.id, h.location, h.maxBudgetUsd, h.commute, h.mustHaves, h.dealBreakers, h.niceToHaves, h.wishes, h.moveInFrom, h.moveInTo, h.incomeBandUsd,
  ]);
  return createHash("sha256").update(JSON.stringify([household.expectedSize, answers])).digest("base64url").slice(0, 16);
}

export async function requestSearch(householdId: string) {
  await sql`
    update households set search_requested_at = now()
    where id = ${householdId} and confirmed and search_requested_at is null`;
}

export async function getAgentRun(householdId: string): Promise<AgentRun | null> {
  const [row] = await sql<{ run: AgentRun }[]>`select run from agent_runs where household_id = ${householdId}`;
  return row?.run ?? null;
}

export async function saveAgentRun(run: AgentRun): Promise<"saved" | "not_found" | "not_requested"> {
  const [household] = await sql<HouseholdRow[]>`select * from households where id = ${run.householdId}`;
  if (!household) return "not_found";
  if (!household.search_requested_at) return "not_requested";
  await sql`
    insert into agent_runs (household_id, run, updated_at) values (${run.householdId}, ${sql.json(JSON.parse(JSON.stringify(run)))}, now())
    on conflict (household_id) do update set run = excluded.run, updated_at = now()`;
  return "saved";
}

export async function pendingHouseholdIds(): Promise<string[]> {
  const rows = await sql<{ id: string }[]>`
    select h.id from households h left join agent_runs r on r.household_id = h.id
    where h.search_requested_at is not null and (r.run is null or r.run->>'finishedAt' is null)
    order by h.search_requested_at`;
  return rows.map((r) => r.id);
}

export async function getBookedTours(householdId: string): Promise<TourSlot[]> {
  // Partly booked tours come back too, so the UI offers to finish that same time instead of proposing a new one.
  const rows = await sql<{ listing_id: string; start_at: Date; end_at: Date; status: TourSlot["status"]; calendar_event_ids: Record<string, string> }[]>`
    select listing_id, start_at, end_at, status, calendar_event_ids from tours
    where household_id = ${householdId} and (status = 'accepted' or calendar_event_ids <> '{}'::jsonb)`;
  return rows.map((r) => ({
    listingId: r.listing_id,
    start: r.start_at.toISOString(),
    end: r.end_at.toISOString(),
    status: r.status,
    calendarEventIds: r.calendar_event_ids,
  }));
}

export interface InterviewState {
  messages: InterviewMessage[];
  done: boolean;
}

export async function getInterview(housemateId: string): Promise<InterviewState> {
  const [row] = await sql<{ interview: InterviewMessage[]; interview_done: boolean }[]>`
    select interview, interview_done from housemates where id = ${housemateId}`;
  return { messages: row?.interview ?? [], done: row?.interview_done ?? false };
}

export async function saveInterview(
  householdId: string,
  housemateId: string,
  messages: InterviewMessage[],
  result: InterviewResult | null,
) {
  await sql.begin(async (tx) => {
    const [household] = await tx<HouseholdRow[]>`select * from households where id = ${householdId} for update`;
    if (household?.search_requested_at) throw new HouseholdError("The search has already started, so preferences are locked.");
    const transcript = tx.json(JSON.parse(JSON.stringify(messages)));
    if (result) {
      await tx`
        update housemates set interview = ${transcript}, interview_done = true,
          must_haves = ${result.mustHaves}, nice_to_haves = ${result.niceToHaves},
          deal_breakers = ${result.dealBreakers}, wishes = ${result.wishes}
        where id = ${housemateId} and household_id = ${householdId}`;
      await tx`update households set confirmed = false where id = ${householdId}`;
    } else {
      // A restarted or in-progress interview keeps the earlier results until it finishes again.
      await tx`update housemates set interview = ${transcript}, interview_done = false where id = ${housemateId} and household_id = ${householdId}`;
    }
  });
}
