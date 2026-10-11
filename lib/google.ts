import "server-only";
import { decrypt, encrypt } from "./crypto";
import { sql } from "./db";
import { env } from "./env";
import type { Interval } from "./slots";

export const GOOGLE_SCOPES = [
  "https://www.googleapis.com/auth/calendar.freebusy",
  "https://www.googleapis.com/auth/calendar.events",
];

const redirectUri = () => `${env.appUrl}/api/auth/google/callback`;

export function googleAuthUrl(state: string, loginHint?: string): string {
  const params = new URLSearchParams({
    client_id: env.googleClientId,
    redirect_uri: redirectUri(),
    response_type: "code",
    scope: GOOGLE_SCOPES.join(" "),
    access_type: "offline",
    // Forces a refresh token even if this Google account connected before.
    prompt: "consent",
    include_granted_scopes: "true",
    state,
  });
  // Skips Google's account picker when the housemate already signed in with this account.
  if (loginHint) params.set("login_hint", loginHint);
  return `https://accounts.google.com/o/oauth2/v2/auth?${params}`;
}

// Sign-in shares the calendar callback URL, so no extra redirect URI has to be registered with Google.
export function googleSignInUrl(state: string): string {
  const params = new URLSearchParams({
    client_id: env.googleClientId,
    redirect_uri: redirectUri(),
    response_type: "code",
    scope: "openid email profile",
    prompt: "select_account",
    state,
  });
  return `https://accounts.google.com/o/oauth2/v2/auth?${params}`;
}

interface TokenResponse {
  access_token: string;
  id_token?: string;
  expires_in: number;
  refresh_token?: string;
  scope: string;
}

async function tokenRequest(body: Record<string, string>): Promise<TokenResponse> {
  const res = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ client_id: env.googleClientId, client_secret: env.googleClientSecret, ...body }),
  });
  if (!res.ok) throw new GoogleError(`Google token request failed (${res.status})`, res.status);
  return res.json();
}

export class GoogleError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

export async function connectCalendar(housemateId: string, code: string) {
  const tokens = await tokenRequest({ code, grant_type: "authorization_code", redirect_uri: redirectUri() });
  const granted = tokens.scope.split(" ");
  if (!tokens.refresh_token || !GOOGLE_SCOPES.every((s) => granted.includes(s))) {
    throw new GoogleError("Calendar access was not fully granted", 403);
  }
  await sql`
    update housemates set
      google_refresh_token = ${encrypt(tokens.refresh_token)},
      google_access_token = ${encrypt(tokens.access_token)},
      google_token_expires_at = ${new Date(Date.now() + (tokens.expires_in - 60) * 1000)}
    where id = ${housemateId}`;
}

export async function signInWithGoogle(code: string) {
  const tokens = await tokenRequest({ code, grant_type: "authorization_code", redirect_uri: redirectUri() });
  if (!tokens.id_token) throw new GoogleError("Google didn't return an identity", 403);
  // The token came straight from Google's token endpoint over TLS, so its claims can be read without checking the signature.
  const claims = JSON.parse(Buffer.from(tokens.id_token.split(".")[1], "base64url").toString("utf8"));
  const issuerOk = claims.iss === "https://accounts.google.com" || claims.iss === "accounts.google.com";
  if (!issuerOk || claims.aud !== env.googleClientId || !claims.email_verified) {
    throw new GoogleError("Google identity could not be verified", 403);
  }
  return {
    sub: String(claims.sub),
    email: String(claims.email),
    firstName: String(claims.given_name ?? ""),
    lastName: String(claims.family_name ?? ""),
    picture: typeof claims.picture === "string" ? claims.picture : undefined,
  };
}

async function accessToken(housemateId: string): Promise<string> {
  const [row] = await sql<{ refresh: string | null; access: string | null; expires: Date | null }[]>`
    select google_refresh_token as refresh, google_access_token as access, google_token_expires_at as expires
    from housemates where id = ${housemateId}`;
  if (!row?.refresh) throw new GoogleError("Calendar not connected", 401);
  if (row.access && row.expires && row.expires.getTime() > Date.now()) return decrypt(row.access);

  try {
    const tokens = await tokenRequest({ refresh_token: decrypt(row.refresh), grant_type: "refresh_token" });
    await sql`
      update housemates set
        google_access_token = ${encrypt(tokens.access_token)},
        google_token_expires_at = ${new Date(Date.now() + (tokens.expires_in - 60) * 1000)}
      where id = ${housemateId}`;
    return tokens.access_token;
  } catch (error) {
    // A revoked or expired grant: drop it so the UI asks this housemate to reconnect.
    if (error instanceof GoogleError && error.status === 400) {
      await sql`
        update housemates set google_refresh_token = null, google_access_token = null, google_token_expires_at = null
        where id = ${housemateId}`;
    }
    throw error;
  }
}

async function calendarFetch<T>(housemateId: string, path: string, body: unknown): Promise<T> {
  const res = await fetch(`https://www.googleapis.com/calendar/v3${path}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${await accessToken(housemateId)}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new GoogleError(`Google Calendar request failed (${res.status})`, res.status);
  return res.json();
}

export async function busyIntervals(housemateId: string, range: Interval): Promise<Interval[]> {
  const data = await calendarFetch<{ calendars: Record<string, { busy: { start: string; end: string }[] }> }>(
    housemateId,
    "/freeBusy",
    { timeMin: new Date(range.start).toISOString(), timeMax: new Date(range.end).toISOString(), items: [{ id: "primary" }] },
  );
  return (data.calendars.primary?.busy ?? []).map((b) => ({ start: Date.parse(b.start), end: Date.parse(b.end) }));
}

export async function createEvent(
  housemateId: string,
  event: { summary: string; location: string; description: string; start: Date; end: Date },
): Promise<string> {
  const created = await calendarFetch<{ id: string }>(housemateId, "/calendars/primary/events", {
    summary: event.summary,
    location: event.location,
    description: event.description,
    start: { dateTime: event.start.toISOString(), timeZone: "America/Los_Angeles" },
    end: { dateTime: event.end.toISOString(), timeZone: "America/Los_Angeles" },
    reminders: { useDefault: true },
  });
  return created.id;
}
