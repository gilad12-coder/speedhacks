import { isMember } from "@/lib/households";
import { getHousemateId } from "@/lib/session";
import { workerRequest } from "@/lib/agent-worker";

type Context = { params: Promise<{ id: string; action?: string[] }> };
export const maxDuration = 30;

async function handle(request: Request, { params }: Context) {
  const { id, action = [] } = await params;
  if (!(await isMember(id, await getHousemateId(id)))) return new Response(null, { status: 401 });
  const suffix = action.join("/");
  const method = request.method;
  if (!({ GET: ["", "preview"], POST: ["", "approve", "preview"], DELETE: [""] }[method]?.includes(suffix))) {
    return new Response(null, { status: 404 });
  }
  const headers: Record<string, string> = { "X-KeyHunt-Voice": "1" };
  let body: ArrayBuffer | undefined;
  if (method !== "GET") {
    if (request.headers.get("x-keyhunt-voice") !== "1" || request.headers.get("sec-fetch-site") === "cross-site") {
      return new Response(null, { status: 403 });
    }
    const origin = request.headers.get("origin");
    if (origin && origin !== new URL(request.url).origin) return new Response(null, { status: 403 });
    const limit = suffix ? 1024 : 4_000_000;
    if (Number(request.headers.get("content-length")) > limit) return new Response(null, { status: 413 });
    if (request.body) {
      const reader = request.body.getReader();
      const parts: Uint8Array[] = []; let size = 0;
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        size += value.length;
        if (size > limit) { await reader.cancel(); return new Response(null, { status: 413 }); }
        parts.push(value);
      }
      const bytes = new Uint8Array(size); let offset = 0;
      for (const part of parts) { bytes.set(part, offset); offset += part.length; }
      body = bytes.buffer;
    }
    for (const name of ["Content-Type", "X-Voice-Consent", "X-Voice-Name"]) {
      const value = request.headers.get(name);
      if (value) headers[name] = value;
    }
  }
  try {
    const result = await workerRequest(`/agent/households/${encodeURIComponent(id)}/voice${suffix ? `/${suffix}` : ""}`, { method, headers, body });
    return new Response(result.body, { status: result.status, headers: {
      "Content-Type": result.headers.get("content-type") || "application/json",
      "Cache-Control": "private, no-store",
    } });
  } catch {
    return Response.json({ detail: "The voice service could not be reached. Refresh its status before retrying." }, { status: 502 });
  }
}

export { handle as GET, handle as POST, handle as DELETE };
