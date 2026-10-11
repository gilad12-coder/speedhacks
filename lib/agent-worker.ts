import "server-only";
import { env } from "./env";

// The secret only crosses the configured server-to-server boundary; never a browser URL.
export async function workerRequest(path: string, init: RequestInit = {}) {
  const base = process.env.AGENT_WORKER_URL?.replace(/\/$/, "");
  if (!base) throw new Error("Agent worker is not connected");
  const url = new URL(base);
  if (url.protocol !== "https:" && !(url.protocol === "http:" && ["127.0.0.1", "localhost"].includes(url.hostname))) {
    throw new Error("Agent worker requires HTTPS");
  }
  return fetch(`${base}${path}`, {
    ...init, cache: "no-store", redirect: "error", signal: AbortSignal.timeout(15_000),
    headers: { ...init.headers, Authorization: `Bearer ${env.agentApiKey}` },
  });
}

