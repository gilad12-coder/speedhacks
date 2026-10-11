import { NextResponse, type NextRequest } from "next/server";
import { newId, sign } from "@/lib/crypto";
import { googleAuthUrl } from "@/lib/google";
import { isMember } from "@/lib/households";
import { getAccount, getHousemateId } from "@/lib/session";

export async function GET(request: NextRequest) {
  const householdId = request.nextUrl.searchParams.get("household") ?? "";
  const housemateId = await getHousemateId(householdId);
  if (!(await isMember(householdId, housemateId))) {
    return NextResponse.redirect(new URL("/", request.url));
  }
  const nonce = newId();
  const response = NextResponse.redirect(googleAuthUrl(sign(`${householdId}:${housemateId}:${nonce}`), (await getAccount())?.email));
  // Binds the OAuth round trip to this browser so a forged callback can't attach someone else's calendar.
  response.cookies.set("kh_oauth", nonce, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/api/auth/google",
    maxAge: 600,
  });
  return response;
}
