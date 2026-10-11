import { z } from "zod";
import { COMMUTE_MODES } from "./features";

const isoDate = z.iso.date();
const isoDateTime = z.iso.datetime({ offset: true });

export const intakeSchema = z
  .object({
    firstName: z.string().trim().min(1, "Add your first name").max(40),
    location: z.string().trim().min(2, "Where do you want to live?").max(120),
    maxBudgetUsd: z.coerce.number().int().min(300, "Budget looks too low").max(20_000),
    commuteDestination: z.string().trim().min(2, "Where do you commute to?").max(200),
    commuteModes: z
      .array(z.enum(COMMUTE_MODES.map((m) => m.value) as [string, ...string[]]))
      .min(1, "Pick at least one way you get there"),
    maxCommuteMinutes: z.coerce.number().int().min(5).max(180),
    moveInFrom: isoDate,
    moveInTo: isoDate,
  })
  .refine((v) => v.moveInTo >= v.moveInFrom, { path: ["moveInTo"], message: "Latest move-in is before the earliest" });

export type Intake = z.infer<typeof intakeSchema>;

const listingSchema = z.object({
  id: z.string().min(1),
  source: z.enum(["curated", "live_search"]),
  sourceUrl: z.url(),
  address: z.string().min(1),
  neighborhood: z.string(),
  rentUsd: z.number().int().nonnegative().nullable(),
  bedrooms: z.number().nonnegative().nullable(),
  bathrooms: z.number().nonnegative().nullable(),
  photoUrls: z.array(z.url()),
  contact: z.object({
    name: z.string(),
    role: z.enum(["landlord", "broker", "property_manager"]),
    phone: z.string(),
  }),
  commuteMinutes: z.number().int().nonnegative().nullable(),
  status: z.enum(["found", "called", "verified", "tour_offered", "ruled_out"]),
  ruledOutReason: z.enum(["scam", "taken", "wrong_tenant", "breaks_must_have", "no_answer"]).optional(),
  ruledOutNote: z.string().optional(),
  research: z.object({
    status: z.enum(["not_checked", "checking", "unconfirmed", "cross_referenced", "concerns_found", "error"]),
    checkedAt: isoDateTime.nullable(),
    findings: z.array(z.object({kind: z.string(), summary: z.string(), quote: z.string(), sourceUrl: z.url()})),
    facts: z.array(z.object({field: z.string(), quote: z.string(), sourceUrl: z.url()})),
    limitations: z.string(),
    medianComparableRent: z.number().nullable(),
    comparableCount: z.number().int().nonnegative(),
  }).optional(),
});

const callSchema = z.object({
  id: z.string().min(1),
  listingId: z.string().min(1),
  dialCallId: z.string(),
  startedAt: isoDateTime,
  durationSec: z.number().nonnegative(),
  outcome: z.enum(["answered", "no_answer", "voicemail", "failed"]),
  audioUrl: z.url().nullable(),
  transcript: z.array(
    z.object({ t: z.number().nonnegative(), speaker: z.enum(["agent", "contact"]), text: z.string() }),
  ),
});

const checkSchema = z
  .object({
    listingId: z.string().min(1),
    kind: z.enum(["real", "matches", "fit", "tour"]),
    passed: z.boolean().nullable(),
    summary: z.string(),
    evidence: z.object({ callId: z.string(), t: z.number().nonnegative(), quote: z.string().min(1) }).nullable(),
  })
  .refine((c) => c.passed !== true || c.evidence !== null, "A passed check must cite call evidence");

export const agentRunSchema = z
  .object({
    householdId: z.string().min(1),
    startedAt: isoDateTime,
    finishedAt: isoDateTime.nullable(),
    listings: z.array(listingSchema),
    calls: z.array(callSchema),
    checks: z.array(checkSchema),
    offeredWindows: z.array(z.object({ listingId: z.string(), start: isoDateTime, end: isoDateTime })),
    progress: z.array(z.string()).optional(),
    warnings: z.array(z.string()).optional(),
  })
  .superRefine((run, ctx) => {
    const listingIds = new Set(run.listings.map((l) => l.id));
    const callIds = new Set(run.calls.map((c) => c.id));
    for (const [i, c] of run.checks.entries()) {
      if (!listingIds.has(c.listingId)) ctx.addIssue({ code: "custom", path: ["checks", i], message: "Unknown listingId" });
      if (c.evidence && !callIds.has(c.evidence.callId))
        ctx.addIssue({ code: "custom", path: ["checks", i], message: "Evidence cites an unknown callId" });
    }
    for (const [i, c] of run.calls.entries()) {
      if (!listingIds.has(c.listingId)) ctx.addIssue({ code: "custom", path: ["calls", i], message: "Unknown listingId" });
    }
  });
