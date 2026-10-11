import { readFileSync } from 'node:fs';
import type { AgentRun } from '../../lib/types.js';
import { normalizeCall, type DialCall } from './dial.js';
import { inputSchema, type Assessment } from './schema.js';
import { verify } from './verify.js';

// Explicitly synthetic fixtures. NEVER used by the live engine or production API.
export function demoFixture() {
  const input = inputSchema.parse(JSON.parse(readFileSync(new URL('../examples/listing.json', import.meta.url), 'utf8')));
  const texts = [
    "I'm the property manager and that exact apartment is still available.",
    'The monthly rent is $4500.',
    'November 1 through November 15 works for move-in.',
    'Three housemates can live there.',
    'All three housemates are eligible to apply; there are no additional screening thresholds for this rental.',
    'It has in-unit laundry.',
    'Pets are allowed.',
    'I can offer October 15, 2026 from 6 to 6:30 PM Pacific for a viewing. Please confirm with your group first.',
    'The refundable deposit is $4500 and the lease term is 12 months.'
  ];
  const raw: DialCall = { id: 'synthetic-example', status: { state: 'Terminated', terminationType: 'Completed' }, createdAt: '2026-10-11T20:00:00Z', duration: 100,
    transcriptTurns: texts.map((text, i) => ({ speaker: 'user', text, startMs: (i + 1) * 10_000, endMs: (i + 1) * 10_000 + 4000 })) };
  const ref = (turnIndex: number) => ({ turnIndex, quote: texts[turnIndex] });
  const keys = ['available', 'rent', 'move_in', 'occupancy', 'qualifications', 'must:0', 'avoid:0'];
  const assessment: Assessment = {
    reachedPerson: true, voicemail: false, doNotCall: null,
    facts: keys.map((key, i) => ({ key, passed: true, summary: texts[i], evidence: [ref(i)] })),
    monthlyRentUsd: { value: 4500, evidence: ref(1) },
    details: [{ name: 'deposit_and_term', value: '$4500 deposit; 12-month lease', evidence: ref(8) }],
    tourOffers: [{ start: '2026-10-15T18:00:00-07:00', end: '2026-10-15T18:30:00-07:00', evidence: [ref(7)] }]
  };
  return { input, raw, assessment };
}
export function demoRun(): AgentRun {
  const { input, raw, assessment } = demoFixture();
  const call = normalizeCall(raw, input.listings[0].id, raw.createdAt!);
  const result = verify(assessment, call, input.listings[0], input.brief);
  return { householdId: input.brief.householdId, startedAt: raw.createdAt!, finishedAt: '2026-10-11T20:02:00Z',
    listings: [result.listing], calls: [result.call], checks: result.checks, offeredWindows: result.offeredWindows };
}
