import { z } from 'zod';
import type { Listing, SearchBrief } from '../../lib/types.js';

const isoDate = z.string().regex(/^\d{4}-\d{2}-\d{2}$/).refine(v => {
  const d = new Date(v); return Number.isFinite(d.getTime()) && d.toISOString().slice(0, 10) === v;
}, 'Invalid calendar date');
const text = z.string().trim().min(1).max(2000);
export const phoneSchema = z.string().regex(/^\+1[2-9]\d{9}$/, 'Use a US E.164 number');
const commute = z.object({ destination: text, mode: z.enum(['caltrain', 'transit', 'drive', 'bike', 'walk']), maxMinutes: z.number().positive() });
export const briefSchema = z.object({
  householdId: text, occupants: z.number().int().min(2).max(6), maxTotalRentUsd: z.number().positive(),
  moveInFrom: isoDate, moveInTo: isoDate, commute,
  mustHaves: z.array(text).max(20), dealBreakers: z.array(text).max(20), niceToHaves: z.array(text).max(20),
  householdIncomeBandUsd: z.object({ min: z.number().nonnegative(), max: z.number().nonnegative() })
}).strict().refine(v => v.moveInFrom <= v.moveInTo, 'Move-in dates are reversed')
  .refine(v => v.householdIncomeBandUsd.min <= v.householdIncomeBandUsd.max, 'Income range is reversed') satisfies z.ZodType<SearchBrief>;
export const listingSchema = z.object({
  id: text, source: z.enum(['curated', 'live_search']), sourceUrl: z.string().url(), address: text,
  neighborhood: text, rentUsd: z.number().positive(), bedrooms: z.number().nonnegative(), bathrooms: z.number().nonnegative(),
  photoUrls: z.array(z.string().url()).max(20),
  contact: z.object({ name: text, role: z.enum(['landlord', 'broker', 'property_manager']), phone: z.string().max(40) }),
  commuteMinutes: z.number().nonnegative().nullable(),
  status: z.enum(['found', 'called', 'verified', 'tour_offered', 'ruled_out']),
  ruledOutReason: z.enum(['scam', 'taken', 'wrong_tenant', 'breaks_must_have', 'no_answer']).optional(),
  ruledOutNote: z.string().optional()
}).strict() satisfies z.ZodType<Listing>;
export const inputSchema = z.object({ brief: briefSchema, listings: z.array(listingSchema).min(1).max(60) }).strict()
  .refine(v => new Set(v.listings.map(l => l.id)).size === v.listings.length, 'Duplicate listing IDs')
  .refine(v => v.listings.every(l => ['found', 'ruled_out'].includes(l.status)), 'Start with found or ruled_out listings');
export type RunInput = z.infer<typeof inputSchema>;

export const refSchema = z.object({ turnIndex: z.number().int().nonnegative(), quote: text }).strict();
export type EvidenceRef = z.infer<typeof refSchema>;
export const factSchema = z.object({
  key: text, passed: z.boolean().nullable(), summary: text,
  evidence: z.array(refSchema).max(12)
}).strict();
export const assessmentSchema = z.object({
  reachedPerson: z.boolean(), voicemail: z.boolean(),
  doNotCall: refSchema.nullable(),
  facts: z.array(factSchema).max(50),
  monthlyRentUsd: z.object({ value: z.number().positive(), evidence: refSchema }).strict().nullable(),
  details: z.array(z.object({ name: text, value: text, evidence: refSchema }).strict()).max(20),
  tourOffers: z.array(z.object({
    start: z.string().datetime({ offset: true }), end: z.string().datetime({ offset: true }),
    evidence: z.array(refSchema).min(1).max(12)
  }).strict()).max(10)
}).strict();
export type Assessment = z.infer<typeof assessmentSchema>;
export interface Requirement { key: string; group: 'real' | 'matches' | 'fit'; question: string }
export function requirements(brief: SearchBrief): Requirement[] {
  return [
    { key: 'available', group: 'real', question: 'Is this exact rental still available, and are you its landlord or authorized agent?' },
    { key: 'rent', group: 'matches', question: `What is the actual total monthly rent? The ceiling is $${brief.maxTotalRentUsd}.` },
    { key: 'move_in', group: 'matches', question: `Can the tenancy start between ${brief.moveInFrom} and ${brief.moveInTo}?` },
    { key: 'occupancy', group: 'fit', question: `Would a group of ${brief.occupants} housemates be allowed to rent and occupy it?` },
    { key: 'qualifications', group: 'fit', question: 'What income, guarantor, credit and application requirements apply? Do not assume the household satisfies unstated or unverified requirements.' },
    ...brief.mustHaves.map((item, i) => ({ key: `must:${i}`, group: 'matches' as const, question: `Required: ${item}. Please confirm.` })),
    ...brief.dealBreakers.map((item, i) => ({ key: `avoid:${i}`, group: 'matches' as const, question: `Deal-breaker: ${item}. Confirm that this does NOT apply.` }))
  ];
}
