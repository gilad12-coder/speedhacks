import { createServer, type IncomingMessage } from 'node:http';
import { timingSafeEqual } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import type { CallerEngine } from './engine.js';
import { liveRuntime } from './runtime.js';

function authenticated(req: IncomingMessage, token: string): boolean {
  const actual = Buffer.from(req.headers.authorization ?? ''), expected = Buffer.from(`Bearer ${token}`);
  return actual.length === expected.length && timingSafeEqual(actual, expected);
}
async function body(req: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = []; let size = 0;
  for await (const chunk of req) {
    size += chunk.length; if (size > 512_000) throw new Error('Request exceeds 512 KB');
    chunks.push(Buffer.from(chunk));
  }
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}
export function createCallerServer(engine: CallerEngine, token: string) {
  if (token.length < 24) throw new Error('Set CALLER_API_TOKEN to at least 24 random characters');
  return createServer(async (req, res) => {
    res.setHeader('content-type', 'application/json'); res.setHeader('cache-control', 'no-store');
    const reply = (status: number, value: unknown) => { res.statusCode = status; res.end(JSON.stringify(value)); };
    const path = new URL(req.url ?? '/', 'http://localhost').pathname;
    if (req.method === 'GET' && path === '/health') { reply(200, { ok: true, service: 'keyhunt-caller' }); return; }
    if (!authenticated(req, token)) { reply(401, { error: 'Unauthorized' }); return; }
    try {
      if (req.method === 'POST' && path === '/v1/runs') {
        const key = req.headers['idempotency-key'];
        if (typeof key !== 'string') { reply(400, { error: 'Idempotency-Key is required' }); return; }
        const record = engine.create(await body(req), key);
        reply(202, { runId: record.id, statusUrl: `/v1/runs/${record.id}`, phase: record.phase }); return;
      }
      const match = path.match(/^\/v1\/runs\/([a-f0-9]{24})(\/resume|\/result)?$/);
      if (match) {
        const record = engine.store.get(match[1]);
        if (!record) { reply(404, { error: 'Run not found' }); return; }
        if (req.method === 'POST' && match[2] === '/resume') {
          reply(202, { runId: engine.resume(record.id).id, phase: 'running' }); return;
        }
        if (req.method === 'GET') {
          if (match[2] === '/result') { reply(200, record.run); return; }
          if (match[2]) { reply(405, { error: 'Method not allowed' }); return; }
          reply(200, { runId: record.id, phase: record.phase, issues: record.issues,
            attempts: record.attempts.map(a => ({ listingId: a.listingId, phase: a.phase, error: a.error })), run: record.run }); return;
        }
      }
      reply(404, { error: 'Not found' });
    } catch (error) { reply(400, { error: error instanceof Error ? error.message : 'Request rejected' }); }
  });
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const { config, engine } = liveRuntime();
  const server = createCallerServer(engine, config.CALLER_API_TOKEN);
  const timer = setInterval(() => { void engine.tick().catch(() => console.error('Worker error; inspect saved run state')); }, 3000);
  server.listen(config.PORT, config.HOST, () => console.log(`Keyhunt caller listening on ${config.HOST}:${config.PORT}`));
  const shutdown = () => { clearInterval(timer); server.close(); };
  process.on('SIGTERM', shutdown); process.on('SIGINT', shutdown);
}
