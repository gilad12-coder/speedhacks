import "server-only";
import { workerRequest } from "./agent-worker";
import type { Outreach } from "./types";

// The household's search workspace, served by the Python engine (househunt/web/household_api.py).
// Server-to-server only: the agent secret never reaches the browser.

export type NextAction =
  | "call" | "email" | "reveal" | "book_online" | "message" | "log_viewing" | "prepare" | "wait" | "move_on";

export interface WorkspaceListing {
  outreach?: Omit<Outreach, "listingId"> | null;
  id: string;
  title: string;
  url: string;
  source: string;
  price: number | null;
  beds: number | null;
  baths: number | null;
  sqft: number | null;
  address: string | null;
  neighborhood: string | null;
  lat: number | null;
  lng: number | null;
  status: "new" | "candidate" | "filtered" | "contacted" | "viable" | "not_viable" | "tour_scheduled";
  score: number;
  notes: string[];
  contact: { name: string | null; phone: string | null; email: string | null } | null;
  contactHint: "show_contact" | "reply" | null;
  tourUrl: string | null;
  call: { id?: string; listingVerified?: boolean | null; bookingWarning?: string | null;
    verificationEvidence?: { key: string; summary: string; passed: boolean | null; evidence: { t: number; quote: string }[] }[];
    status: string; error: string | null; summary: string | null; viable: boolean | null; tradeoffs: string[]; transcript: string | null } | null;
  email: { id: number; status: "draft" | "sent" | "failed" | "discarded"; to: string; subject: string; body: string } | null;
  viewing: { start: string; end?: string | null; confirmedOnCall?: boolean; calendarStatus?: string; calendarError?: string | null; calendarUrl: string | null } | null;
  interested: string | null;
  nextStep: { action: NextAction; label: string; why: string; href: string | null } | null;
}

export interface Workspace {
  autonomousCalling?: boolean;
  callbackReady?: boolean;
  search: {
    id: number;
    status: string;
    error: string | null;
    criteria: { city: string; max_price: number; min_beds: number; neighborhoods: string[]; must_haves: string[] };
  };
  listings: WorkspaceListing[];
  callingEnabled: boolean;
}

export type WorkspaceResult =
  | { ok: true; workspace: Workspace }
  | { ok: false; reason: "not_started" | "unavailable" };

export async function getWorkspace(householdId: string): Promise<WorkspaceResult> {
  try {
    const res = await workerRequest(`/agent/households/${encodeURIComponent(householdId)}/workspace`);
    if (res.status === 404) return { ok: false, reason: "not_started" };
    if (!res.ok) return { ok: false, reason: "unavailable" };
    return { ok: true, workspace: (await res.json()) as Workspace };
  } catch {
    return { ok: false, reason: "unavailable" };
  }
}

/** POST to the household's workspace API. Returns the engine's error message on failure. */
export async function workspacePost(householdId: string, path: string, body: unknown = {}): Promise<{ error?: string; data?: unknown }> {
  try {
    const res = await workerRequest(`/agent/households/${encodeURIComponent(householdId)}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) return { error: typeof data.detail === "string" ? data.detail : "That didn't go through. Try again." };
    return { data };
  } catch {
    return { error: "KeyHunt's search engine isn't reachable right now. Try again in a moment." };
  }
}

export const SEARCH_RUNNING = new Set(["pending", "sourcing", "screening", "calling"]);
