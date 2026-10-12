// This convenience login is exclusively for a development server bound to loopback.
export function personalMode(host: string | null, origin?: string | null): boolean {
  if (process.env.PERSONAL_MODE !== "1" || process.env.NODE_ENV !== "development") return false;
  try {
    const url = new URL(process.env.APP_URL ?? "");
    return url.protocol === "http:" && ["127.0.0.1", "localhost"].includes(url.hostname)
      && host === url.host && (origin === undefined || origin === url.origin);
  } catch { return false; }
}
