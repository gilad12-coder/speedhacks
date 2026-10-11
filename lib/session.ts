import "server-only";
import { cookies } from "next/headers";
import { sign, unsign } from "./crypto";

// One cookie per household, so one browser can belong to several households.
const cookieName = (householdId: string) => `kh_${householdId}`;

export async function setHousemateSession(householdId: string, housemateId: string) {
  (await cookies()).set(cookieName(householdId), sign(housemateId), {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 60 * 60 * 24 * 90,
  });
}

export async function getHousemateId(householdId: string): Promise<string | null> {
  return unsign((await cookies()).get(cookieName(householdId))?.value);
}

export interface Account {
  sub: string;
  email: string;
  firstName: string;
  lastName: string;
  picture?: string;
}

const ACCOUNT_COOKIE = "kh_account";

export async function setAccount(account: Account) {
  (await cookies()).set(ACCOUNT_COOKIE, sign(Buffer.from(JSON.stringify(account)).toString("base64url")), {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 60 * 60 * 24 * 90,
  });
}

export async function getAccount(): Promise<Account | null> {
  const value = unsign((await cookies()).get(ACCOUNT_COOKIE)?.value);
  if (!value) return null;
  try {
    return JSON.parse(Buffer.from(value, "base64url").toString("utf8"));
  } catch {
    return null;
  }
}

// Clears the account and every household session, so the next visit starts at sign-in.
export async function clearSessions() {
  const jar = await cookies();
  for (const { name } of jar.getAll()) if (name.startsWith("kh_")) jar.delete(name);
}
