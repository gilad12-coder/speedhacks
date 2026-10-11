import { test } from 'node:test';
import assert from 'node:assert/strict';
import { demoFixture, demoRun } from '../src/demo.js';
import { normalizeCall } from '../src/dial.js';
import { verify } from '../src/verify.js';

function setup() {
  const { input, raw, assessment } = demoFixture();
  const call = normalizeCall(raw, input.listings[0].id, raw.createdAt!);
  return { input, call, assessment, evaluate: () => verify(assessment, call, input.listings[0], input.brief) };
}
test('complete evidence produces a tour offer with exact timestamps, not a booking', () => {
  const run = demoRun();
  assert.equal(run.listings[0].status, 'tour_offered');
  assert.equal(run.checks.length, 4);
  assert.equal(run.checks[0].evidence?.t, 10);
  assert.equal(run.checks[3].evidence?.t, 80);
  assert.equal(run.calls[0].audioUrl, null);
  assert.equal(run.offeredWindows[0].start, '2026-10-15T18:00:00-07:00');
});
test('a fabricated quote cannot verify a must-have', () => {
  const x = setup(); x.assessment.facts[5].evidence[0].quote = 'This was never said';
  const result = x.evaluate(); assert.equal(result.checks[1].passed, null); assert.equal(result.listing.status, 'called');
});
test('agent statements cannot be used as landlord evidence', () => {
  const x = setup(); x.call.transcript[0].speaker = 'agent';
  assert.equal(x.evaluate().checks[0].passed, null);
});
test('one confirmed amenity does not hide another missing requirement', () => {
  const x = setup(); x.input.brief.mustHaves.push('parking');
  assert.equal(x.evaluate().checks[1].passed, null);
});
test('unanswered tenant qualifications do not pass fit', () => {
  const x = setup(); x.assessment.facts = x.assessment.facts.filter(f => f.key !== 'qualifications');
  assert.equal(x.evaluate().checks[2].passed, null);
});
test('over-budget confirmed rent overrides the model verdict and suppresses tours', () => {
  const x = setup(); x.assessment.monthlyRentUsd!.value = 5500;
  x.call.transcript[1].text = 'The rent is $5500'; x.assessment.monthlyRentUsd!.evidence.quote = 'The rent is $5500';
  const result = x.evaluate(); assert.equal(result.checks[1].passed, false);
  assert.equal(result.listing.status, 'ruled_out'); assert.equal(result.listing.rentUsd, 5500); assert.deepEqual(result.offeredWindows, []);
});
test('negative availability rules out taken listings', () => {
  const x = setup(); x.assessment.facts[0].passed = false;
  x.call.transcript[0].text = 'It was rented yesterday';
  x.assessment.facts[0].summary = 'Already rented'; x.assessment.facts[0].evidence[0].quote = 'It was rented yesterday';
  assert.equal(x.evaluate().listing.ruledOutReason, 'taken');
});
test('past, reversed and unsupported tour windows are discarded', () => {
  for (const type of ['past', 'reversed', 'unsupported']) {
    const x = setup(); const offer = x.assessment.tourOffers[0];
    if (type === 'past') { offer.start = '2026-10-10T18:00:00-07:00'; offer.end = '2026-10-10T18:30:00-07:00'; }
    if (type === 'reversed') offer.end = '2026-10-15T17:30:00-07:00';
    if (type === 'unsupported') offer.evidence[0].quote = 'Made up slot';
    assert.deepEqual(x.evaluate().offeredWindows, []);
  }
});
test('voicemail never becomes verification', () => {
  const x = setup(); x.assessment.voicemail = true;
  const r = x.evaluate(); assert.ok(r.checks.every(c => c.passed === null)); assert.equal(r.call.outcome, 'voicemail');
});
test('flat transcript without real offsets does not invent timed evidence', () => {
  const { raw } = demoFixture(); raw.transcriptTurns = [{ speaker: 'user', text: 'Yes, available' }];
  raw.transcript = 'Contact: Yes, available';
  assert.deepEqual(normalizeCall(raw, 'listing', raw.createdAt!).transcript, []);
});
test('an opt-out needs actual contact evidence', () => {
  const x = setup(); x.assessment.doNotCall = { turnIndex: 0, quote: 'Never call me' };
  assert.equal(x.evaluate().doNotCall, false);
  x.call.transcript[0].text = 'Never call me'; assert.equal(x.evaluate().doNotCall, true);
});
