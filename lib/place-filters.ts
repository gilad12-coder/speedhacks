import type { AgentRun, Call, Listing, RentalResearch, RuledOutReason } from "./types";
import { RULED_OUT_LABELS, primaryCall } from "./view";

// Client-side search over a run's places: one text query, a stage toggle, and
// multi-select facets whose counts reflect every other active filter.

export type Stage = "all" | "checking" | "verified" | "ruled_out";
export type FacetField = "neighborhoods" | "beds" | "rent" | "calls" | "screening" | "reasons";
export type Sort = "best" | "rent" | "commute";
export type Filters = Record<FacetField, string[]>;

export const EMPTY_FILTERS: Filters = { neighborhoods: [], beds: [], rent: [], calls: [], screening: [], reasons: [] };

export const STAGES: { value: Stage; label: string }[] = [
  { value: "all", label: "All" },
  { value: "checking", label: "Being checked" },
  { value: "verified", label: "Verified" },
  { value: "ruled_out", label: "Ruled out" },
];

const STAGE_OF: Record<Listing["status"], Exclude<Stage, "all">> = {
  found: "checking",
  called: "checking",
  verified: "verified",
  tour_offered: "verified",
  ruled_out: "ruled_out",
};

const CALL_LABELS: Record<Call["outcome"] | "none", string> = {
  answered: "Answered",
  no_answer: "No answer",
  voicemail: "Voicemail",
  failed: "Didn't go through",
  none: "Not called yet",
};

const SCREENING_LABELS: Record<Exclude<RentalResearch["status"], "not_checked"> | "none", string> = {
  cross_referenced: "Checks out online",
  concerns_found: "Concerns to review",
  unconfirmed: "Couldn't confirm",
  checking: "Checking sources",
  error: "Screening incomplete",
  none: "Not screened yet",
};

const RENT_LABELS = { within: "Within budget", over: "Over budget", unknown: "Rent unknown" } as const;

export interface FieldSpec {
  field: FacetField;
  label: string;
  /** Free-text values get a search box; fixed sets list every value in order. */
  searchable: boolean;
  order?: string[];
  display: (value: string) => string;
}

export const FIELDS: FieldSpec[] = [
  { field: "neighborhoods", label: "Area", searchable: true, display: (v) => v },
  { field: "rent", label: "Rent", searchable: false, order: Object.keys(RENT_LABELS), display: (v) => RENT_LABELS[v as keyof typeof RENT_LABELS] ?? v },
  { field: "beds", label: "Bedrooms", searchable: false, display: (v) => (v === "?" ? "Unknown" : v === "0" ? "Studio" : `${v} bd`) },
  { field: "calls", label: "Call", searchable: false, order: Object.keys(CALL_LABELS), display: (v) => CALL_LABELS[v as keyof typeof CALL_LABELS] ?? v },
  { field: "screening", label: "Screening", searchable: false, order: Object.keys(SCREENING_LABELS), display: (v) => SCREENING_LABELS[v as keyof typeof SCREENING_LABELS] ?? v },
  { field: "reasons", label: "Ruled out for", searchable: false, order: Object.keys(RULED_OUT_LABELS), display: (v) => RULED_OUT_LABELS[v as RuledOutReason] ?? v },
];

/** The one value each place holds per field, or null where the field doesn't apply. */
export function valuesOf(run: AgentRun, l: Listing, budget: number | null): Record<FacetField, string | null> {
  const call = primaryCall(run, l.id);
  return {
    neighborhoods: l.neighborhood || null,
    beds: l.bedrooms === null ? "?" : String(l.bedrooms),
    rent: l.rentUsd === null ? "unknown" : budget === null || l.rentUsd <= budget ? "within" : "over",
    calls: call ? call.outcome : "none",
    screening: l.research ? (l.research.status === "not_checked" ? "none" : l.research.status) : "none",
    reasons: l.status === "ruled_out" ? (l.ruledOutReason ?? null) : null,
  };
}

export function stageOf(l: Listing): Exclude<Stage, "all"> {
  return STAGE_OF[l.status];
}

export function matchesText(l: Listing, query: string): boolean {
  const tokens = tokenize(query);
  if (!tokens.length) return true;
  const hay = [l.address, l.neighborhood, l.ruledOutNote ?? ""].join(" ").toLowerCase();
  return tokens.every((t) => hay.includes(t));
}

export function tokenize(query: string): string[] {
  return query.trim().toLowerCase().split(/\s+/).filter((t) => t.length > 0);
}

export interface Query {
  text: string;
  stage: Stage;
  filters: Filters;
  sort: Sort;
}

interface Row {
  listing: Listing;
  values: Record<FacetField, string | null>;
}

function passes(row: Row, q: Query, skip: FacetField | null): boolean {
  if (q.stage !== "all" && stageOf(row.listing) !== q.stage) return false;
  if (!matchesText(row.listing, q.text)) return false;
  for (const f of Object.keys(q.filters) as FacetField[]) {
    if (f === skip || !q.filters[f].length) continue;
    const v = row.values[f];
    if (v === null || !q.filters[f].includes(v)) return false;
  }
  return true;
}

const RANK: Record<Listing["status"], number> = { tour_offered: 0, verified: 1, called: 2, found: 3, ruled_out: 4 };

function compare(sort: Sort) {
  const rent = (l: Listing) => l.rentUsd ?? Infinity;
  const commute = (l: Listing) => l.commuteMinutes ?? Infinity;
  return (a: Listing, b: Listing) =>
    sort === "rent"
      ? rent(a) - rent(b)
      : sort === "commute"
        ? commute(a) - commute(b) || rent(a) - rent(b)
        : RANK[a.status] - RANK[b.status] || rent(a) - rent(b);
}

export interface FacetOption {
  value: string;
  count: number;
}

export interface SearchResult {
  results: Listing[];
  /** Per field: every value it can take across the run, counted against the other active filters. */
  facets: Record<FacetField, FacetOption[]>;
  /** How many places each stage would show with the current text and filters. */
  stageCounts: Record<Stage, number>;
}

export function searchPlaces(run: AgentRun, budget: number | null, q: Query): SearchResult {
  const rows: Row[] = run.listings.map((listing) => ({ listing, values: valuesOf(run, listing, budget) }));
  const results = rows.filter((r) => passes(r, q, null)).map((r) => r.listing).sort(compare(q.sort));

  const facets = {} as Record<FacetField, FacetOption[]>;
  for (const spec of FIELDS) {
    const counts = new Map<string, number>();
    for (const r of rows) {
      const v = r.values[spec.field];
      if (v !== null && !counts.has(v)) counts.set(v, 0);
    }
    for (const r of rows) {
      const v = r.values[spec.field];
      if (v !== null && passes(r, q, spec.field)) counts.set(v, (counts.get(v) ?? 0) + 1);
    }
    const options = [...counts].map(([value, count]) => ({ value, count }));
    const position = (v: string) => spec.order?.indexOf(v) ?? -1;
    options.sort((a, b) =>
      spec.order
        ? position(a.value) - position(b.value)
        : spec.field === "beds"
          ? sortBeds(a.value, b.value)
          : b.count - a.count || a.value.localeCompare(b.value),
    );
    facets[spec.field] = options;
  }

  const stageCounts = { all: 0, checking: 0, verified: 0, ruled_out: 0 } as Record<Stage, number>;
  for (const r of rows) {
    if (!passes(r, { ...q, stage: "all" }, null)) continue;
    stageCounts.all += 1;
    stageCounts[stageOf(r.listing)] += 1;
  }

  return { results, facets, stageCounts };
}

function sortBeds(a: string, b: string) {
  const n = (v: string) => (v === "?" ? Infinity : Number(v));
  return n(a) - n(b);
}

export function activeCount(filters: Filters): number {
  return Object.values(filters).reduce((sum, values) => sum + values.length, 0);
}
