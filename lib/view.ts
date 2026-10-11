import type { AgentRun, Check, CheckKind, Listing } from "./types";

export const CHECK_ORDER: CheckKind[] = ["real", "matches", "fit", "tour"];

export const CHECK_LABELS: Record<CheckKind, string> = {
  real: "Real & available",
  matches: "Matches your must-haves",
  fit: "You fit what they want",
  tour: "Tour offered",
};

export const RULED_OUT_LABELS: Record<NonNullable<Listing["ruledOutReason"]>, string> = {
  scam: "Likely scam",
  taken: "Already taken",
  wrong_tenant: "Wants a different tenant",
  breaks_must_have: "Breaks a must-have",
  no_answer: "No answer",
};

export function pipelineCounts(run: AgentRun) {
  const called = new Set(run.calls.map((c) => c.listingId));
  const verified = run.listings.filter((l) => l.status === "verified" || l.status === "tour_offered");
  return {
    found: run.listings.length,
    called: called.size,
    verified: verified.length,
    tourOffered: run.listings.filter((l) => l.status === "tour_offered").length,
    ruledOut: run.listings.filter((l) => l.status === "ruled_out").length,
  };
}

export function checksFor(run: AgentRun, listingId: string): Record<CheckKind, Check | null> {
  const byKind = Object.fromEntries(CHECK_ORDER.map((k) => [k, null])) as Record<CheckKind, Check | null>;
  for (const c of run.checks) if (c.listingId === listingId) byKind[c.kind] = c;
  return byKind;
}

// Tours on offer first, then the most checks confirmed, then cheapest. Capped at seven.
export function shortlist(run: AgentRun): Listing[] {
  const passed = (l: Listing) => Object.values(checksFor(run, l.id)).filter((c) => c?.passed === true).length;
  return run.listings
    .filter((l) => l.status === "verified" || l.status === "tour_offered")
    .sort(
      (a, b) =>
        Number(b.status === "tour_offered") - Number(a.status === "tour_offered") ||
        passed(b) - passed(a) ||
        a.rentUsd - b.rentUsd,
    )
    .slice(0, 7);
}

export function ruledOut(run: AgentRun): Listing[] {
  return run.listings.filter((l) => l.status === "ruled_out");
}

export function primaryCall(run: AgentRun, listingId: string) {
  const calls = run.calls.filter((c) => c.listingId === listingId);
  return calls.find((c) => c.outcome === "answered") ?? calls[0] ?? null;
}

export const usd = (n: number) => `$${n.toLocaleString("en-US")}`;

const tz = "America/Los_Angeles";
export function formatSlot(startIso: string, endIso: string) {
  const start = new Date(startIso);
  const day = start.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: tz });
  const time = (d: Date) => d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: tz });
  return `${day} · ${time(start)}–${time(new Date(endIso))}`;
}

export function formatClock(seconds: number) {
  const s = Math.floor(seconds);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
