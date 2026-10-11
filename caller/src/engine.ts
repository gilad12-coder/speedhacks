import type { AgentRun } from '../../lib/types.js';
import type { Config } from './config.js';
import { normalizeCall, terminal, type DialProvider } from './dial.js';
import type { Extractor } from './extract.js';
import { inputSchema, phoneSchema } from './schema.js';
import { callInstruction } from './prompt.js';
import { FileStore, hash, type RunRecord } from './store.js';
import { unconfirmedChecks, verify } from './verify.js';

export class CallerEngine {
  constructor(readonly store: FileStore, private dial: DialProvider, private extractor: Extractor,
    private config: Config, private now: () => Date = () => new Date()) {}
  create(input: unknown, requestKey: string): RunRecord {
    if (!requestKey.trim() || requestKey.length > 200) throw new Error('Provide a stable Idempotency-Key (1–200 characters)');
    const parsed = inputSchema.parse(input), inputHash = hash(JSON.stringify(parsed));
    const id = hash(requestKey).slice(0, 24), existing = this.store.get(id);
    if (existing) {
      if (existing.inputHash !== inputHash) throw new Error('Idempotency-Key already belongs to different input');
      return existing;
    }
    if (!this.config.LIVE_CALLS_ENABLED) throw new Error('Live calls disabled; run npm run demo, or enable live calls with an approved recipient allowlist');
    const listings = structuredClone(parsed.listings), issues: string[] = [];
    for (const listing of listings) {
      if (listing.status === 'ruled_out') continue;
      if ((listing.rentUsd !== null && listing.rentUsd > parsed.brief.maxTotalRentUsd) || (listing.commuteMinutes !== null && listing.commuteMinutes > parsed.brief.commute.maxMinutes)) {
        listing.status = 'ruled_out'; listing.ruledOutReason = 'breaks_must_have';
        listing.ruledOutNote = listing.rentUsd !== null && listing.rentUsd > parsed.brief.maxTotalRentUsd ? 'Advertised rent exceeds the household ceiling' : 'Listed commute exceeds the household limit';
      }
    }
    const seen = new Set<string>();
    const eligible = listings.filter(l => {
      if (l.status === 'ruled_out') return false;
      if (!l.contact.phone) { issues.push(`${l.id}: no callable contact supplied`); return false; }
      if (seen.has(l.contact.phone)) { issues.push(`${l.id}: same contact already selected; not called twice`); return false; }
      seen.add(l.contact.phone); return true;
    }).slice(0, this.config.MAX_CALLS_PER_RUN);
    for (const listing of eligible) {
      phoneSchema.parse(listing.contact.phone);
      if (/^\+1\d{3}55501\d{2}$/.test(listing.contact.phone)) throw new Error('Fictional 555 demo numbers cannot be dialed');
      if (!this.config.DIAL_ALLOWED_NUMBERS.includes(listing.contact.phone)) throw new Error(`Recipient for ${listing.id} is not in DIAL_ALLOWED_NUMBERS`);
      if (this.store.isBlocked(listing.contact.phone)) throw new Error(`Contact for ${listing.id} is on the do-not-call list`);
    }
    const record: RunRecord = {
      id, inputHash, input: parsed, mode: 'live', phase: eligible.length ? 'queued' : 'done',
      run: { householdId: parsed.brief.householdId, startedAt: this.now().toISOString(), finishedAt: eligible.length ? null : this.now().toISOString(),
        listings, calls: [], checks: [], offeredWindows: [] },
      attempts: eligible.map(l => ({ listingId: l.id, key: `keyhunt-${id}-${hash(l.id).slice(0, 16)}`, phase: 'queued' })), issues
    };
    if (eligible.length < listings.filter(l => l.status === 'found').length) record.issues.push('Some listings remain uncalled; inspect missing contacts, duplicates and MAX_CALLS_PER_RUN');
    this.store.save(record); return record;
  }
  async tick(): Promise<void> {
    const release = this.store.acquireWorker(); if (!release) return;
    try {
      const records = this.store.all().filter(r => r.phase !== 'done');
      // An uncertain or active call prevents another call from starting across runs.
      const uncertain = records.find(r => r.attempts.some(a => a.phase === 'attention' && (!a.raw || !terminal(a.raw))));
      if (uncertain) return;
      const record = records.find(r => r.phase !== 'attention' && r.attempts.some(a => ['placing', 'waiting', 'extracting'].includes(a.phase)))
        ?? records.find(r => r.phase === 'queued' || r.phase === 'running');
      if (!record) return;
      const attempt = record.attempts.find(a => a.phase !== 'done'); if (!attempt) return;
      const listing = record.run.listings.find(l => l.id === attempt.listingId)!;
      record.phase = 'running';
      try {
        if (attempt.phase === 'queued' || attempt.phase === 'placing') {
          // Rechecked after queueing: settings or DNC state may have changed.
          if (!this.config.LIVE_CALLS_ENABLED || !this.config.DIAL_ALLOWED_NUMBERS.includes(listing.contact.phone) || this.store.isBlocked(listing.contact.phone)) throw new Error('Call blocked by current calling settings or do-not-call list');
          const day = this.now().toISOString().slice(0, 10);
          const previous = this.store.all().flatMap(r => r.attempts.filter(a => a.key !== attempt.key && a.startedAt?.startsWith(day)
            && r.input.listings.find(l => l.id === a.listingId)?.contact.phone === listing.contact.phone));
          if (previous.length >= this.config.MAX_CALLS_PER_NUMBER_PER_DAY) throw new Error('Daily call limit reached for this contact; do not create another attempt');
          attempt.phase = 'placing'; attempt.startedAt ??= this.now().toISOString(); this.store.save(record);
          const raw = await this.dial.place(listing.contact.phone,
            callInstruction(record.input.brief, listing, attempt.startedAt, this.config.CALLER_TIMEZONE), attempt.key);
          attempt.dialCallId = raw.id; attempt.raw = raw; attempt.phase = 'waiting'; listing.status = 'called'; this.store.save(record);
          return;
        }
        if (attempt.phase === 'waiting') {
          const raw = await this.dial.get(attempt.dialCallId!); attempt.raw = raw;
          if (!terminal(raw)) {
            if (this.now().getTime() - Date.parse(attempt.startedAt!) > this.config.CALL_TIMEOUT_SECONDS * 1000) throw new Error('Call polling timed out; inspect the existing Dial call before resuming. No replacement call was started.');
            this.store.save(record); return;
          }
          attempt.terminalAt ??= this.now().toISOString();
          const call = normalizeCall(raw, listing.id, attempt.startedAt!);
          // A final call event may arrive before the transcript. Wait for timed contact turns.
          if (!call.transcript.some(t => t.speaker === 'contact') && this.now().getTime() - Date.parse(attempt.terminalAt) < this.config.TRANSCRIPT_GRACE_SECONDS * 1000) {
            this.store.save(record); return;
          }
          if (call.transcript.some(t => t.speaker === 'contact') && call.outcome === 'answered') {
            attempt.phase = 'extracting'; this.store.save(record);
          } else {
            record.run.calls.push(call);
            record.run.checks.push(...unconfirmedChecks(listing.id, call.outcome === 'no_answer' ? 'No answer' : call.outcome === 'voicemail' ? 'Voicemail; not verified' : 'Call failed or timed transcript unavailable'));
            if (call.outcome === 'no_answer') { listing.status = 'ruled_out'; listing.ruledOutReason = 'no_answer'; listing.ruledOutNote = 'No answer'; }
            else record.issues.push(`${listing.id}: ${call.outcome}; not verified`);
            attempt.phase = 'done';
          }
        }
        if (attempt.phase === 'extracting') {
          const call = normalizeCall(attempt.raw!, listing.id, attempt.startedAt!);
          // Persist an opt-out before the model call so an extraction outage cannot lose it.
          if (call.transcript.some(t => t.speaker === 'contact' && /\b(do not|don't|stop) call(ing)?|remove (me|my number)|never call/i.test(t.text))) this.store.block(listing.contact.phone);
          const assessment = await this.extractor.extract(call, listing, record.input.brief, this.config.CALLER_TIMEZONE);
          const result = verify(assessment, call, listing, record.input.brief);
          if (result.doNotCall) this.store.block(listing.contact.phone);
          record.run.listings = record.run.listings.map(l => l.id === listing.id ? result.listing : l);
          record.run.calls.push(result.call); record.run.checks.push(...result.checks); record.run.offeredWindows.push(...result.offeredWindows);
          record.issues.push(...result.warnings.map(w => `${listing.id}: ${w}`));
          attempt.verification = result; attempt.phase = 'done';
        }
        if (record.attempts.every(a => a.phase === 'done')) { record.phase = 'done'; record.run.finishedAt = this.now().toISOString(); }
        this.store.save(record);
      } catch (error) {
        attempt.phase = 'attention'; attempt.error = error instanceof Error ? error.message : 'Call processing failed';
        record.phase = 'attention'; this.store.save(record);
      }
    } finally { release(); }
  }
  resume(id: string): RunRecord {
    const record = this.store.get(id); if (!record) throw new Error('Run not found');
    for (const attempt of record.attempts.filter(a => a.phase === 'attention')) {
      attempt.phase = attempt.dialCallId ? 'waiting' : 'placing';
      delete attempt.error;
    }
    if (record.phase !== 'attention') return record;
    record.phase = 'running';
    this.store.save(record); return record;
  }
  result(id: string): AgentRun | undefined { return this.store.get(id)?.run; }
}
