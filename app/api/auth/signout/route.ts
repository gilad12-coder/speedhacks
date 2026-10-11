import { NextResponse, type NextRequest } from "next/server";
import { clearSessions } from "@/lib/session";

// A plain POST route rather than a server action, so signing out works however the form is submitted.
export async function POST(req: NextRequest) {
  const form = await req.formData();
  const code = String(form.get("joinCode") ?? "");
  await clearSessions();
  const to = /^[A-Za-z0-9_-]+$/.test(code) ? `/join/${code}` : "/";
  return NextResponse.redirect(new URL(to, req.url), 303);
}
