import type { Call, Check, Listing, OfferedWindow, SearchBrief } from '../../lib/types.js';
import { assessmentSchema, requirements, type Assessment, type EvidenceRef } from './schema.js';

export function validRef(ref: EvidenceRef, call: Call): boolean {
  const line = call.transcript[ref.turnIndex];
  return !!line && line.speaker === 'contact' && !!ref.quote.trim() && line.text.includes(ref.quote);
}
export function evidence(ref: EvidenceRef, call: Call): NonNullable<Check['evidence']> {
  return { callId: call.id, t: call.transcript[ref.turnIndex].t, quote: ref.quote };
}
export interface Verification {
  listing: Listing; call: Call; checks: Check[]; offeredWindows: OfferedWindow[];
  assessment: Assessment; warnings: string[]; doNotCall: boolean;
}
export function verify(raw: Assessment, call: Call, listing: Listing, brief: SearchBrief): Verification {
  const assessment = structuredClone(assessmentSchema.parse(raw));
  const warnings: string[] = [];
  const expected = requirements(brief);
  for (const fact of assessment.facts) {
    if (assessment.facts.filter(f => f.key === fact.key).length !== 1) throw new Error(`Duplicate extracted requirement: ${fact.key}`);
    if (!expected.some(r => r.key === fact.key)) throw new Error(`Unknown extracted requirement: ${fact.key}`);
    if (fact.passed !== null && (!fact.evidence.length || !fact.evidence.every(ref => validRef(ref, call)))) {
      warnings.push(`Rejected unsupported evidence for ${fact.key}`);
      fact.passed = null; fact.evidence = []; fact.summary = 'Not confirmed on the call';
    }
  }
  if (assessment.monthlyRentUsd && !validRef(assessment.monthlyRentUsd.evidence, call)) {
    warnings.push('Rejected unsupported monthly rent'); assessment.monthlyRentUsd = null;
  }
  // Price arithmetic is performed in code; a model cannot pass an over-budget rent.
  const rentFact = assessment.facts.find(f => f.key === 'rent');
  if (rentFact) {
    const rent = assessment.monthlyRentUsd;
    rentFact.passed = rent ? rent.value <= brief.maxTotalRentUsd : null;
    rentFact.evidence = rent ? [rent.evidence] : [];
    rentFact.summary = rent ? `Contact stated $${rent.value}/month; ceiling $${brief.maxTotalRentUsd}` : 'Monthly rent not confirmed on the call';
  }
  assessment.details = assessment.details.filter(d => validRef(d.evidence, call));
  const answered = assessment.reachedPerson && !assessment.voicemail && call.outcome === 'answered';
  const checks: Check[] = (['real', 'matches', 'fit'] as const).map(kind => {
    const facts = expected.filter(r => r.group === kind).map(r => assessment.facts.find(f => f.key === r.key));
    const failed = facts.find(f => f?.passed === false);
    const passed = !answered ? null : failed ? false : facts.every(f => f?.passed === true) ? true : null;
    const cited = failed ?? facts.find(f => f?.passed === true);
    return { listingId: listing.id, kind, passed,
      summary: passed === null ? 'Not fully confirmed on the call' : facts.filter(f => f?.passed === passed).map(f => f!.summary).join('; '),
      evidence: passed !== null && cited?.evidence[0] ? evidence(cited.evidence[0], call) : null };
  });
  const hardFailure = checks.some(c => c.passed === false);
  const offers = assessment.tourOffers.filter(offer => {
    const start = Date.parse(offer.start), end = Date.parse(offer.end);
    const valid = offer.evidence.every(ref => validRef(ref, call)) && end > start && start > Date.parse(call.startedAt) && end - start <= 24 * 3600_000;
    if (!valid) warnings.push('Rejected an invalid or unsupported tour window');
    return valid;
  });
  const offeredWindows: OfferedWindow[] = answered && !hardFailure
    ? offers.map(o => ({ listingId: listing.id, start: o.start, end: o.end })) : [];
  checks.push({ listingId: listing.id, kind: 'tour', passed: offeredWindows.length ? true : null,
    summary: offeredWindows.length ? 'Contact offered a viewing window; household has not confirmed' : 'No usable tour window confirmed',
    evidence: offeredWindows.length ? evidence(offers[0].evidence[0], call) : null });
  const updated = { ...listing };
  delete updated.ruledOutReason; delete updated.ruledOutNote;
  updated.status = 'called';
  if (assessment.monthlyRentUsd && answered) updated.rentUsd = assessment.monthlyRentUsd.value;
  if (answered && hardFailure) {
    updated.status = 'ruled_out';
    updated.ruledOutReason = checks[0].passed === false ? 'taken' : checks[2].passed === false ? 'wrong_tenant' : 'breaks_must_have';
    updated.ruledOutNote = checks.find(c => c.passed === false)!.summary;
  } else if (checks.slice(0, 3).every(c => c.passed === true)) {
    updated.status = offeredWindows.length ? 'tour_offered' : 'verified';
  }
  const updatedCall = { ...call, outcome: assessment.voicemail ? 'voicemail' as const : call.outcome };
  const doNotCall = !!assessment.doNotCall && validRef(assessment.doNotCall, call);
  return { listing: updated, call: updatedCall, checks, offeredWindows, assessment, warnings, doNotCall };
}
export function unconfirmedChecks(listingId: string, summary: string): Check[] {
  return (['real', 'matches', 'fit', 'tour'] as const).map(kind => ({ listingId, kind, passed: null, summary, evidence: null }));
}
