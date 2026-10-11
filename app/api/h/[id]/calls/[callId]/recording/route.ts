import { isMember, getAgentRun } from "@/lib/households";
import { getHousemateId } from "@/lib/session";
import { workerRequest } from "@/lib/agent-worker";

export async function GET(request: Request, { params }: { params: Promise<{ id: string; callId: string }> }) {
  const { id, callId } = await params;
  if (!(await isMember(id, await getHousemateId(id)))) return new Response(null, { status: 401 });
  const run = await getAgentRun(id);
  if (!/^\d+$/.test(callId) || !run?.calls.some((c) => c.id === callId && c.audioUrl)) return new Response(null, { status: 404 });
  try {
    const range = request.headers.get("range");
    const result = await workerRequest(`/agent/households/${encodeURIComponent(id)}/calls/${callId}/recording`, {
      headers: range ? { Range: range } : {},
    });
    const headers = new Headers({ "Cache-Control": "private, no-store" });
    for (const name of ["Content-Type", "Content-Length", "Content-Range", "Accept-Ranges"]) {
      const value = result.headers.get(name);
      if (value) headers.set(name, value);
    }
    return new Response(result.body, { status: result.status, headers });
  } catch {
    return new Response(null, { status: 502 });
  }
}
