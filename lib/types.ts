// Shared data contract between the three parts of Keyhunt.
// Change it only by PR, and tell the other owners: every part builds against it.

// ---------- Part 3 → Part 2: what the agent searches for ----------

// "caltrain" is the stored value for any train; "transit" is the old combined bus-or-metro answer.
export type CommuteMode =
  | "walk" | "bike" | "scooter" | "drive" | "caltrain" | "metro" | "bus" | "tram" | "ferry" | "transit";

export interface SearchBrief {
  householdId: string;
  renterName?: string; // spoken by the AI assistant; optional for older workers
  occupants: number; // 1–6
  location: string; // city or area to search, free text
  maxTotalRentUsd: number; // sum of personal budgets
  moveInFrom: string; // ISO date
  moveInTo: string; // ISO date
  commute: { destination: string; mode: CommuteMode; modes: CommuteMode[]; maxMinutes: number }; // mode = most common first choice
  mustHaves: string[]; // e.g. "laundry", "parking"
  dealBreakers: string[]; // e.g. "no pets allowed"
  niceToHaves: string[];
  householdIncomeBandUsd: { min: number; max: number }; // for tenant fit
  wishes: string[]; // free-form wishes from each housemate's interview, e.g. "Dana: a quiet street"
}

// ---------- Part 2 → Parts 1 & 3: what the agent returns ----------

export type ListingStatus = "found" | "called" | "verified" | "tour_offered" | "ruled_out";

export type RuledOutReason = "scam" | "taken" | "wrong_tenant" | "breaks_must_have" | "no_answer";

export interface Listing {
  id: string;
  source: "curated" | "live_search";
  sourceUrl: string;
  address: string;
  neighborhood: string;
  rentUsd: number | null; // unknown is never represented as a zero-dollar rental
  bedrooms: number | null;
  bathrooms: number | null;
  photoUrls: string[];
  contact: { name: string; role: "landlord" | "broker" | "property_manager"; phone: string };
  commuteMinutes: number | null;
  status: ListingStatus;
  ruledOutReason?: RuledOutReason;
  ruledOutNote?: string; // one plain sentence, shown in "Ruled out"
  research?: RentalResearch;
}

export interface RentalResearch {
  status: "not_checked" | "checking" | "unconfirmed" | "cross_referenced" | "concerns_found" | "error";
  checkedAt: string | null;
  findings: { kind: string; summary: string; quote: string; sourceUrl: string }[];
  facts: { field: string; quote: string; sourceUrl: string }[];
  limitations: string;
  medianComparableRent: number | null;
  comparableCount: number;
}

export interface TranscriptLine {
  t: number; // seconds from call start
  speaker: "agent" | "contact";
  text: string;
}

export interface Call {
  id: string;
  listingId: string;
  dialCallId: string;
  startedAt: string; // ISO datetime
  durationSec: number;
  outcome: "answered" | "no_answer" | "voicemail" | "failed";
  audioUrl: string | null;
  transcript: TranscriptLine[];
}

export type CheckKind = "real" | "matches" | "fit" | "tour";

export interface Check {
  listingId: string;
  kind: CheckKind;
  passed: boolean | null; // null = not confirmed on the call; never shown as passed
  summary: string; // e.g. "Available from Nov 1, allows 4 occupants"
  evidence: { callId: string; t: number; quote: string } | null; // required when passed === true
}

// Times the contact offered for a tour; Part 3 intersects these with the group's free time.
export interface OfferedWindow {
  listingId: string;
  start: string; // ISO datetime
  end: string; // ISO datetime
}

export interface AgentRun {
  householdId: string;
  startedAt: string;
  finishedAt: string | null; // null while still running
  listings: Listing[];
  calls: Call[];
  checks: Check[];
  offeredWindows: OfferedWindow[];
  progress?: string[];
  warnings?: string[];
}

// ---------- Part 3 → Part 1: household and tours ----------

export interface Housemate {
  id: string;
  name: string;
  location: string;
  maxBudgetUsd: number;
  commute: { destination: string; mode: CommuteMode; modes: CommuteMode[]; maxMinutes: number }; // mode = first of modes
  mustHaves: string[];
  dealBreakers: string[];
  niceToHaves: string[];
  wishes: string[]; // what the interview turned up beyond the fixed features
  moveInFrom: string;
  moveInTo: string;
  incomeBandUsd: { min: number; max: number };
  calendarConnected: boolean;
  intakeComplete: boolean;
}

export interface Conflict {
  field: keyof Housemate;
  housemateIds: string[];
  description: string; // e.g. "Dana needs pets allowed; Omer listed no pets"
  suggestion: string; // the compromise Keyhunt proposes
}

export interface Household {
  id: string;
  shareUrl: string;
  housemates: Housemate[];
  expectedSize: number;
  conflicts: Conflict[];
  confirmed: boolean; // group signed off on the merged brief
}

export interface TourSlot {
  listingId: string;
  start: string;
  end: string;
  status: "proposed" | "accepted";
  calendarEventIds: Record<string, string>; // housemateId → Google event id
}
