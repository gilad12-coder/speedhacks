import "server-only";
import { createHash } from "node:crypto";
import { sql } from "./db";
import { createConfirmedEvent } from "./google";
import type { AgentRun, Household } from "./types";

export interface CalendarSync { callId: string; status: "synced" | "pending"; error?: string }

/** The contact already booked this time. Failures here never change that fact or redial. */
export async function syncCallBookings(household: Household, run: AgentRun): Promise<CalendarSync[]> {
  const results: CalendarSync[] = [];
  for (const tour of run.bookedTours ?? []) {
    try {
      const result = await sql.begin(async (tx) => {
        await tx`select pg_advisory_xact_lock(hashtext(${`tour:${household.id}:${tour.listingId}`}))`;
        const [existing] = await tx<{ start_at: Date; end_at: Date; calendar_event_ids: Record<string, string> }[]>`
          select start_at, end_at, calendar_event_ids from tours where household_id=${household.id} and listing_id=${tour.listingId}`;
        const start = new Date(tour.start), end = new Date(tour.end);
        if (existing && (existing.start_at.getTime() !== start.getTime() || existing.end_at.getTime() !== end.getTime())) {
          return { callId: tour.callId, status: "pending" as const, error: "A different viewing is already saved. Review both times before changing the calendar." };
        }
        const eventIds = { ...(existing?.calendar_event_ids ?? {}) };
        const eventId = createHash("sha256").update(`keyhunt:${household.id}:${tour.callId}:${tour.start}`).digest("hex");
        let incomplete = household.housemates.length === 0;
        for (const member of household.housemates) {
          if (eventIds[member.id]) continue;
          try {
            if (!member.calendarConnected) throw new Error("Calendar disconnected");
            eventIds[member.id] = await createConfirmedEvent(member.id, eventId, {
              summary: `Tour: ${tour.meetingAddress}`, location: tour.meetingAddress,
              description: `Confirmed with the contact by the household's AI assistant.\n${tour.contactEvidence.quote}\n${run.listings.find((l) => l.id === tour.listingId)?.sourceUrl ?? ""}`,
              start, end,
            });
          } catch { incomplete = true; }
        }
        await tx`
          insert into tours (household_id, listing_id, start_at, end_at, status, calendar_event_ids)
          values (${household.id}, ${tour.listingId}, ${start}, ${end}, ${incomplete ? "proposed" : "accepted"}, ${tx.json(eventIds)})
          on conflict (household_id, listing_id) do update set status=excluded.status, calendar_event_ids=excluded.calendar_event_ids`;
        return incomplete
          ? { callId: tour.callId, status: "pending" as const, error: "Tour booked with the contact; calendar sync needs attention. Check for conflicts or reconnect calendars. Saved events will not be duplicated." }
          : { callId: tour.callId, status: "synced" as const };
      });
      results.push(result);
    } catch {
      results.push({ callId: tour.callId, status: "pending", error: "Tour booked; calendar sync will retry. Do not arrange a second appointment." });
    }
  }
  return results;
}
