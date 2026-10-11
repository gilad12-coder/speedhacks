import { test, type TestContext } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { loadConfig } from '../src/config.js';
import { CallerEngine } from '../src/engine.js';
import { FileStore } from '../src/store.js';
import { demoFixture } from '../src/demo.js';
import type { DialProvider } from '../src/dial.js';
import type { Extractor } from '../src/extract.js';

function setup(t: TestContext) {
  const fixture = demoFixture(); fixture.input.listings[0].contact.phone = '+12025552222';
  const dir = mkdtempSync(join(tmpdir(), 'keyhunt-test-')); t.after(() => rmSync(dir, { recursive: true, force: true }));
  const store = new FileStore(dir);
  const config = loadConfig({ LIVE_CALLS_ENABLED: 'true', DIAL_ALLOWED_NUMBERS: '+12025552222' });
  const keys: string[] = [];
  const dial: DialProvider = { async place(_to, _prompt, key) { keys.push(key); return { id: fixture.raw.id, status: 'Queued' }; }, async get() { return fixture.raw; } };
  const extractor: Extractor = { async extract() { return fixture.assessment; } };
  const engine = new CallerEngine(store, dial, extractor, config, () => new Date('2026-10-11T20:03:00Z'));
  return { fixture, store, config, keys, dial, extractor, engine };
}
test('saved run resumes after restart and returns the shared AgentRun', async t => {
  const x = setup(t), record = x.engine.create(x.fixture.input, 'first');
  await x.engine.tick(); assert.equal(x.store.get(record.id)!.attempts[0].phase, 'waiting');
  const restarted = new CallerEngine(x.store, x.dial, x.extractor, x.config);
  await restarted.tick(); const result = x.store.get(record.id)!;
  assert.equal(result.phase, 'done'); assert.equal(result.run.checks.length, 4); assert.equal(result.run.listings[0].status, 'tour_offered'); assert.equal(x.keys.length, 1);
});
test('same request key does not call twice and cannot change input', async t => {
  const x = setup(t); const a = x.engine.create(x.fixture.input, 'same');
  assert.equal(x.engine.create(x.fixture.input, 'same').id, a.id);
  x.fixture.input.brief.occupants = 4;
  assert.throws(() => x.engine.create(x.fixture.input, 'same'), /different input/);
  await x.engine.tick(); await x.engine.tick(); await x.engine.tick(); assert.equal(x.keys.length, 1);
});
test('ambiguous placement retries the same provider key only after explicit resume', async t => {
  const x = setup(t); let first = true;
  const place = x.dial.place;
  x.dial.place = async (...args) => { if (first) { first = false; x.keys.push(args[2]); throw new Error('Network timeout'); } return place(...args); };
  const r = x.engine.create(x.fixture.input, 'ambiguous');
  await x.engine.tick(); assert.equal(x.store.get(r.id)!.phase, 'attention');
  await x.engine.tick(); assert.equal(x.keys.length, 1);
  x.engine.resume(r.id); await x.engine.tick(); assert.equal(x.keys[0], x.keys[1]);
});
test('delayed timed transcripts are awaited without completing the run', async t => {
  const x = setup(t); x.dial.get = async () => ({ ...x.fixture.raw, transcriptTurns: [] });
  const r = x.engine.create(x.fixture.input, 'delayed'); await x.engine.tick(); await x.engine.tick();
  assert.equal(x.store.get(r.id)!.phase, 'running'); assert.equal(x.store.get(r.id)!.run.calls.length, 0);
});
test('allowlist, disabled live mode, fictional numbers and DNC block calls', t => {
  const x = setup(t); x.config.LIVE_CALLS_ENABLED = false;
  assert.throws(() => x.engine.create(x.fixture.input, 'disabled'), /disabled/);
  x.config.LIVE_CALLS_ENABLED = true; x.config.DIAL_ALLOWED_NUMBERS = [];
  assert.throws(() => x.engine.create(x.fixture.input, 'not-approved'), /not in/);
  x.config.DIAL_ALLOWED_NUMBERS = ['+12025552222']; x.store.block('+12025552222');
  assert.throws(() => x.engine.create(x.fixture.input, 'blocked'), /do-not-call/);
  x.fixture.input.listings[0].contact.phone = '+14155550123';
  assert.throws(() => x.engine.create(x.fixture.input, 'fake'), /Fictional/);
  assert.equal(x.keys.length, 0);
});
test('opt-out is persisted even if model extraction fails', async t => {
  const x = setup(t); x.fixture.raw.transcriptTurns![0].text = "Please don't call me again";
  x.extractor.extract = async () => { throw new Error('Provider down'); };
  const r = x.engine.create(x.fixture.input, 'opt-out'); await x.engine.tick(); await x.engine.tick();
  assert.equal(x.store.isBlocked('+12025552222'), true); assert.equal(x.store.get(r.id)!.phase, 'attention');
});
test('a new run cannot bypass the daily contact cap with a new request key', async t => {
  const x = setup(t);
  x.engine.create(x.fixture.input, 'first-contact');
  await x.engine.tick(); await x.engine.tick();
  const second = x.engine.create(x.fixture.input, 'second-contact');
  await x.engine.tick();
  assert.equal(x.keys.length, 1);
  assert.equal(x.store.get(second.id)!.phase, 'attention');
  assert.match(x.store.get(second.id)!.attempts[0].error!, /Daily call limit/);
});
