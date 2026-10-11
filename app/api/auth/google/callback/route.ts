import { NextResponse, type NextRequest } from "next/server";
import { safeEqual, unsign } from "@/lib/crypto";
import { connectCalendar, signInWithGoogle } from "@/lib/google";
import { findHouseholdByCode, findHousemateByAccount, isMember } from "@/lib/households";
import { getHousemateId, setAccount, setHousemateSession } from "@/lib/session";

export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  const [first, second, nonce] = (unsign(params.get("state") ?? undefined) ?? "").split(":");
  const cookieNonce = request.cookies.get("kh_oauth")?.value ?? "";
  if (!nonce || !cookieNonce || !safeEqual(nonce, cookieNonce)) return NextResponse.redirect(new URL("/", request.url));

  const response =
    first === "signin" ? await finishSignIn(request, second) : await finishCalendar(request, first, second);
  response.cookies.delete({ name: "kh_oauth", path: "/api/auth/google" });
  return response;
}

async function finishSignIn(request: NextRequest, joinCode: string) {
  const join = new URL(joinCode ? `/join/${joinCode}` : "/", request.url);
  const household = joinCode ? await findHouseholdByCode(joinCode) : null;
  if (joinCode && !household) return NextResponse.redirect(new URL("/", request.url));

  const code = request.nextUrl.searchParams.get("code");
  if (!code) {
    join.searchParams.set("signin", "declined");
    return NextResponse.redirect(join);
  }
  try {
    const account = await signInWithGoogle(code);
    await setAccount(account);
    // Someone who already joined from another browser gets straight back into their answers.
    const existing = household && (await findHousemateByAccount(household.id, account.sub));
    if (household && existing) await setHousemateSession(household.id, existing);
  } catch {
    join.searchParams.set("signin", "failed");
  }
  return NextResponse.redirect(join);
}

async function finishCalendar(request: NextRequest, householdId: string, housemateId: string) {
  const valid =
    householdId &&
    (await getHousemateId(householdId)) === housemateId &&
    (await isMember(householdId, housemateId));
  if (!valid) return NextResponse.redirect(new URL("/", request.url));

  const settings = new URL(`/h/${householdId}/settings`, request.url);
  const code = request.nextUrl.searchParams.get("code");
  if (!code) {
    settings.searchParams.set("calendar", "declined");
  } else {
    try {
      await connectCalendar(housemateId, code);
      settings.searchParams.set("calendar", "connected");
    } catch {
      settings.searchParams.set("calendar", "failed");
    }
  }
  return NextResponse.redirect(settings);
}
