import "server-only";
import { sql } from "./db";
import { busyIntervals, createEvent } from "./google";
import { firstFreeSlot, tourDurationMs, type Interval } from "./slots";
import type { AgentRun, Household, Listing, TourSlot } from "./types";

export type ProposedSlots =
  | { status: "ok"; slots: Record<string, TourSlot> }
  | { status: "calendars_missing"; names: string[] }
  | { status: "calendar_error"; names: string[] };

function windowsFor(run: AgentRun, listingId: string): Interval[] {
  return run.offeredWindows
    .filter((w) => w.listingId === listingId)
    .map((w) => ({ start: Date.parse(w.start), end: Date.parse(w.end) }))
    .filter((w) => w.end > Date.now());
}

// The dashboard refreshes every few seconds during a search; this keeps that from hammering Google's free/busy quota.
const CACHE_MS = 60_000;
const cache = new Map<string, { key: string; at: number; value: ProposedSlots }>();

export async function proposeTourSlots(household: Household, run: AgentRun, listings: Listing[]): Promise<ProposedSlots> {
  const key = JSON.stringify([household.housemates.map((h) => [h.id, h.calendarConnected]), run.offeredWindows, listings.map((l) => l.id)]);
  const hit = cache.get(household.id);
  if (hit && hit.key === key && Date.now() - hit.at < CACHE_MS) return hit.value;
  const value = await computeTourSlots(household, run, listings);
  cache.set(household.id, { key, at: Date.now(), value });
  return value;
}

// One free/busy call per housemate across every offered window, then a slot per listing.
async function computeTourSlots(household: Household, run: AgentRun, listings: Listing[]): Promise<ProposedSlots> {
  const missing = household.housemates.filter((h) => !h.calendarConnected);
  if (missing.length) return { status: "calendars_missing", names: missing.map((h) => h.name) };

  const windows = listings.flatMap((l) => windowsFor(run, l.id));
  if (!windows.length) return { status: "ok", slots: {} };
  const range = { start: Math.min(...windows.map((w) => w.start)), end: Math.max(...windows.map((w) => w.end)) };

  const results = await Promise.allSettled(household.housemates.map((h) => busyIntervals(h.id, range)));
  const failed = household.housemates.filter((_, i) => results[i].status === "rejected");
  if (failed.length) return { status: "calendar_error", names: failed.map((h) => h.name) };
  const busy = results.flatMap((r) => (r.status === "fulfilled" ? r.value : []));

  const slots: Record<string, TourSlot> = {};
  for (const listing of listings) {
    for (const window of windowsFor(run, listing.id)) {
      const slot = firstFreeSlot(window, busy);
      if (slot) {
        slots[listing.id] = {
          listingId: listing.id,
          start: new Date(slot.start).toISOString(),
          end: new Date(slot.end).toISOString(),
          status: "proposed",
          calendarEventIds: {},
        };
        break;
      }
    }
  }
  return { status: "ok", slots };
}

export class TourError extends Error {}

export async function acceptTour(household: Household, run: AgentRun, listingId: string, startIso: string, endIso: string) {
  const listing = run.listings.find((l) => l.id === listingId);
  if (!listing || listing.status !== "tour_offered") throw new TourError("This place has no tour on offer.");
  let start = Date.parse(startIso);
  let end = Date.parse(endIso);

  // Serialize accepts for the same tour so two housemates clicking at once can't both create events.
  const failed = await sql.begin(async (tx) => {
    await tx`select pg_advisory_xact_lock(hashtext(${`tour:${household.id}:${listingId}`}))`;
    const [existing] = await tx<{ status: string; start_at: Date; end_at: Date; calendar_event_ids: Record<string, string> }[]>`
      select status, start_at, end_at, calendar_event_ids from tours where household_id = ${household.id} and listing_id = ${listingId}`;
    if (existing?.status === "accepted") return [];

    const eventIds: Record<string, string> = { ...(existing?.calendar_event_ids ?? {}) };
    if (Object.keys(eventIds).length) {
      // Some calendars already hold this tour; finish booking that same time rather than starting over.
      start = existing.start_at.getTime();
      end = existing.end_at.getTime();
    } else {
      const window = windowsFor(run, listingId).find((w) => w.start <= start && end <= w.end);
      if (!window) throw new TourError("That time isn't one the landlord offered.");
      if (start < Date.now()) throw new TourError("That tour time has passed. Refresh for a new one.");
      if (end - start !== tourDurationMs(window)) throw new TourError("That isn't a tour length Keyhunt offers.");
      const busy = (await Promise.all(household.housemates.map((h) => busyIntervals(h.id, { start, end })))).flat();
      if (busy.some((b) => b.start < end && b.end > start)) {
        throw new TourError("Someone's calendar changed and that time no longer works. Refresh for a new time.");
      }
    }

    const failed: string[] = [];
    for (const housemate of household.housemates) {
      if (eventIds[housemate.id]) continue;
      try {
        eventIds[housemate.id] = await createEvent(housemate.id, {
          summary: `Tour: ${listing.address}`,
          location: listing.address,
          description: `${listing.neighborhood} · ${listing.rentUsd === null ? "Rent not confirmed" : `$${listing.rentUsd.toLocaleString("en-US")}/mo`}\nMeet ${listing.contact.name} (${listing.contact.phone}).\nBooked with Keyhunt for ${household.housemates.map((h) => h.name).join(", ")}.`,
          start: new Date(start),
          end: new Date(end),
        });
      } catch {
        // Any failure for one housemate (Google, network, token) must not lose the events already made for others.
        failed.push(housemate.name);
      }
    }

    const status = failed.length ? "proposed" : "accepted";
    await tx`
      insert into tours (household_id, listing_id, start_at, end_at, status, calendar_event_ids)
      values (${household.id}, ${listingId}, ${new Date(start)}, ${new Date(end)}, ${status}, ${tx.json(eventIds)})
      on conflict (household_id, listing_id) do update set
        start_at = excluded.start_at, end_at = excluded.end_at, status = excluded.status, calendar_event_ids = excluded.calendar_event_ids`;
    return failed;
  });

  // Raised after the commit so the row keeping the events already created survives for the retry.
  if (failed.length) {
    throw new TourError(`Added to everyone's calendar except ${failed.join(", ")}. Ask them to reconnect Google Calendar, then press Accept again.`);
  }
}
