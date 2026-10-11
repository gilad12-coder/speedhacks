import { test } from 'node:test';
import assert from 'node:assert/strict';
import { once } from 'node:events';
import { mkdtempSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import type { AddressInfo } from 'node:net';
import { CallerEngine } from '../src/engine.js';
import { FileStore } from '../src/store.js';
import { loadConfig } from '../src/config.js';
import { createCallerServer } from '../src/server.js';
import { demoFixture } from '../src/demo.js';

test('HTTP handoff authenticates, creates idempotently and returns an exact AgentRun', async t => {
  const fixture = demoFixture(); fixture.input.listings[0].contact.phone = '+12025552222';
  const dir = mkdtempSync(join(tmpdir(), 'keyhunt-http-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const engine = new CallerEngine(new FileStore(dir), {
    async place() { return { id: fixture.raw.id, status: 'Queued' }; }, async get() { return fixture.raw; }
  }, { async extract() { return fixture.assessment; } }, loadConfig({ LIVE_CALLS_ENABLED: 'true', DIAL_ALLOWED_NUMBERS: '+12025552222' }));
  const token = 'test-only-abcdefghijklmnopqrstuvwxyz';
  const server = createCallerServer(engine, token); server.listen(0, '127.0.0.1'); await once(server, 'listening');
  t.after(() => { server.closeAllConnections(); server.close(); });
  const url = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  assert.equal((await fetch(`${url}/health`)).status, 200);
  assert.equal((await fetch(`${url}/v1/runs`, { method: 'POST' })).status, 401);
  const headers = { authorization: `Bearer ${token}`, 'content-type': 'application/json', 'idempotency-key': 'http-example' };
  const post = () => fetch(`${url}/v1/runs`, { method: 'POST', headers, body: JSON.stringify(fixture.input) });
  const response = await post(); assert.equal(response.status, 202);
  const accepted = await response.json() as { runId: string };
  assert.equal((await (await post()).json() as { runId: string }).runId, accepted.runId);
  await engine.tick(); await engine.tick();
  const result = await (await fetch(`${url}/v1/runs/${accepted.runId}/result`, { headers })).json() as Record<string, unknown>;
  assert.deepEqual(Object.keys(result).sort(), ['householdId', 'startedAt', 'finishedAt', 'listings', 'calls', 'checks', 'offeredWindows'].sort());
  assert.ok(result.finishedAt);
  assert.equal((result.calls as unknown[]).length, 1);
});
