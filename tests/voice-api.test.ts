import { beforeEach, describe, expect, it, vi } from 'vitest';
vi.mock('@/lib/households', () => ({ isMember: vi.fn() }));
vi.mock('@/lib/session', () => ({ getHousemateId: vi.fn(async () => 'person-a') }));
vi.mock('@/lib/agent-worker', () => ({ workerRequest: vi.fn() }));
import { isMember } from '@/lib/households';
import { workerRequest } from '@/lib/agent-worker';
import { GET, POST, DELETE } from '../app/api/h/[id]/voice/[[...action]]/route';
const context = (action?: string[]) => ({ params: Promise.resolve({ id: 'home-a', action }) });
const base = 'https://keyhunt.example/api/h/home-a/voice';
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(isMember).mockResolvedValue(true);
  vi.mocked(workerRequest).mockResolvedValue(Response.json({ phase: 'creating' }, { status: 202 }));
});
describe('voice enrollment household boundary', () => {
  it('rejects nonmembers before contacting the worker', async () => {
    vi.mocked(isMember).mockResolvedValue(false);
    expect((await GET(new Request(base), context())).status).toBe(401);
    expect(workerRequest).not.toHaveBeenCalled();
  });
  it('requires a same-origin mutation with the custom header', async () => {
    for (const headers of [{} as Record<string, string>, { 'X-KeyHunt-Voice':'1', Origin:'https://unrelated.example' }]) {
      expect((await POST(new Request(base, { method:'POST', headers }), context())).status).toBe(403);
    }
    expect(workerRequest).not.toHaveBeenCalled();
  });
  it('rejects oversized audio before forwarding it', async () => {
    const request = new Request(base, { method:'POST', headers: { 'X-KeyHunt-Voice':'1', 'Content-Length':'4000001' } });
    expect((await POST(request, context())).status).toBe(413);
    expect(workerRequest).not.toHaveBeenCalled();
  });
  it('forwards the consented audio only to the authenticated household path', async () => {
    const request = new Request(base, { method:'POST', body:new Uint8Array([1,2,3]), headers: {
      'X-KeyHunt-Voice':'1', 'Content-Type':'audio/wav', 'X-Voice-Consent':'true', 'X-Voice-Name':'Reed', Origin:'https://keyhunt.example' } });
    const response = await POST(request, context());
    expect(response.status).toBe(202);
    expect(response.headers.get('cache-control')).toBe('private, no-store');
    expect(workerRequest).toHaveBeenCalledWith('/agent/households/home-a/voice', expect.objectContaining({ method:'POST', headers:expect.objectContaining({ 'X-Voice-Consent':'true' }) }));
  });
  it('does not forward arbitrary subpaths or delete preview endpoints', async () => {
    expect((await GET(new Request(base), context(['../secrets']))).status).toBe(404);
    expect((await DELETE(new Request(base, { method:'DELETE' }), context(['preview']))).status).toBe(404);
    expect(workerRequest).not.toHaveBeenCalled();
  });
});
