import { NextResponse, type NextRequest } from "next/server";
import { newId, sign } from "@/lib/crypto";
import { googleSignInUrl } from "@/lib/google";
import { findHouseholdByCode } from "@/lib/households";

export async function GET(request: NextRequest) {
  const joinCode = request.nextUrl.searchParams.get("code") ?? "";
  // No code means signing in from the landing page, before any household exists.
  if (joinCode && !(await findHouseholdByCode(joinCode))) return NextResponse.redirect(new URL("/", request.url));

  const nonce = newId();
  const response = NextResponse.redirect(googleSignInUrl(sign(`signin:${joinCode}:${nonce}`)));
  response.cookies.set("kh_oauth", nonce, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/api/auth/google",
    maxAge: 600,
  });
  return response;
}
