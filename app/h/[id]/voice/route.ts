import { isMember } from "@/lib/households";
import { getHousemateId } from "@/lib/session";
import { workerRequest } from "@/lib/agent-worker";

export async function GET(_: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!(await isMember(id, await getHousemateId(id)))) return new Response(null, { status: 404 });
  try {
    const page = await workerRequest(`/agent/households/${encodeURIComponent(id)}/voice/page`);
    return new Response(page.body, { status: page.status, headers: { "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "private, no-store", "Permissions-Policy": "microphone=(self)", "X-Content-Type-Options": "nosniff" } });
  } catch { return new Response("Voice setup is temporarily unavailable. Your search is saved; please try again.", { status: 503 }); }
}
