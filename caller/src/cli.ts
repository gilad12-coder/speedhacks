import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { setTimeout } from 'node:timers/promises';
import { loadConfig } from './config.js';
import { demoRun } from './demo.js';
import { inputSchema } from './schema.js';
import { callInstruction } from './prompt.js';
import { liveRuntime } from './runtime.js';

async function main() {
  const [command, file, requestKey] = process.argv.slice(2);
  const config = loadConfig();
  if (command === 'demo') {
    mkdirSync(config.CALLER_DATA_DIR, { recursive: true, mode: 0o700 });
    const output = join(config.CALLER_DATA_DIR, 'synthetic-agent-run.json');
    writeFileSync(output, JSON.stringify(demoRun(), null, 2), { mode: 0o600 });
    console.log(JSON.stringify({ mode: 'synthetic fixture — no real call', output, checks: demoRun().checks.map(c => ({ kind: c.kind, passed: c.passed })) }, null, 2));
    return;
  }
  if (!file || !['preview', 'call'].includes(command)) throw new Error('Usage: npm run preview -- input.json OR npm run call -- input.json stable-request-key');
  const input = inputSchema.parse(JSON.parse(readFileSync(file, 'utf8')));
  if (command === 'preview') {
    for (const listing of input.listings) console.log(callInstruction(input.brief, listing, new Date().toISOString(), config.CALLER_TIMEZONE));
    return;
  }
  if (!requestKey) throw new Error('A stable request key is required; use the same key when resuming');
  const { engine } = liveRuntime();
  const record = engine.create(input, requestKey);
  console.log(JSON.stringify({ runId: record.id, phase: record.phase }));
  while (true) {
    await engine.tick();
    const current = engine.store.get(record.id)!;
    if (current.phase === 'done') { console.log(JSON.stringify(current.run, null, 2)); return; }
    if (current.phase === 'attention') throw new Error(`Run ${current.id} needs attention: ${current.attempts.find(a => a.error)?.error}. Transcript and call ID are saved.`);
    await setTimeout(3000);
  }
}
main().catch(error => { console.error(error instanceof Error ? error.message : 'Caller failed'); process.exitCode = 1; });
